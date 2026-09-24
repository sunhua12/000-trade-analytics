"""Read-only fixed-scope comparison for the Day 12 dashboard."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from importlib import import_module
from pathlib import Path

from trade_analytics.dashboard.queries import PublishedQueries, Settings


def main() -> None:
    settings = Settings.from_env()
    reader = PublishedQueries(settings)
    start, end = date(2023, 1, 1), date(2024, 12, 1)
    partner = "458"  # Malaysia, a verified country in the published mart.
    months = reader.months()
    rankings = reader.rankings(start, end, [partner], 5)
    trend = reader.trend(start, end, [partner])
    world = reader.world_total(start, end)
    quality = reader.quality(start, end)
    empty = reader.rankings(start, end, ["999"], 5)

    # Independent fixed SQL: no dashboard aggregation or shared query helper.
    sql = f"""
SELECT COUNT(DISTINCT period_start_date) AS month_count,
       SUM(primary_value) AS import_value
FROM {settings.table("mart_us_semiconductor_supply_chain")}
WHERE period_start_date BETWEEN DATE '2023-01-01' AND DATE '2024-12-01'
  AND cmd_code='8542' AND hs_version='H6'
  AND partner_code='458' AND partner_type='country'
"""
    bigquery = import_module("google.cloud.bigquery")
    job = reader.client.query(
        sql,
        job_config=bigquery.QueryJobConfig(maximum_bytes_billed=settings.maximum_bytes_billed),
        location=settings.location,
    )
    reference = dict(next(iter(job.result(timeout=90))))
    ranking_value = rankings[0]["import_value"] if len(rankings) == 1 else None
    trend_total = sum((row["import_value"] for row in trend), Decimal(0))
    if not (
        len(months) == 24
        and len(quality) == 24
        and world["published_months"] == 24
        and len(trend) == reference["month_count"] == 24
        and ranking_value == trend_total == reference["import_value"]
        and not empty
    ):
        raise AssertionError("Dashboard and independent BigQuery results differ")

    evidence = {
        "verified_at_utc": datetime.now(UTC).isoformat(),
        "scope": "202301-202412 / 8542 / H6 / partner 458",
        "published_months": world["published_months"],
        "quality_rows": len(quality),
        "partner_months": len(trend),
        "partner_value": str(ranking_value),
        "independent_value": str(reference["import_value"]),
        "world_value": str(world["world_value"]),
        "empty_partner_rows": len(empty),
        "reference_job_id": job.job_id,
        "reference_bytes_processed": job.total_bytes_processed,
        "reference_bytes_billed": job.total_bytes_billed,
        "dashboard_jobs": reader.jobs,
    }
    path = Path("docs/evidence/day12-verification.json")
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
