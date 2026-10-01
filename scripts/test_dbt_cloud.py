"""Manual ADC-backed dbt build in a new isolated BigQuery dataset."""

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from google.cloud import bigquery


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--location", default="asia-northeast1")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--dbt", default=".venv-dbt/bin/dbt")
    parser.add_argument("--max-bytes-billed", type=int, default=10**9)
    parser.add_argument("--evidence-dir", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", args.run_id):
        parser.error("run-id must be a lowercase identifier, at most 41 characters")
    if args.max_bytes_billed <= 0:
        parser.error("max-bytes-billed must be positive")
    root = Path(__file__).resolve().parents[1]
    executable = Path(args.dbt).resolve()
    evidence = Path(args.evidence_dir).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    dataset_name = "trade_ci_" + args.run_id
    client = bigquery.Client(project=args.project, location=args.location)
    dataset = bigquery.Dataset(f"{args.project}.{dataset_name}")
    dataset.location = args.location
    dataset.default_table_expiration_ms = 24 * 60 * 60 * 1000
    dataset.labels = {"purpose": "manual_dbt_test"}
    # Never reuse a dataset: existing results cannot masquerade as a fresh run.
    client.create_dataset(dataset, exists_ok=False)
    started = datetime.now(UTC)
    status = "failed"
    try:
        with tempfile.TemporaryDirectory(prefix="trade-dbt-test-") as temporary:
            workspace = Path(temporary)
            project = workspace / "dbt"
            shutil.copytree(
                root / "dbt",
                project,
                ignore=shutil.ignore_patterns(
                    "local",
                    "day11-profile",
                    "target",
                    "logs",
                    "dbt_packages",
                    "profiles.yml",
                    ".user.yml",
                ),
            )
            profile = {
                "trade_analytics": {
                    "target": "ci",
                    "outputs": {
                        "ci": {
                            "type": "bigquery",
                            "method": "oauth",
                            "project": args.project,
                            "dataset": dataset_name,
                            "location": args.location,
                            "threads": 2,
                            "maximum_bytes_billed": args.max_bytes_billed,
                            "job_execution_timeout_seconds": 180,
                        }
                    },
                }
            }
            (workspace / "profiles.yml").write_text(json.dumps(profile))
            environment = {
                **os.environ,
                "DBT_PROJECT": args.project,
                "DBT_RAW_PROJECT": args.project,
                "DBT_RAW_DATASET": "trade_raw",
                "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
            }
            variables = json.dumps(
                {"enable_publication_audit": False, "publication_dataset": dataset_name}
            )
            # Empty parents supply schemas required by unit tests; all relations
            # are built inside the fresh target. Raw sources remain read-only.
            commands = [("seed", []), ("run", ["--empty"]), ("build", [])]
            try:
                for command, extra in commands:
                    invocation = [
                        str(executable),
                        command,
                        *extra,
                        "--project-dir",
                        str(project),
                        "--profiles-dir",
                        str(workspace),
                        "--vars",
                        variables,
                    ]
                    result = subprocess.run(
                        invocation, env=environment, text=True, capture_output=True, check=False
                    )
                    (evidence / f"{command}.log").write_text(result.stdout + result.stderr)
                    print(f"dbt {command}: exit {result.returncode}", flush=True)
                    if result.returncode:
                        raise RuntimeError(
                            f"dbt {command} failed; see {evidence / (command + '.log')}"
                        )
                status = "success"
            finally:
                for filename in ("manifest.json", "run_results.json"):
                    artifact = project / "target" / filename
                    if artifact.exists():
                        shutil.copyfile(artifact, evidence / filename)
    finally:
        jobs = [
            {
                "job_id": job.job_id,
                "state": job.state,
                "bytes_processed": job.total_bytes_processed,
                "bytes_billed": job.total_bytes_billed,
                "error": job.error_result,
            }
            for job in client.list_jobs(
                min_creation_time=started - timedelta(seconds=1), all_users=False
            )
            if job.job_type == "query"
        ]
        summary = {
            "project": args.project,
            "dataset": dataset_name,
            "location": args.location,
            "run_id": args.run_id,
            "status": status,
            "started_at": started.isoformat(),
            "completed_at": datetime.now(UTC).isoformat(),
            "maximum_bytes_billed_per_query": args.max_bytes_billed,
            "table_expiration_hours": 24,
            "jobs": jobs,
            "job_scope": "current ADC user jobs during test window; may include concurrent queries",
        }
        (evidence / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
        print(json.dumps({key: value for key, value in summary.items() if key != "jobs"}))


if __name__ == "__main__":
    main()
