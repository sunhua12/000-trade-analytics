"""Run the real publisher against isolated synthetic tables; never mutate trade_raw."""

import argparse
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from google.cloud import bigquery  # noqa: E402

from scripts.quality_fixture import cases, fixture  # noqa: E402
from trade_analytics.warehouse.publish import (  # noqa: E402
    CANDIDATE,
    PUBLISHED,
    Publisher,
    identifier,
)

PROJECT = "trade-analytics-508604"
INPUTS = "trade_analytics_day10_inputs_fixture"
RELEASE = "trade_analytics_day10_publish_fixture"


def main():
    global INPUTS, RELEASE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--transactions-only", action="store_true")
    parser.add_argument("--tag", default="")
    args = parser.parse_args()
    evidence = ROOT / "docs/evidence/day10"
    if args.tag:
        tag = identifier(args.tag)
        INPUTS = f"trade_analytics_day10_{tag}_inputs_fixture"
        RELEASE = f"trade_analytics_day10_{tag}_publish_fixture"
        evidence = evidence / tag
    evidence.mkdir(parents=True, exist_ok=True)
    client = bigquery.Client(project=PROJECT, location="asia-northeast1")
    runner = Publisher(client, PROJECT, INPUTS, INPUTS, RELEASE)
    checkpoint = evidence / "fixture-checkpoint.json"
    resume = "--resume" in sys.argv and checkpoint.exists()
    report = json.loads(checkpoint.read_text()) if resume else {"cases": []}
    report["result"] = "running"
    prefix = report.setdefault("prefix", uuid.uuid4().hex[:10])
    if resume:
        old_jobs = evidence / "fixture-jobs.json"
        if old_jobs.exists():
            runner.jobs = json.loads(old_jobs.read_text())["jobs"]

    def save():
        report["cases"] = list({case["name"]: case for case in report["cases"]}.values())
        runner.save_evidence(evidence / "fixture-jobs.json")
        checkpoint.write_text(json.dumps(report, default=str, indent=2) + "\n")

    schemas = {}
    try:
        runner.query(
            f"CREATE SCHEMA IF NOT EXISTS `{PROJECT}.{INPUTS}` OPTIONS(location='asia-northeast1')"
        )
        for name, source in (
            (CANDIDATE, "trade_analytics_day10_dev"),
            ("un_comtrade_partner_detail", "trade_raw"),
            ("un_comtrade_world_total", "trade_raw"),
            ("audit_ingestion_runs", "trade_raw"),
        ):
            filter_sql = (
                "WHERE period_start_date=DATE '2023-01-01' AND FALSE"
                if name.startswith("un_comtrade")
                else "WHERE FALSE"
            )
            runner.query(
                f"""
CREATE OR REPLACE TABLE {runner.table(INPUTS, name)} AS SELECT * FROM
 {runner.table(source, name)} {filter_sql}
                """
            )
            schemas[name] = client.get_table(f"{PROJECT}.{INPUTS}.{name}").schema
        runner.initialize()
        # Published fixtures may be reset; real published data is never targeted here.
        if not resume:
            runner.query(f"DELETE FROM {runner.table(RELEASE, PUBLISHED)} WHERE TRUE")

        def load(data):
            parts = ["BEGIN TRANSACTION;"]
            for name, key in (
                (CANDIDATE, "candidate"),
                ("un_comtrade_partner_detail", "detail"),
                ("un_comtrade_world_total", "world"),
            ):
                table = runner.table(INPUTS, name)
                columns = []
                for field in schemas[name]:
                    expr = f"JSON_VALUE(row,'$.{field.name}')"
                    fieldtype = {"INTEGER": "INT64", "FLOAT": "FLOAT64", "BOOLEAN": "BOOL"}.get(
                        field.field_type, field.field_type
                    )
                    if fieldtype != "STRING":
                        expr = f"CAST({expr} AS {fieldtype})"
                    columns.append(expr)
                parts.append(
                    f"""
DELETE FROM {table} WHERE TRUE; INSERT INTO {table} SELECT {",".join(columns)} FROM
 UNNEST(JSON_QUERY_ARRAY(@inputs,'$.{key}')) row;
                    """
                )
            parts.append(f"DELETE FROM {runner.table(RELEASE, 'source_attestations')} WHERE TRUE;")
            parts.append(
                f"""
INSERT INTO {runner.table(RELEASE, "source_attestations")} SELECT
 TO_JSON_STRING(row),CURRENT_TIMESTAMP() FROM
 UNNEST(JSON_QUERY_ARRAY(PARSE_JSON(@inputs),'$.loads')) row;
                """
            )
            parts.append("COMMIT TRANSACTION;")
            runner.query("\n".join(parts), {"inputs": json.dumps(data, default=str)})

        def snapshot():
            return runner.query(
                f"""
SELECT TO_JSON_STRING(p) row_json FROM {runner.table(RELEASE, PUBLISHED)} p ORDER BY row_json
                """
            )

        def attempt(name, data, expected, period="202301"):
            run_id = f"{prefix}-{name}"
            if any(c["name"] == name for c in report["cases"]):
                print(f"Already verified {name}", flush=True)
                return run_id
            load(data)
            run_id = f"{prefix}-{name}"
            audit = runner.audit(run_id, period)
            assert audit["status"] == expected, (name, audit)
            before = snapshot()
            try:
                runner.publish(run_id, period)
                assert expected != "FAIL", "FAIL unexpectedly published"
            except Exception as error:
                if expected != "FAIL":
                    raise
                assert "gate_missing_or_failed" in str(error), str(error)
                assert snapshot() == before, "Failed gate changed published rows"
            report["cases"].append(
                {
                    "name": name,
                    "run_id": run_id,
                    "status": audit["status"],
                    "reasons": audit["reason_codes"],
                    "result": "passed",
                }
            )
            save()
            print(f"PASS {name}: {expected}", flush=True)
            return run_id

        # First failed partition must remain absent, with audit and summary visible.
        attempt("first_failure", fixture(world=None, period="202302"), "FAIL", "202302")
        for name, data, status in [] if args.transactions_only else cases():
            attempt(name, data, status)
        a = attempt("baseline", fixture(), "PASS")
        baseline = snapshot()
        runner.publish(a, "202301")
        assert snapshot() == baseline
        report["cases"].append({"name": "idempotent_retry", "result": "passed"})
        load(fixture(("50", "50")))
        rollback_id = f"{prefix}-rollback-{uuid.uuid4().hex[:6]}"
        assert runner.audit(rollback_id, "202301")["status"] == "PASS"
        try:
            runner.publish(rollback_id, "202301", rollback_probe=True)
            raise AssertionError("Rollback probe did not fail")
        except Exception as error:
            assert "fixture_rollback_probe" in str(error), str(error)
        assert snapshot() == baseline
        report["cases"].append(
            {"name": "transaction_rollback_preserves_all_columns", "result": "passed"}
        )
        # Modify a frozen candidate after audit. Hash gate must reject it.
        runner.query(
            f"""
UPDATE {runner.table(RELEASE, "candidate_batches")} SET source_name='tampered' WHERE
 candidate_batch_id=@run_id
            """,
            {"run_id": rollback_id},
        )
        try:
            runner.publish(rollback_id, "202301")
            raise AssertionError("Tampered batch published")
        except Exception as error:
            assert "candidate_changed" in str(error), str(error)
        assert snapshot() == baseline
        report["cases"].append({"name": "frozen_candidate_tampering", "result": "passed"})
        # Publish another partition, then remove one partner via an accepted revision.
        attempt("other_month", fixture(period="202302"), "PASS", "202302")
        other = [r for r in snapshot() if "202302" in r["row_json"]]
        revised = attempt("revision_removes_partner", fixture(("100",)), "PASS")
        current = snapshot()
        assert len(current) == 3 and [r for r in current if "202302" in r["row_json"]] == other
        runner.publish(revised, "202301")
        assert snapshot() == current
        runner.publish(a, "202301")  # previously published older retry is a no-op
        assert snapshot() == current
        report["cases"].append({"name": "partition_replace_and_old_retry", "result": "passed"})
        # Missing audit and wrong business partition cannot publish.
        for run_id, period, reason in (
            (prefix + "-missing", "202301", "gate_missing_or_failed"),
            (revised, "202302", "gate_missing_or_failed"),
        ):
            try:
                runner.publish(run_id, period)
                raise AssertionError("Missing or mismatched audit published")
            except Exception as error:
                assert reason in str(error)
            assert snapshot() == current
        report["cases"].append({"name": "missing_audit_and_partition_mismatch", "result": "passed"})
        # Upstream errors must still create a durable FAIL audit.
        broken = Publisher(client, PROJECT, "nonexistent_day10_models", INPUTS, RELEASE)
        upstream = prefix + "-upstream-" + uuid.uuid4().hex[:6]
        try:
            broken.audit(upstream, "202303")
            raise AssertionError("Missing upstream did not fail")
        except Exception as error:
            assert "Not found" in str(error) or "not found" in str(error)
        finally:
            runner.jobs.extend(broken.jobs)
        history = runner.query(
            f"""
SELECT status,reason_codes FROM {runner.table(RELEASE, "quality_audit_history")} WHERE
 run_id=@run_id
            """,
            {"run_id": upstream},
        )
        assert history == [{"status": "FAIL", "reason_codes": ["upstream_snapshot_failed"]}]
        assert snapshot() == current
        report["cases"].append({"name": "upstream_failure_persisted", "result": "passed"})
        report["summary"] = runner.query(
            f"SELECT * FROM {runner.table(RELEASE, 'publication_quality_summary')}"
        )
        report["result"] = "passed"
    finally:
        if report.get("result") != "passed":
            report["result"] = "failed"
        save()
        (evidence / "fixtures.json").write_text(json.dumps(report, default=str, indent=2) + "\n")


if __name__ == "__main__":
    main()
