"""Compare dashboard reads with independent SQL and exercise real-data Streamlit UI."""

import json
import os
from datetime import UTC, date, datetime
from pathlib import Path

os.environ.setdefault("TRADE_DASHBOARD_AFTER_LAST_MONTH", "2025-05-01")

from google.cloud import bigquery  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

from trade_analytics.dashboard.queries import PublishedQueries, Settings  # noqa: E402


def main() -> None:
    output = Path("docs/evidence/day18")
    output.mkdir(parents=True, exist_ok=True)
    settings = Settings.from_env()
    reader = PublishedQueries(settings)
    reference_sql = f"""SELECT period_start_date AS month,
      MAX(world_value) AS world_value,
      MAX(country_coverage) AS country_coverage,
      MAX(hhi) AS hhi, ANY_VALUE(hhi_status) AS hhi_status,
      MAX(IF(partner_code='458' AND partner_type='country',primary_value,NULL)) AS partner_value,
      MAX(IF(partner_code='458' AND partner_type='country',yoy,NULL)) AS partner_yoy
    FROM {settings.table("mart_us_semiconductor_supply_chain")}
    WHERE period_start_date >= DATE '2024-01-01'
      AND period_start_date < DATE '2025-05-01'
      AND cmd_code='8542' AND hs_version='H6'
    GROUP BY month ORDER BY month"""
    output.joinpath("reference.sql").write_text(reference_sql + "\n")
    job = reader.client.query(
        reference_sql,
        location=settings.location,
        job_config=bigquery.QueryJobConfig(maximum_bytes_billed=settings.maximum_bytes_billed),
    )
    reference = [dict(row) for row in job.result(timeout=120)]
    monthly = {r["month"]: r for r in reader.monthly_metrics(date(2024, 1, 1), date(2025, 4, 1))}
    partner = {
        r["month"]: r for r in reader.partner_metrics(date(2024, 1, 1), date(2025, 4, 1), "458")
    }
    for row in reference:
        for key in ["world_value", "country_coverage", "hhi", "hhi_status"]:
            assert monthly[row["month"]][key] == row[key], (row["month"], key)
        if row["partner_value"] is not None:
            assert partner[row["month"]]["import_value"] == row["partner_value"]
            assert partner[row["month"]]["yoy"] == row["partner_yoy"]
    app = AppTest.from_file(Path("dashboard.py").resolve(), default_timeout=180).run()
    assert not app.error and not app.exception
    assert date(2025, 4, 1) in app.selectbox[1].options or "2025-04" in app.selectbox[1].options
    app.selectbox[0].set_value(date(2024, 1, 1)).run()
    app.selectbox[1].set_value(date(2024, 12, 1)).run()
    app.multiselect[0].set_value(["458"]).run()
    assert not app.error and not app.exception
    historical_tables = [len(t.value) for t in app.dataframe]
    assert historical_tables[:3] == [1, 12, 12]
    app.multiselect[0].set_value([]).run()
    app.selectbox[1].set_value(date(2025, 4, 1)).run()
    app.selectbox[0].set_value(date(2025, 4, 1)).run()
    assert not app.error and not app.exception
    april = next(r for r in reference if r["month"] == date(2025, 4, 1))
    assert any(f"USD {april['world_value']:,.0f}" in c.value for c in app.caption)
    evidence = {
        "verified_at_utc": datetime.now(UTC).isoformat(),
        "reference_job_id": job.job_id,
        "bytes_processed": job.total_bytes_processed,
        "bytes_billed": job.total_bytes_billed,
        "reference_rows": reference,
        "dashboard_jobs": reader.jobs,
        "historical_filtered_table_rows": historical_tables,
        "april_metrics": [{"label": m.label, "value": m.value} for m in app.metric],
        "ui_exceptions": 0,
        "scope": "real BigQuery + local AppTest; live browser verified separately",
    }
    output.joinpath("query-ui-verification.json").write_text(
        json.dumps(evidence, default=str, ensure_ascii=False, indent=2) + "\n"
    )
    print("Independent SQL and real-data AppTest passed")


if __name__ == "__main__":
    main()
