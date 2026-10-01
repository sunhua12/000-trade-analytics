"""Validate an explicit, bounded Airflow backfill before any pipeline writes."""

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import boto3
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.monthly_plan import (  # noqa: E402
    AWS_REGION,
    bigquery_client,
    current_published,
    source_available,
)
from scripts.pipeline_exit import exit_for_error  # noqa: E402
from trade_analytics.warehouse.backfill import KINDS, source_key  # noqa: E402


def periods_between(start: str, end: str) -> list[str]:
    source_key(start, KINDS[0])
    source_key(end, KINDS[0])
    if start > end:
        raise ValueError("start_period must not exceed end_period")
    today = datetime.now(ZoneInfo("Asia/Taipei"))
    if end >= today.strftime("%Y%m"):
        raise ValueError("end_period must be a completed month")
    result = []
    period = start
    while period <= end and len(result) <= 3:
        result.append(period)
        year, month = int(period[:4]), int(period[4:])
        period = f"{year + (month == 12):04d}{month % 12 + 1:02d}"
    if len(result) > 3 or result[-1] != end:
        raise ValueError("backfill range must contain at most 3 consecutive months")
    return result


def validate_conf(conf: dict[str, Any]) -> tuple[list[str], dict[str, int], dict[str, str]]:
    if not isinstance(conf, dict) or set(conf) - {
        "start_period",
        "end_period",
        "revisions",
        "replay_run_ids",
        "recovery_probe",
    }:
        raise ValueError("unsupported backfill configuration")
    start, end = conf.get("start_period"), conf.get("end_period")
    if not isinstance(start, str) or not isinstance(end, str):
        raise ValueError("start_period and end_period are required YYYYMM strings")
    periods = periods_between(start, end)
    revisions = conf.get("revisions", {kind: 1 for kind in KINDS})
    if (
        not isinstance(revisions, dict)
        or set(revisions) != set(KINDS)
        or any(type(value) is not int or value < 1 for value in revisions.values())
    ):
        raise ValueError("revisions must contain positive integers for both source kinds")
    replay = conf.get("replay_run_ids", {})
    if (
        not isinstance(replay, dict)
        or set(replay) - set(periods)
        or any(not isinstance(value, str) or not value.strip() for value in replay.values())
    ):
        raise ValueError("replay_run_ids must map selected periods to nonempty run IDs")
    probe = conf.get("recovery_probe")
    if probe is not None and (
        not isinstance(probe, dict)
        or set(probe) != {"period", "kind"}
        or probe["period"] not in periods
        or probe["kind"] not in KINDS
    ):
        raise ValueError("recovery_probe must select one period and source kind in range")
    return periods, revisions, replay


def plan(conf: dict[str, Any], dag_run_id: str) -> dict[str, Any]:
    periods, revisions, replay = validate_conf(conf)
    client = bigquery_client()
    s3 = boto3.client("s3", region_name=AWS_REGION)
    items: list[dict[str, Any]] = []
    with httpx.Client(timeout=httpx.Timeout(30.0)) as http_client:
        for period in periods:
            published_run_id = current_published(client, period)
            if published_run_id and (conf.get("recovery_probe") or {}).get("period") == period:
                raise ValueError("recovery probe requires an unpublished month")
            if published_run_id and period not in replay:
                items.append({"period": period, "status": "already_published"})
                continue
            if period in replay and replay[period] != published_run_id:
                raise ValueError(f"replay run ID does not match published month: {period}")
            sources = {
                kind: source_available(s3, http_client, period, kind, revisions[kind])
                for kind in KINDS
            }
            if not all(sources.values()):
                raise ValueError(f"source not available for {period}: {sources}")
            run_id = replay.get(period) or (
                f"backfill-{period}-{hashlib.sha256(dag_run_id.encode()).hexdigest()[:16]}"
            )
            items.append(
                {
                    "period": period,
                    "status": "ready",
                    "run_id": run_id,
                    "revisions": revisions,
                    "sources": sources,
                }
            )
    return {"items": items, "dag_run_id": dag_run_id}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conf", required=True, type=json.loads)
    parser.add_argument("--dag-run-id", required=True)
    args = parser.parse_args()
    print(json.dumps(plan(args.conf, args.dag_run_id), sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit(exit_for_error(error)) from error
