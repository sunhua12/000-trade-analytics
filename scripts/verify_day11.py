"""Write the 24-month source, raw, quality and publication coverage matrix."""

import csv
import json
import sys
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ingest_day11 import existing_keys

from trade_analytics.warehouse.backfill import KINDS, source_key

ROOT = Path(__file__).resolve().parents[1]


def status(row: dict[str, object]) -> str:
    if not row["detail_s3"] or not row["world_s3"]:
        return "source_missing"
    if not row["detail_rows"] or row["world_rows"] != 1:
        return "raw_incomplete"
    if row["detail_checksums"] != 1 or row["world_checksums"] != 1:
        return "raw_mixed_source"
    if not row["detail_attestations"] or not row["world_attestations"]:
        return "source_not_attested"
    if row["quality_status"] is None:
        return "quality_not_run"
    if row["quality_status"] == "FAIL":
        return "quality_fail_previous_published" if row["published_rows"] else "quality_fail"
    if not row["published_rows"]:
        return "not_published"
    return "published_" + str(row["quality_status"]).lower()


def main() -> None:
    bigquery = import_module("google.cloud.bigquery")

    client = bigquery.Client(project="trade-analytics-508604", location="asia-northeast1")
    sql = (ROOT / "docs/evidence/day11-coverage.sql").read_text()
    job = client.query(sql, job_config=bigquery.QueryJobConfig(maximum_bytes_billed=10**9))
    source = existing_keys()
    rows = []
    for record in job.result(timeout=180):
        row = dict(record)
        period = row["period"]
        for kind in KINDS:
            prefix = source_key(period, kind)
            label = "detail_s3" if kind == "partner_detail" else "world_s3"
            row[label] = prefix + "/data.ndjson" in source and prefix + "/manifest.json" in source
        row["reason_codes"] = ",".join(row["reason_codes"] or [])
        row["coverage_status"] = status(row)
        rows.append(row)
    expected = [f"{year}{month:02d}" for year in (2023, 2024) for month in range(1, 13)]
    if [row["period"] for row in rows] != expected:
        raise ValueError("coverage spine must contain exactly 24 ordered months")
    publication_sql = (ROOT / "docs/evidence/day11-publication-check.sql").read_text()
    publication_job = client.query(
        publication_sql, job_config=bigquery.QueryJobConfig(maximum_bytes_billed=10**9)
    )
    publication = dict(next(iter(publication_job.result(timeout=180))))
    if any(
        publication[key] != 0
        for key in ("difference_rows", "duplicate_grain_rows", "invalid_quality_rows")
    ):
        raise ValueError(f"published/frozen integrity failed: {publication}")
    metrics_sql = (ROOT / "docs/evidence/day11-metrics.sql").read_text()
    metrics_job = client.query(
        metrics_sql, job_config=bigquery.QueryJobConfig(maximum_bytes_billed=10**9)
    )
    metrics = [dict(row) for row in metrics_job.result(timeout=180)]
    by_period = {row["period"]: row for row in metrics}
    if (
        len(metrics) != 24
        or by_period["202301"]["mom_rows"] != 0
        or by_period["202301"]["yoy_rows"] != 0
        or by_period["202302"]["mom_rows"] == 0
        or by_period["202401"]["mom_rows"] == 0
        or by_period["202401"]["yoy_rows"] == 0
    ):
        raise ValueError("cross-month metric availability does not match the date spine")
    evidence = ROOT / "docs/evidence/day11"
    evidence.mkdir(parents=True, exist_ok=True)
    with (evidence / "coverage.csv").open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    (evidence / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str) + "\n")
    counts = {
        s: sum(r["coverage_status"] == s for r in rows)
        for s in sorted({r["coverage_status"] for r in rows})
    }
    summary = {
        "verified_at": datetime.now(UTC).isoformat(),
        "job_id": job.job_id,
        "publication_job_id": publication_job.job_id,
        "metrics_job_id": metrics_job.job_id,
        "publication_integrity": publication,
        "metric_summary": {
            "mom_rows": sum(row["mom_rows"] for row in metrics),
            "yoy_rows": sum(row["yoy_rows"] for row in metrics),
            "unit_value_rows": sum(row["unit_value_rows"] for row in metrics),
            "visible_hhi_rows": sum(row["visible_hhi_rows"] for row in metrics),
            "max_difference_rate": str(max(row["difference_rate"] for row in metrics)),
            "min_country_coverage": str(min(row["country_coverage"] for row in metrics)),
            "max_country_coverage": str(max(row["country_coverage"] for row in metrics)),
        },
        "months": len(rows),
        "status_counts": counts,
    }
    (evidence / "coverage-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
