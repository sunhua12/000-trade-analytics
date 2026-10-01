"""Read-only BigQuery evidence for three-month backfill and safe reruns."""

import argparse
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from google.cloud import bigquery

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.backfill_plan import periods_between  # noqa: E402
from trade_analytics.warehouse.backfill import KINDS, PROJECT  # noqa: E402

LOCATION = "asia-northeast1"


def query(client: bigquery.Client, sql: str, period: str) -> dict[str, Any]:
    job = client.query(
        sql,
        location=LOCATION,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("period", "STRING", period)],
            maximum_bytes_billed=10**9,
        ),
    )
    rows = [dict(row) for row in job.result(timeout=180)]
    if len(rows) != 1:
        raise ValueError(f"unexpected verification result for {period}")
    return {"job_id": job.job_id, **rows[0]}


def verify(client: bigquery.Client, periods: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {"checked_at": datetime.now().astimezone().isoformat(), "months": []}
    for period in periods:
        item: dict[str, Any] = {"period": period, "raw": {}}
        for kind in KINDS:
            table = f"`{PROJECT}.trade_raw.un_comtrade_{kind}`"
            item["raw"][kind] = query(
                client,
                f"""
SELECT COUNT(*) row_count, COUNT(DISTINCT partner_code) distinct_partner_count,
 CAST(SUM(primary_value) AS STRING) amount,
 COUNT(DISTINCT checksum) checksum_count, COUNT(DISTINCT revision) revision_count
FROM {table}
WHERE period_start_date=PARSE_DATE('%Y%m',@period)
 AND cmd_code='8542' AND hs_version='H6'
""",
                period,
            )
        item["published"] = query(
            client,
            f"""
SELECT COUNT(*) row_count, COUNT(DISTINCT partner_code) distinct_partner_count,
 COUNT(DISTINCT published_run_id) run_id_count,
 ARRAY_AGG(DISTINCT published_run_id IGNORE NULLS) run_ids,
 ARRAY_AGG(DISTINCT CAST(published_at AS STRING) IGNORE NULLS) published_at
FROM `{PROJECT}.trade_analytics_published.mart_us_semiconductor_supply_chain`
WHERE period_start_date=PARSE_DATE('%Y%m',@period)
 AND cmd_code='8542' AND hs_version='H6'
""",
            period,
        )
        item["latest_quality"] = query(
            client,
            f"""
SELECT TO_JSON_STRING(ARRAY_AGG(STRUCT(run_id, status, reason_codes, tested_at)
 ORDER BY tested_at DESC LIMIT 1)[SAFE_OFFSET(0)]) latest_json
FROM `{PROJECT}.trade_analytics_published.quality_audit_history`
WHERE period=@period AND cmd_code='8542' AND hs_version='H6'
""",
            period,
        )
        result["months"].append(item)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("start_period")
    parser.add_argument("end_period")
    args = parser.parse_args()
    periods = periods_between(args.start_period, args.end_period)
    client = bigquery.Client(project=PROJECT, location=LOCATION)
    print(json.dumps(verify(client, periods), default=serialize, sort_keys=True))


def serialize(value: Any) -> str:
    if isinstance(value, (datetime, Decimal)):
        return str(value)
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


if __name__ == "__main__":
    main()
