"""Bounded multi-market extraction; validated manifests are the resume authority."""

import time
from collections import defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import httpx

from trade_analytics.ingestion.client import ComtradeClient
from trade_analytics.ingestion.exceptions import DataContractError, ResponseTruncatedError
from trade_analytics.ingestion.manifest import checksum, serialize_ndjson
from trade_analytics.ingestion.queries import ComtradeQuery, QueryType
from trade_analytics.ingestion.schemas import ComtradeResponse, TradeRecord
from trade_analytics.ingestion.service import validate_dataset
from trade_analytics.ingestion.storage import LocalStorage, read_source, scan_sources

MARKETS = {
    842: "美國",
    156: "中國",
    344: "香港",
    392: "日本",
    410: "韓國",
    702: "新加坡",
    458: "馬來西亞",
    276: "德國",
    528: "荷蘭",
    704: "越南",
}
PRODUCTS = {
    "854231": "處理器與控制器",
    "854232": "記憶體",
    "854233": "放大器",
    "854239": "其他積體電路",
    "854290": "零件",
}


def periods(start: str, end: str) -> list[str]:
    for value in (start, end):
        ComtradeQuery(period=value, query_type=QueryType.PARTNER_DETAIL)
    if start < "201601" or start > end:
        raise ValueError("range must start in 201601 or later and be ascending")
    result = []
    while start <= end:
        result.append(start)
        year, month = int(start[:4]), int(start[4:])
        start = f"{year + (month == 12):04d}{month % 12 + 1:02d}"
    return result


def accept_response(query: ComtradeQuery, response: ComtradeResponse) -> ComtradeQuery:
    """Discover the reported edition, never infer it from the calendar year."""
    versions = {row.classification_code for row in response.data}
    if len(versions) != 1 or any(
        row.is_original_classification is not True for row in response.data
    ):
        raise DataContractError("expected one original reported HS edition")
    return ComtradeQuery.model_validate(
        {
            **query.model_dump(),
            "expected_hs_version": versions.pop(),
        }
    )


class BudgetExhausted(Exception):
    """The bounded run needs another explicitly requested invocation."""


@dataclass
class RequestBudget:
    limit: int
    interval: float = 1.1
    requests: int = 0
    last_request: float | None = None

    def consume(self) -> None:
        if self.requests >= self.limit:
            raise BudgetExhausted
        if self.last_request is not None:
            time.sleep(max(0, self.interval - (time.monotonic() - self.last_request)))
        self.requests += 1
        self.last_request = time.monotonic()


@dataclass
class BatchResult:
    accepted: list[dict[str, Any]] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    requests: int = 0
    complete: bool = False


def plan_jobs(
    months: list[str], reporters: tuple[int, ...], existing: dict[str, Any], refresh: bool
) -> list[tuple[str, str, tuple[int, ...]]]:
    jobs = []
    for month in months:
        for product in PRODUCTS:
            group = tuple(
                r
                for r in reporters
                if refresh
                or any(f"{r}/{product}/{month}/{kind.value}" not in existing for kind in QueryType)
            )
            if group:
                jobs.append((month, product, group))
    return jobs


def fetch_complete(
    client: ComtradeClient, month: str, product: str, group: tuple[int, ...]
) -> Iterator[tuple[tuple[int, ...], ComtradeResponse]]:
    query = ComtradeQuery(
        period=month, cmd_code=product, reporter_codes=group, query_type=QueryType.PARTNER_DETAIL
    )
    try:
        yield group, client.fetch(query)
    except ResponseTruncatedError:
        if len(group) == 1:
            raise
        midpoint = len(group) // 2
        yield from fetch_complete(client, month, product, group[:midpoint])
        yield from fetch_complete(client, month, product, group[midpoint:])


def save_extracts(
    root: Path,
    month: str,
    product: str,
    group: tuple[int, ...],
    response: ComtradeResponse,
    existing: dict[str, Any],
    result: BatchResult,
    refresh: bool,
) -> None:
    grouped: dict[tuple[int, QueryType], list[TradeRecord]] = defaultdict(list)
    for row in response.data:
        if row.reporter_code not in group:
            raise DataContractError("response contains an unrequested reporter")
        kind = QueryType.WORLD_TOTAL if row.partner_code == 0 else QueryType.PARTNER_DETAIL
        grouped[row.reporter_code, kind].append(row)
    for reporter in group:
        for kind in QueryType:
            save_source(
                root,
                ComtradeQuery(
                    period=month, cmd_code=product, reporter_code=reporter, query_type=kind
                ),
                response,
                grouped[reporter, kind],
                existing,
                result,
                refresh,
            )


def save_source(
    root: Path,
    query: ComtradeQuery,
    response: ComtradeResponse,
    selected: list[TradeRecord],
    existing: dict[str, Any],
    result: BatchResult,
    refresh: bool,
) -> None:
    reporter, product, month, kind = (
        query.reporter_code,
        query.cmd_code,
        query.period,
        query.query_type,
    )
    identity = f"{reporter}/{product}/{month}/{kind.value}"
    previous = existing.get(identity)
    if previous and not refresh:
        return
    if not selected:
        if previous:
            raise DataContractError("refresh omitted previously accepted extract")
        result.unavailable.append(identity)
        return
    subset = response.model_copy(update={"data": selected, "count": len(selected)})
    query = accept_response(
        query,
        subset,
    )
    dataset = validate_dataset(query, subset)
    if previous and checksum(serialize_ndjson(dataset)) == previous["manifest"]["checksum"]:
        return
    revision = previous["manifest"]["revision"] + 1 if previous else 1
    dataset = replace(dataset, query=query.model_copy(update={"revision": revision}))
    stored = LocalStorage(root).write(dataset)
    existing[identity] = read_source(stored.manifest_path)


def run_batch(
    root: Path,
    *,
    months: list[str],
    reporters: tuple[int, ...],
    max_requests: int = 100,
    refresh: bool = False,
    api_key: str | None = None,
    completed: set[str] | None = None,
    on_group: Callable[[dict[str, Any], list[str]], None] | None = None,
) -> BatchResult:
    existing = scan_sources(root)
    completed = completed or set()
    result = BatchResult(accepted=list(existing.values()))
    budget = RequestBudget(max_requests)
    if on_group is not None and not refresh:
        on_group(existing, list(existing))
    with httpx.Client() as http:
        client = ComtradeClient(
            http_client=http,
            api_key=api_key,
            before_request=budget.consume,
        )
        try:
            for month, product, group in plan_jobs(months, reporters, existing, refresh):
                group = tuple(
                    r
                    for r in group
                    if any(f"{r}/{product}/{month}/{k.value}" not in completed for k in QueryType)
                )
                if not group:
                    continue
                for accepted_group, response in fetch_complete(client, month, product, group):
                    save_extracts(
                        root, month, product, accepted_group, response, existing, result, refresh
                    )
                    if on_group is not None:
                        identities = [
                            f"{r}/{product}/{month}/{k.value}"
                            for r in accepted_group
                            for k in QueryType
                        ]
                        on_group(existing, identities)
            result.complete = True
        except BudgetExhausted:
            pass
    result.requests = budget.requests
    result.accepted = list(existing.values())
    return result
