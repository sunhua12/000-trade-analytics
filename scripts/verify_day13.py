"""Verify Day 13 views against independent, read-only BigQuery queries."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from google.cloud import bigquery

from trade_analytics.dashboard.queries import PublishedQueries, Settings


def simplify(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: simplify(item) for key, item in value.items()}
    if isinstance(value, list):
        return [simplify(item) for item in value]
    return value


def main() -> None:
    settings = Settings.from_env()
    reader = PublishedQueries(settings)
    start, end = date(2023, 1, 1), date(2024, 12, 1)
    monthly = reader.monthly_metrics(start, end)
    partner = reader.partner_metrics(date(2024, 1, 1), end, "458")
    scatter = reader.scatter(end, [])
    quality = reader.quality(start, end)
    if len(monthly) != 24 or len(quality) != 24:
        raise AssertionError("Expected 24 published months and quality rows")

    table = settings.table("mart_us_semiconductor_supply_chain")
    sql = f"""
WITH month_values AS (
  SELECT period_start_date,
         MAX(world_value) AS world_value,
         MAX(country_coverage) AS coverage,
         MAX(hhi) AS hhi,
         ANY_VALUE(hhi_status) AS hhi_status
  FROM {table}
  WHERE period_start_date >= DATE '2023-01-01'
    AND period_start_date < DATE '2025-01-01'
    AND cmd_code='8542' AND hs_version='H6'
  GROUP BY period_start_date
)
SELECT COUNT(*) AS months,
       SUM(IF(EXTRACT(YEAR FROM period_start_date)=2023, world_value, 0)) AS world_2023,
       SUM(IF(EXTRACT(YEAR FROM period_start_date)=2024, world_value, 0)) AS world_2024,
       MIN(coverage) AS min_coverage, MAX(coverage) AS max_coverage,
       COUNTIF(hhi IS NOT NULL) AS visible_hhi_months,
       COUNTIF(hhi_status='insufficient_coverage') AS insufficient_coverage_months
FROM month_values
"""
    job = reader.client.query(
        sql,
        job_config=bigquery.QueryJobConfig(maximum_bytes_billed=settings.maximum_bytes_billed),
        location=settings.location,
    )
    independent = dict(next(iter(job.result(timeout=90))))
    world_2023 = sum(
        (row["world_value"] for row in monthly if row["month"].year == 2023), Decimal(0)
    )
    world_2024 = sum(
        (row["world_value"] for row in monthly if row["month"].year == 2024), Decimal(0)
    )
    coverage = [row["country_coverage"] for row in monthly]
    if (
        independent["months"] != 24
        or independent["world_2023"] != world_2023
        or independent["world_2024"] != world_2024
        or independent["min_coverage"] != min(coverage)
        or independent["max_coverage"] != max(coverage)
        or independent["visible_hhi_months"] != sum(row["hhi"] is not None for row in monthly)
    ):
        raise AssertionError("Monthly dashboard values differ from independent SQL")

    partner_sql = f"""
SELECT period_start_date, primary_value, previous_year_value, yoy
FROM {table}
WHERE period_start_date >= DATE '2024-01-01'
  AND period_start_date < DATE '2025-01-01'
  AND cmd_code='8542' AND hs_version='H6'
  AND partner_type='country' AND partner_code='458'
ORDER BY period_start_date
"""
    partner_job = reader.client.query(
        partner_sql,
        job_config=bigquery.QueryJobConfig(maximum_bytes_billed=settings.maximum_bytes_billed),
        location=settings.location,
    )
    partner_reference = [dict(row) for row in partner_job.result(timeout=90)]
    if partner != [
        {
            "month": row["period_start_date"],
            "import_value": row["primary_value"],
            "previous_year_value": row["previous_year_value"],
            "yoy": row["yoy"],
        }
        for row in partner_reference
    ]:
        raise AssertionError("Partner YoY differs from independent SQL")

    ranking_sql = f"""
SELECT partner_code, ANY_VALUE(source_name) AS source_name,
       SUM(IF(EXTRACT(YEAR FROM period_start_date)=2023, primary_value, 0)) AS value_2023,
       SUM(IF(EXTRACT(YEAR FROM period_start_date)=2024, primary_value, 0)) AS value_2024
FROM {table}
WHERE period_start_date >= DATE '2023-01-01'
  AND period_start_date < DATE '2025-01-01'
  AND cmd_code='8542' AND hs_version='H6' AND partner_type='country'
GROUP BY partner_code ORDER BY value_2024 DESC, partner_code LIMIT 5
"""
    ranking_job = reader.client.query(
        ranking_sql,
        job_config=bigquery.QueryJobConfig(maximum_bytes_billed=settings.maximum_bytes_billed),
        location=settings.location,
    )
    top_2024 = [dict(row) for row in ranking_job.result(timeout=90)]

    mapping_sql = f"""
SELECT COUNT(*) AS country_rows, COUNTIF(map_iso3 IS NULL) AS unmapped_rows,
       SUM(primary_value) AS country_value,
       SUM(IF(map_iso3 IS NULL, primary_value, 0)) AS unmapped_value
FROM {table}
WHERE period_start_date = DATE '2024-12-01'
  AND cmd_code='8542' AND hs_version='H6' AND partner_type='country'
"""
    mapping_job = reader.client.query(
        mapping_sql,
        job_config=bigquery.QueryJobConfig(maximum_bytes_billed=settings.maximum_bytes_billed),
        location=settings.location,
    )
    mapping = dict(next(iter(mapping_job.result(timeout=90))))

    evidence = {
        "verified_at_utc": datetime.now(UTC),
        "scope": "202301-202412 / 8542 / H6; partner YoY 458",
        "monthly_summary": independent,
        "world_yoy_2024": world_2024 / world_2023 - 1,
        "partner_458_2024_yoy_rows": len(partner),
        "partner_458_december_yoy": partner[-1]["yoy"] if partner else None,
        "top_2024_partners": top_2024,
        "december_map_mapping": mapping,
        "december_scatter_points": len(scatter),
        "quality_rows": len(quality),
        "reference_job_id": job.job_id,
        "reference_bytes_processed": job.total_bytes_processed,
        "partner_reference_job_id": partner_job.job_id,
        "partner_reference_bytes_processed": partner_job.total_bytes_processed,
        "ranking_reference_job_id": ranking_job.job_id,
        "mapping_reference_job_id": mapping_job.job_id,
        "dashboard_jobs": reader.jobs,
    }
    path = Path("docs/evidence/day13-verification.json")
    path.write_text(json.dumps(simplify(evidence), ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(simplify(evidence), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
