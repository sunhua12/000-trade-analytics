"""List unclassified partner codes in one loaded month without changing BigQuery."""

import argparse
import json
import sys
from pathlib import Path

from google.cloud import bigquery

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trade_analytics.warehouse.backfill import PROJECT, source_key  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("period")
    args = parser.parse_args()
    source_key(args.period, "partner_detail")
    client = bigquery.Client(project=PROJECT, location="asia-northeast1")
    sql = f"""
SELECT r.partner_code, COUNT(*) row_count, CAST(SUM(r.primary_value) AS STRING) amount,
 ANY_VALUE(d.source_name) partner_name, ANY_VALUE(d.classification_status) classification_status,
 ANY_VALUE(d.reconciliation_role) reconciliation_role
FROM `{PROJECT}.trade_raw.un_comtrade_partner_detail` r
LEFT JOIN `{PROJECT}.trade_analytics_day10_dev.dim_countries` d
 ON r.partner_code=d.partner_code
WHERE r.period_start_date=PARSE_DATE('%Y%m',@period)
 AND r.cmd_code='8542' AND r.hs_version='H6'
 AND (d.partner_code IS NULL OR d.classification_status!='verified'
      OR d.reconciliation_role='unresolved')
GROUP BY r.partner_code ORDER BY r.partner_code
"""
    job = client.query(
        sql,
        location="asia-northeast1",
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("period", "STRING", args.period)],
            maximum_bytes_billed=10**9,
        ),
    )
    print(
        json.dumps({"job_id": job.job_id, "rows": [dict(row) for row in job.result(timeout=180)]})
    )


if __name__ == "__main__":
    main()
