"""Execute Day 8 dbt acceptance against dev and isolated disposable fixtures.

Requires ADC, dbt/local/profiles.yml and .venv-dbt. Never mutates trade_raw.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from google.cloud import bigquery

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence/day08"
PROJECT = "trade-analytics-508604"
DEV = "trade_analytics_dev"
FIXTURE = "trade_analytics_day08_fixture"
RAW_FIXTURE = "trade_raw_day08_fixture"
client = bigquery.Client(project=PROJECT, location="asia-northeast1")
summary = {"started_at": datetime.now(UTC).isoformat(), "dbt_runs": [], "queries": []}


def query(sql):
    job = client.query(sql)
    rows = [dict(r) for r in job.result()]
    summary["queries"].append({"job_id": job.job_id, "sql": sql, "row_count": len(rows)})
    return rows


def table(dataset, name):
    return f"`{PROJECT}.{dataset}.{name}`"


def dbt(label, command, target="dev", select=None, expected_failure=None):
    env = dict(
        os.environ,
        DBT_RAW_PROJECT=PROJECT,
        DBT_RAW_DATASET=RAW_FIXTURE if target == "fixture" else "trade_raw",
        DBT_SEND_ANONYMOUS_USAGE_STATS="false",
    )
    args = [
        str(ROOT / ".venv-dbt/bin/dbt"),
        command,
        "--project-dir",
        "dbt",
        "--profiles-dir",
        "dbt/local",
        "--target",
        target,
    ]
    if select:
        args += ["--select", *select]
    print(label, flush=True)
    result = subprocess.run(
        args, cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    (EVIDENCE / f"{label}.log").write_text(result.stdout)
    artifact = ROOT / "dbt/target/run_results.json"
    if command != "docs generate":
        shutil.copyfile(artifact, EVIDENCE / f"{label}-run-results.json")
        data = json.loads(artifact.read_text())
        results = [
            {"id": r["unique_id"], "status": r["status"], "failures": r.get("failures")}
            for r in data["results"]
        ]
        summary["dbt_runs"].append(
            {"label": label, "returncode": result.returncode, "results": results}
        )
        assert results, f"No nodes executed: {label}"
        if expected_failure:
            failures = [r for r in results if r["status"] == "fail"]
            assert result.returncode == 1 and any(expected_failure in r["id"] for r in failures), (
                result.stdout
            )
            assert not any(r["status"] == "error" for r in results), result.stdout
        else:
            assert result.returncode == 0, result.stdout
    print(result.stdout[-450:], flush=True)


def snapshot(dataset):
    return query(
        f"SELECT TO_JSON_STRING(t) AS row "
        f"FROM {table(dataset, 'fct_monthly_semiconductor_imports')} t "
        "ORDER BY period_start_date, partner_code, cmd_code, hs_version"
    )


def run(resume_fixtures=False):
    if resume_fixtures:
        summary.update(json.loads((EVIDENCE / "verification.json").read_text()))
        assert summary.get("dev_rebuild_identical"), "No successful dev rebuild to resume"
    else:
        dbt("dev-seed", "seed")
        dbt("dev-seed-tests", "test", select=["country_reference", "hs_code_reference"])
        dbt("dev-build", "build")
    first = snapshot(DEV)
    world_before = query(
        f"SELECT TO_JSON_STRING(t) AS row "
        f"FROM {table('trade_raw', 'un_comtrade_world_total')} t "
        "WHERE period_start_date >= DATE '2023-01-01' "
        "AND period_start_date < DATE '2025-01-01' ORDER BY row"
    )
    digest = hashlib.sha256(json.dumps(first, sort_keys=True).encode()).hexdigest()
    if resume_fixtures:
        assert digest == summary["dev_fact_sha256"], "Dev changed since saved verification"
    else:
        dbt("dev-rebuild", "build")
        assert first == snapshot(DEV), "Rebuild changed fact including lineage"
        summary["dev_rebuild_identical"] = True
        summary["dev_fact_rows"] = len(first)
        summary["dev_fact_sha256"] = digest
    summary["dev_amounts"] = query(
        "SELECT period, COUNT(*) AS row_count, SUM(primary_value) amount, "
        "COUNTIF(net_weight IS NULL) null_weights "
        f"FROM {table(DEV, 'fct_monthly_semiconductor_imports')} GROUP BY period"
    )
    summary["dev_audit"] = query(
        f"SELECT * FROM {table(DEV, 'audit_partner_mapping_issues')} "
        "ORDER BY partner_code, issue_type"
    )
    for dataset in [RAW_FIXTURE, FIXTURE]:
        query(
            f'CREATE SCHEMA IF NOT EXISTS `{PROJECT}.{dataset}` OPTIONS(location="asia-northeast1")'
        )
    for name in ["un_comtrade_partner_detail", "un_comtrade_world_total"]:
        query(
            f"CREATE OR REPLACE TABLE {table(RAW_FIXTURE, name)} "
            f"AS SELECT * FROM {table('trade_raw', name)} "
            'WHERE period_start_date >= DATE "2023-01-01" '
            'AND period_start_date < DATE "2025-01-01"'
        )
    dbt("fixture-baseline", "build", "fixture")
    baseline = snapshot(FIXTURE)
    country = table(FIXTURE, "dim_countries")
    hs = table(FIXTURE, "dim_hs_codes")
    month = table(FIXTURE, "dim_months")
    fact = table(FIXTURE, "fct_monthly_semiconductor_imports")
    audit = table(FIXTURE, "audit_partner_mapping_issues")
    downstream = ["fct_monthly_semiconductor_imports", "audit_partner_mapping_issues"]

    query(f"DELETE FROM {country} WHERE partner_code = '32'")
    dbt("fixture-missing-country-run", "run", "fixture", downstream)
    dbt(
        "fixture-missing-country-tests",
        "test",
        "fixture",
        ["assert_fact_preserves_staging", "assert_fact_contract", "assert_missing_country_audited"],
    )
    rows = query(f"SELECT * FROM {fact} WHERE partner_code = '32'")
    assert rows and all(
        not r["country_mapping_found"] and r["partner_type"] == "unknown" for r in rows
    )
    assert query(
        f"SELECT * FROM {audit} WHERE partner_code = '32' AND issue_type = 'missing_reference'"
    )
    dbt("fixture-restore-country", "run", "fixture", ["dim_countries"])

    query(f"INSERT INTO {country} SELECT * FROM {country} WHERE partner_code = '32'")
    dbt(
        "fixture-duplicate-country-test",
        "test",
        "fixture",
        ["dim_countries"],
        "unique_dim_countries_partner_code",
    )
    dbt("fixture-duplicate-country-run", "run", "fixture", downstream)
    dbt(
        "fixture-fanout-test",
        "test",
        "fixture",
        ["assert_fact_preserves_staging"],
        "assert_fact_preserves_staging",
    )
    dbt("fixture-restore-country-again", "run", "fixture", ["dim_countries"])

    query(
        f"INSERT INTO {hs} SELECT 'H5', cmd_code, hs_description, code_level, "
        f"parent_code, source_url, retrieved_at FROM {hs} WHERE hs_version = 'H6'"
    )
    dbt("fixture-other-hs-version-run", "run", "fixture", downstream)
    assert snapshot(FIXTURE) == baseline, "HS version join multiplied rows"
    dbt(
        "fixture-other-hs-version-tests",
        "test",
        "fixture",
        ["assert_fact_preserves_staging", "assert_fact_contract"],
    )
    dbt("fixture-restore-hs", "run", "fixture", ["dim_hs_codes"])

    for kind, relation, predicate, restore in [
        ("month", month, "month_start_date = DATE '2023-01-01'", "dim_months"),
        ("hs", hs, "hs_version = 'H6' AND cmd_code = '8542'", "dim_hs_codes"),
    ]:
        query(f"DELETE FROM {relation} WHERE {predicate}")
        dbt(f"fixture-missing-{kind}-run", "run", "fixture", downstream)
        dbt(
            f"fixture-missing-{kind}-preserved",
            "test",
            "fixture",
            ["assert_fact_preserves_staging"],
        )
        dbt(
            f"fixture-missing-{kind}-detected",
            "test",
            "fixture",
            ["assert_fact_contract"],
            "assert_fact_contract",
        )
        dbt(f"fixture-restore-{kind}", "run", "fixture", [restore])

    raw = table(RAW_FIXTURE, "un_comtrade_partner_detail")
    query(
        f"INSERT INTO {raw} SELECT * REPLACE('999999' AS partner_code) "
        f"FROM {raw} WHERE partner_code = '32'"
    )
    query(
        f"INSERT INTO {country} SELECT * REPLACE('999999' AS partner_code, "
        "'Unreviewed fixture' AS source_name, 'special' AS partner_type, "
        "'needs_review' AS classification_status, CAST(NULL AS STRING) AS map_iso3, "
        f"'unresolved' AS reconciliation_role) FROM {country} WHERE partner_code = '32'"
    )
    dbt("fixture-unreviewed-special-run", "run", "fixture", downstream)
    dbt(
        "fixture-unreviewed-special-tests",
        "test",
        "fixture",
        ["assert_fact_preserves_staging", "assert_fact_contract"],
    )
    special = query(f"SELECT * FROM {fact} WHERE partner_code = '999999'")
    assert special and special[0]["partner_type"] == "special" and special[0]["map_iso3"] is None
    assert query(
        f"SELECT * FROM {audit} WHERE partner_code = '999999' "
        "AND issue_type = 'classification_needs_review'"
    )
    query(f"DELETE FROM {raw} WHERE partner_code = '999999'")
    dbt("fixture-restored-build", "build", "fixture")
    assert snapshot(FIXTURE) == baseline
    assert world_before == query(
        f"SELECT TO_JSON_STRING(t) AS row "
        f"FROM {table('trade_raw', 'un_comtrade_world_total')} t "
        "WHERE period_start_date >= DATE '2023-01-01' "
        "AND period_start_date < DATE '2025-01-01' ORDER BY row"
    )
    summary["world_unchanged"] = True
    args = [
        str(ROOT / ".venv-dbt/bin/dbt"),
        "docs",
        "generate",
        "--project-dir",
        "dbt",
        "--profiles-dir",
        "dbt/local",
        "--target",
        "dev",
    ]
    result = subprocess.run(
        args,
        cwd=ROOT,
        env=dict(os.environ, DBT_RAW_PROJECT=PROJECT, DBT_RAW_DATASET="trade_raw"),
        capture_output=True,
        text=True,
    )
    (EVIDENCE / "docs-generate.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    for name in ["manifest.json", "catalog.json"]:
        shutil.copyfile(ROOT / "dbt/target" / name, EVIDENCE / name)
    summary["complete"] = True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume-fixtures", action="store_true")
    arguments = parser.parse_args()
    try:
        run(arguments.resume_fixtures)
    finally:
        summary["finished_at"] = datetime.now(UTC).isoformat()
        (EVIDENCE / "verification.json").write_text(
            json.dumps(summary, indent=2, default=str) + "\n"
        )
