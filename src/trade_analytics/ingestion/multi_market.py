"""Bounded, resumable original-classification IC extracts across reporting markets."""

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from trade_analytics.ingestion.client import ComtradeClient
from trade_analytics.ingestion.exceptions import DataContractError
from trade_analytics.ingestion.manifest import checksum
from trade_analytics.ingestion.paths import relative_artifact_path, resolve_artifact
from trade_analytics.ingestion.queries import ComtradeQuery, QueryType
from trade_analytics.ingestion.schemas import ComtradeResponse
from trade_analytics.ingestion.service import IngestionService
from trade_analytics.ingestion.storage import LocalStorage

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


class CachedResponse:
    def __init__(self, response: ComtradeResponse) -> None:
        self.response = response

    def fetch(self, query: ComtradeQuery) -> ComtradeResponse:
        return self.response


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


def run_batch(
    root: Path,
    *,
    start: str,
    end: str,
    reporters: list[int],
    max_requests: int = 100,
    interval: float = 1.1,
    revision: int = 1,
    recent_from: str | None = None,
    refresh_recent: bool = False,
) -> dict[str, Any]:
    from trade_analytics.ingestion.exceptions import ResponseTruncatedError
    from trade_analytics.warehouse.writer_lock import writer_lock

    if (
        max_requests < 1
        or type(revision) is not int
        or revision < 1
        or interval < 1
        or not reporters
        or any(code not in MARKETS for code in reporters)
    ):
        raise ValueError("invalid batch bounds, rate limit, or reporter")
    months = periods(start, end)
    if recent_from is not None:
        ComtradeQuery(period=recent_from, query_type=QueryType.PARTNER_DETAIL)
    root.mkdir(parents=True, exist_ok=True)
    ledger_path = root / "batch-ledger.json"
    with writer_lock(root / "batch.lock"):
        ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
        requests = 0

        def persist() -> None:
            temporary = ledger_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n")
            temporary.replace(ledger_path)

        def refreshing(identity: str) -> bool:
            return (
                refresh_recent and recent_from is not None and identity.split("/")[2] >= recent_from
            )

        def ready(identity: str) -> bool:
            previous = ledger.get(identity, {})
            if previous.get("status") != "success":
                return False
            data = resolve_artifact(root, previous["data_path"])
            if data.exists() and data.with_name("manifest.json").exists():
                manifest = json.loads(data.with_name("manifest.json").read_bytes())
                if manifest["revision"] < revision:
                    return False
                expected_identity = (
                    f"{manifest['request_parameters']['reporterCode']}/"
                    f"{manifest['cmd_code']}/{manifest['period']}/"
                    f"{manifest['query_type']}"
                )
                if expected_identity != identity:
                    raise DataContractError("resume manifest identity mismatch")
                if checksum(data.read_bytes()) == manifest["checksum"]:
                    return not refreshing(identity)
            raise DataContractError(f"resume artifact failed validation: {identity}")

        with httpx.Client() as http:
            client = ComtradeClient(http_client=http, api_key=os.environ.get("COMTRADE_API_KEY"))

            def extract(month: str, product: str, group: list[int]) -> bool:
                nonlocal requests
                if requests >= max_requests:
                    return False
                query = ComtradeQuery(
                    period=month,
                    cmd_code=product,
                    reporter_codes=tuple(group),
                    query_type=QueryType.PARTNER_DETAIL,
                )
                requests += 1
                response = None
                try:
                    response = client.fetch(query)
                except ResponseTruncatedError:
                    if len(group) == 1:
                        raise
                finally:
                    time.sleep(interval)
                if response is None:
                    midpoint = len(group) // 2
                    return extract(month, product, group[:midpoint]) and extract(
                        month, product, group[midpoint:]
                    )
                for reporter in group:
                    rows = [row for row in response.data if row.reporter_code == reporter]
                    if not rows:
                        if any(
                            ledger.get(f"{reporter}/{product}/{month}/{kind.value}", {}).get(
                                "status"
                            )
                            == "success"
                            for kind in QueryType
                        ):
                            raise DataContractError(
                                "refresh omitted previously accepted market extract"
                            )
                        for kind in QueryType:
                            ledger[f"{reporter}/{product}/{month}/{kind.value}"] = {
                                "status": "unavailable",
                                "checked_at": datetime.now(UTC).isoformat(),
                            }
                        persist()
                        continue
                    for kind in QueryType:
                        identity = f"{reporter}/{product}/{month}/{kind.value}"
                        if ready(identity):
                            continue
                        selected = [
                            row
                            for row in rows
                            if (row.partner_code == 0) == (kind == QueryType.WORLD_TOTAL)
                        ]
                        if not selected:
                            if ledger.get(identity, {}).get("status") == "success":
                                raise DataContractError(
                                    "refresh omitted previously accepted extract"
                                )
                            ledger[identity] = {
                                "status": "unavailable",
                                "checked_at": datetime.now(UTC).isoformat(),
                            }
                            persist()
                            continue
                        subset = response.model_copy(
                            update={"data": selected, "count": len(selected)}
                        )
                        next_revision = revision
                        previous = ledger.get(identity, {})
                        if refreshing(identity) and previous.get("status") == "success":
                            previous_data = resolve_artifact(root, previous["data_path"])
                            previous_manifest = json.loads(
                                previous_data.with_name("manifest.json").read_bytes()
                            )
                            next_revision = max(revision, previous_manifest["revision"] + 1)
                        single = ComtradeQuery(
                            period=month,
                            reporter_code=reporter,
                            cmd_code=product,
                            query_type=kind,
                            revision=next_revision,
                        )
                        single = accept_response(single, subset)
                        dataset = IngestionService(CachedResponse(subset)).fetch_dataset(single)
                        stored = LocalStorage(root).write(dataset)
                        ledger[identity] = {
                            "status": "success",
                            "rows": stored.row_count,
                            "data_path": relative_artifact_path(stored.data_path).as_posix(),
                            "hs_version": single.expected_hs_version,
                            "checked_at": datetime.now(UTC).isoformat(),
                        }
                        persist()
                    print(
                        json.dumps(
                            {
                                "reporter": reporter,
                                "product": product,
                                "month": month,
                                "rows": len(rows),
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                return True

            plans: list[tuple[str, str, list[int], str]] = []
            for month in months:
                for product in PRODUCTS:
                    group = [
                        reporter
                        for reporter in reporters
                        if not all(
                            ready(f"{reporter}/{product}/{month}/{kind.value}")
                            for kind in QueryType
                        )
                    ]
                    if group:
                        checked = [
                            ledger.get(f"{reporter}/{product}/{month}/{kind.value}", {}).get(
                                "checked_at", ""
                            )
                            for reporter in group
                            for kind in QueryType
                            if ledger.get(f"{reporter}/{product}/{month}/{kind.value}", {}).get(
                                "status"
                            )
                            != "success"
                        ]
                        plans.append((month, product, group, min(checked, default="")))
            if recent_from is not None:
                plans.sort(
                    key=lambda item: (
                        0 if item[0] >= recent_from else 1,
                        -int(item[0]) if item[0] >= recent_from else 0,
                        item[3],
                        item[0],
                        item[1],
                    )
                )
            for month, product, group, _ in plans:
                if not extract(month, product, group):
                    return {"requests": requests, "entries": len(ledger), "complete": False}
        return {"requests": requests, "entries": len(ledger), "complete": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="201601")
    parser.add_argument("--end", required=True)
    parser.add_argument("--reporters", nargs="+", type=int, default=list(MARKETS))
    parser.add_argument("--max-requests", type=int, default=100)
    parser.add_argument("--revision", type=int, default=1)
    parser.add_argument("--interval", type=float, default=1.1)
    parser.add_argument("--output-dir", type=Path, default=Path("data/multi-market"))
    args = parser.parse_args()
    print(
        json.dumps(
            run_batch(
                args.output_dir,
                start=args.start,
                end=args.end,
                reporters=args.reporters,
                max_requests=args.max_requests,
                interval=args.interval,
                revision=args.revision,
            )
        )
    )


if __name__ == "__main__":
    main()
