"""Select at most three completed months for the Airflow monthly pipeline."""

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import boto3
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.pipeline_exit import exit_for_error  # noqa: E402
from trade_analytics.ingestion.client import ComtradeClient  # noqa: E402
from trade_analytics.ingestion.queries import ComtradeQuery, QueryType  # noqa: E402
from trade_analytics.warehouse.backfill import (  # noqa: E402
    BUCKET,
    KINDS,
    PROJECT,
    source_key,
)

AWS_REGION = "ap-northeast-1"
BIGQUERY_LOCATION = "asia-northeast1"
API_REQUEST_SPACING_SECONDS = 1.0


def previous_month(period: str) -> str:
    year, month = int(period[:4]), int(period[4:])
    return f"{year - (month == 1):04d}{(month - 2) % 12 + 1:02d}"


def candidate_periods(interval_end: datetime, count: int = 3) -> list[str]:
    if interval_end.tzinfo is None:
        raise ValueError("data interval end must have a timezone")
    if count < 1 or count > 3:
        raise ValueError("candidate count must be from 1 to 3")
    boundary = interval_end.astimezone(ZoneInfo("Asia/Taipei"))
    if boundary.day != 1:
        raise ValueError("scheduled data interval must end on the first day of a month")
    latest = previous_month(boundary.strftime("%Y%m"))
    periods = [latest]
    for _ in range(count - 1):
        periods.append(previous_month(periods[-1]))
    return [period for period in reversed(periods) if period >= "202301"]


def current_published(client: Any, period: str) -> str | None:
    from google.cloud import bigquery

    table = f"`{PROJECT}.trade_analytics_published.mart_us_semiconductor_supply_chain`"
    job = client.query(
        f"SELECT DISTINCT published_run_id FROM {table} "
        "WHERE period_start_date=PARSE_DATE('%Y%m',@period) "
        "AND cmd_code='8542' AND hs_version='H6'",
        location=BIGQUERY_LOCATION,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("period", "STRING", period)],
            maximum_bytes_billed=10**9,
        ),
    )
    rows = list(job.result(timeout=180))
    if len(rows) > 1:
        raise ValueError(f"multiple published run IDs for {period}")
    return rows[0].published_run_id if rows else None


def older_unpublished(client: Any, oldest_candidate: str) -> list[str]:
    """Expose months before the bounded lookback without probing their remote sources."""
    if oldest_candidate <= "202301":
        return []
    from google.cloud import bigquery

    table = f"`{PROJECT}.trade_analytics_published.mart_us_semiconductor_supply_chain`"
    job = client.query(
        f"SELECT DISTINCT FORMAT_DATE('%Y%m', period_start_date) AS period FROM {table} "
        "WHERE period_start_date < PARSE_DATE('%Y%m',@oldest) "
        "AND cmd_code='8542' AND hs_version='H6'",
        location=BIGQUERY_LOCATION,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("oldest", "STRING", oldest_candidate)],
            maximum_bytes_billed=10**9,
        ),
    )
    published = {row.period for row in job.result(timeout=180)}
    missing: list[str] = []
    period = "202301"
    while period < oldest_candidate:
        if period not in published:
            missing.append(period)
        year, month = int(period[:4]), int(period[4:])
        period = f"{year + (month == 12):04d}{month % 12 + 1:02d}"
    return missing


def bigquery_client() -> Any:
    from google.cloud import bigquery

    return bigquery.Client(project=PROJECT, location=BIGQUERY_LOCATION)


def source_available(
    s3: Any, http_client: httpx.Client, period: str, kind: str, revision: int
) -> bool:
    from botocore.exceptions import ClientError

    prefix = source_key(period, kind, revision)
    found: list[bool] = []
    for filename in ("data.ndjson", "manifest.json"):
        try:
            s3.head_object(Bucket=BUCKET, Key=f"{prefix}/{filename}")
            found.append(True)
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code not in ("404", "NoSuchKey", "NotFound"):
                raise
            found.append(False)
    if all(found):
        return True
    if any(found):
        raise ValueError(f"incomplete S3 source pair: {period} {kind} revision {revision}")
    query = ComtradeQuery(
        period=period, cmd_code="8542", query_type=QueryType(kind), revision=revision
    )
    time.sleep(API_REQUEST_SPACING_SECONDS)
    response = ComtradeClient(http_client=http_client).fetch(query)
    if response.count == 0 and not response.data:
        return False
    if response.count > 0 and response.data:
        return True
    raise ValueError(f"inconsistent source availability response: {period} {kind}")


def plan(
    *,
    interval_end: datetime,
    dag_run_id: str,
    manual_period: str | None = None,
    replay_run_id: str | None = None,
    revisions: dict[str, int] | None = None,
) -> dict[str, Any]:
    candidates = [manual_period] if manual_period is not None else candidate_periods(interval_end)
    if manual_period is not None:
        source_key(manual_period, KINDS[0])
        if manual_period > previous_month(
            datetime.now(UTC).astimezone(ZoneInfo("Asia/Taipei")).strftime("%Y%m")
        ):
            raise ValueError("manual period must be a completed month")
    if replay_run_id and manual_period is None:
        raise ValueError("replay_run_id requires manual period")
    chosen_revisions = {kind: 1 for kind in KINDS}
    if revisions:
        if set(revisions) != set(KINDS) or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 1
            for value in revisions.values()
        ):
            raise ValueError("revisions must contain positive integers for both source kinds")
        chosen_revisions = revisions
    client = bigquery_client()
    s3 = boto3.client("s3", region_name=AWS_REGION)
    selected: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    backlog = older_unpublished(client, candidates[0]) if manual_period is None else []
    with httpx.Client(timeout=httpx.Timeout(30.0)) as http_client:
        for period in candidates:
            existing = current_published(client, period)
            checked_at = datetime.now(UTC).isoformat()
            if existing and replay_run_id != existing:
                checks.append(
                    {"period": period, "status": "already_published", "checked_at": checked_at}
                )
                continue
            sources = {
                kind: source_available(s3, http_client, period, kind, chosen_revisions[kind])
                for kind in KINDS
            }
            ready = all(sources.values())
            if not ready:
                checks.append(
                    {
                        "period": period,
                        "status": "not_available",
                        "checked_at": checked_at,
                        "sources": sources,
                    }
                )
                continue
            run_id = replay_run_id or (
                f"monthly-{period}-{hashlib.sha256(dag_run_id.encode()).hexdigest()[:16]}"
            )
            selected.append({"period": period, "run_id": run_id, "revisions": chosen_revisions})
            checks.append(
                {"period": period, "status": "ready", "checked_at": checked_at, "sources": sources}
            )
    return {"selected": selected, "checks": checks, "older_unpublished": backlog}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval-end", required=True)
    parser.add_argument("--dag-run-id", required=True)
    parser.add_argument("--period")
    parser.add_argument("--replay-run-id")
    parser.add_argument("--revisions", type=json.loads)
    args = parser.parse_args()
    result = plan(
        interval_end=datetime.fromisoformat(args.interval_end),
        dag_run_id=args.dag_run_id,
        manual_period=args.period,
        replay_run_id=args.replay_run_id,
        revisions=args.revisions,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit(exit_for_error(error)) from error
