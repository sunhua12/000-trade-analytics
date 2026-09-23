"""Read-only verification of the actual published partition and its frozen batch."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from trade_analytics.warehouse.publish import PUBLISHED, Publisher


def main():
    from google.cloud import bigquery

    runner = Publisher(
        bigquery.Client(project="trade-analytics-508604", location="asia-northeast1"),
        "trade-analytics-508604",
        "trade_analytics_day10_dev",
        "trade_raw",
        "trade_analytics_published",
    )

    def t(name):
        return runner.table(runner.release, name)

    try:
        comparison = runner.query(f"""
WITH published AS (
 SELECT * FROM {t(PUBLISHED)} WHERE period_start_date=DATE '2023-01-01'
), candidate AS (
 SELECT * FROM {t("candidate_batches")} WHERE candidate_batch_id='real-202301-quality-v1'
), differences AS (
 (SELECT * EXCEPT(quality_status,published_at,published_run_id) FROM published
 EXCEPT DISTINCT SELECT * FROM candidate)
 UNION ALL
 (SELECT * FROM candidate EXCEPT DISTINCT
 SELECT * EXCEPT(quality_status,published_at,published_run_id) FROM published)
)
SELECT (SELECT COUNT(*) FROM differences) difference_rows,
 COUNT(*) row_count,COUNT(DISTINCT partner_code) partner_count,SUM(primary_value) amount,
 COUNTIF(hhi IS NOT NULL) nonnull_hhi,COUNTIF(mom IS NOT NULL OR yoy IS NOT NULL) nonnull_growth,
 COUNTIF(quality_status!='PASS' OR published_run_id!='real-202301-quality-v1') bad_publication,
 MIN(published_at) published_at,MAX(country_coverage) country_coverage,
 SUM(IF(partner_code='490',primary_value,0)) special_value FROM published
""")[0]
        assert comparison["difference_rows"] == 0
        assert comparison["row_count"] == comparison["partner_count"] == 67
        assert comparison["amount"] == 2799575181 and comparison["special_value"] == 630972428
        assert (
            comparison["nonnull_hhi"]
            == comparison["nonnull_growth"]
            == comparison["bad_publication"]
            == 0
        )
        summary = runner.query(
            f"SELECT * FROM {t('publication_quality_summary')} WHERE period='202301'"
        )
        audit = runner.query(
            f"SELECT * FROM {t('audit_world_reconciliation')} WHERE run_id='real-202301-quality-v1'"
        )
        assert len(audit) == 1 and audit[0]["status"] == "PASS" and audit[0]["difference"] == 0
        assert audit[0]["country_coverage"] is not None
        assert summary[0]["published_run_id"] == "real-202301-quality-v1"
        snapshot = runner.query(f"""
SELECT TO_JSON_STRING(p) row_json FROM {t(PUBLISHED)} p
WHERE period_start_date=DATE '2023-01-01' ORDER BY row_json
""")
        analysis_path = Path(__file__).resolve().parents[1] / "docs/evidence/day10-verification.sql"
        analysis = [
            {"sql": sql.strip(), "rows": runner.query(sql)}
            for sql in analysis_path.read_text().split(";")
            if sql.strip()
        ]
        report = {
            "result": "passed",
            "analysis_queries": analysis,
            "comparison": comparison,
            "summary": summary,
            "audit": audit,
            "published_snapshot": snapshot,
        }
        Path("docs/evidence/day10/published-verification.json").write_text(
            json.dumps(report, default=str, indent=2) + "\n"
        )
        print(
            "PASS: 67 published rows; all frozen columns preserved; "
            "reconciliation and NULL metrics verified"
        )
    finally:
        runner.save_evidence(Path("docs/evidence/day10/published-verification-jobs.json"))


if __name__ == "__main__":
    main()
