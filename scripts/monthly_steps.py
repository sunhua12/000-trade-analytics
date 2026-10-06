"""Airflow-independent, single-month pipeline steps. Run one subcommand per task."""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime
from importlib import import_module
from pathlib import Path
from typing import Any

import boto3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.pipeline_exit import RetryablePipelineError, exit_for_error  # noqa: E402
from trade_analytics.warehouse.loader import (  # noqa: E402
    BUCKET,
    KINDS,
    PROJECT,
    RawLoader,
    source_key,
)
from trade_analytics.warehouse.source_validation import verify as verify_source  # noqa: E402

LAMBDA_FUNCTION = os.environ.get("TRADE_LAMBDA_FUNCTION", "trade-analytics-ingestion")
AWS_REGION = os.environ.get("AWS_REGION", "ap-northeast-1")
LOCATION = os.environ.get("TRADE_BQ_LOCATION", "asia-northeast1")
API_REQUEST_SPACING_SECONDS = 1.0


def next_month(period: str) -> date:
    year, month = int(period[:4]), int(period[4:])
    return date(year + (month == 12), month % 12 + 1, 1)


def validate_period(period: str) -> None:
    source_key(period, KINDS[0])


def job_metadata(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: job[key] for key in ("job_id", "status", "result") if key in job} for job in jobs]


def invoke_lambda(period: str, kind: str, revision: int, run_id: str) -> dict[str, Any]:
    prefix = source_key(period, kind, revision)
    s3 = boto3.client("s3", region_name=AWS_REGION)
    from botocore.exceptions import ClientError

    existing: dict[str, bytes | None] = {}
    for filename in ("data.ndjson", "manifest.json"):
        try:
            existing[filename] = s3.get_object(Bucket=BUCKET, Key=f"{prefix}/{filename}")[
                "Body"
            ].read()
        except ClientError as error:
            if str(error.response.get("Error", {}).get("Code", "")) not in (
                "404",
                "NoSuchKey",
                "NotFound",
            ):
                raise
            existing[filename] = None
    if all(value is not None for value in existing.values()):
        data_bytes = existing["data.ndjson"]
        manifest_bytes = existing["manifest.json"]
        assert data_bytes is not None and manifest_bytes is not None
        attested = verify_source(
            data_bytes,
            manifest_bytes,
            f"s3://{BUCKET}/{prefix}/data.ndjson",
        )
        manifest = attested["manifest"]
        if manifest["period"] != period or manifest["query_type"] != kind:
            raise ValueError("stored source identity mismatch")
        return {
            "step": "ingest",
            "period": period,
            "kind": kind,
            "revision": revision,
            "run_id": run_id,
            "status": "already_exists",
            "row_count": manifest["row_count"],
            "checksum": manifest["checksum"],
            "data_uri": attested["source_file"],
            "manifest_uri": attested["manifest_file"],
        }
    if any(value is not None for value in existing.values()):
        raise ValueError("S3 source pair is incomplete")
    payload = json.dumps(
        {
            "action": "ingest",
            "period": period,
            "cmd_code": "8542",
            "query_type": kind,
            "revision": revision,
            "run_id": run_id,
        }
    )
    # The Pool serializes task execution; this pause also separates fresh API calls.
    time.sleep(API_REQUEST_SPACING_SECONDS)
    invocation = boto3.client("lambda", region_name=AWS_REGION).invoke(
        FunctionName=LAMBDA_FUNCTION,
        InvocationType="RequestResponse",
        Payload=payload.encode(),
    )
    body = json.loads(invocation["Payload"].read())
    if invocation.get("StatusCode") != 200:
        if int(invocation.get("StatusCode", 0)) >= 500:
            raise RetryablePipelineError("Lambda service failed; inspect its log")
        raise RuntimeError("Lambda invocation failed; inspect the Lambda log for this run")
    if invocation.get("FunctionError"):
        if body.get("errorType") == "ComtradeTransientError":
            raise RetryablePipelineError("Comtrade request exhausted Lambda retries")
        raise RuntimeError("Lambda ingestion failed; inspect the Lambda log for this run")
    if body.get("status") not in ("success", "already_exists"):
        raise RuntimeError(f"Lambda ingestion failed: {body.get('status')}")
    expected_uri = f"s3://{BUCKET}/{prefix}"
    if (
        body.get("period") != period
        or body.get("query_type") != kind
        or body.get("data_uri") != expected_uri + "/data.ndjson"
        or body.get("manifest_uri") != expected_uri + "/manifest.json"
        or not isinstance(body.get("row_count"), int)
        or body["row_count"] < 1
        or not isinstance(body.get("checksum"), str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", body["checksum"])
    ):
        raise ValueError("Lambda response metadata does not match the requested source")
    return {
        "step": "ingest",
        "period": period,
        "kind": kind,
        "revision": revision,
        "run_id": run_id,
        "status": body["status"],
        "row_count": body["row_count"],
        "checksum": body["checksum"],
        "data_uri": body["data_uri"],
        "manifest_uri": body["manifest_uri"],
    }


def execute(args: argparse.Namespace) -> dict[str, Any]:
    validate_period(args.period)
    if args.step == "ingest":
        return invoke_lambda(args.period, args.kind, args.revision, args.run_id)
    if args.step == "load":
        bigquery = import_module("google.cloud.bigquery")
        loader = RawLoader(
            bigquery.Client(project=args.project, location=LOCATION),
            boto3.client("s3", region_name=AWS_REGION),
            project=args.project,
            raw_dataset=args.raw,
        )
        result = loader.load(args.period, args.kind, args.revision)
        return {
            "step": "load",
            **result,
            "revision": args.revision,
            "jobs": job_metadata(loader.jobs),
        }
    if args.step == "build":
        if args.dbt_executable is None:
            raise ValueError("--dbt-executable is required for build")
        variables = {
            "raw_start_date": "2023-01-01",
            "raw_end_date": "2100-01-01",
            "month_spine_start_date": "2023-01-01",
            "month_spine_end_date": datetime.strptime(args.period, "%Y%m").date().isoformat(),
        }
        command = [
            str(args.dbt_executable),
            "build",
            "--project-dir",
            str(ROOT / "dbt"),
            "--profiles-dir",
            str(args.profiles_dir),
            "--target",
            args.target,
            "--vars",
            json.dumps(variables),
        ]
        environment = os.environ.copy()
        environment["DBT_RAW_PROJECT"] = args.project
        environment["DBT_RAW_DATASET"] = args.raw
        environment.setdefault("DBT_SEND_ANONYMOUS_USAGE_STATS", "false")
        subprocess.run(command, cwd=ROOT, env=environment, check=True)
        return {"step": "build", "period": args.period, "status": "success", "vars": variables}
    raise ValueError(f"unknown step: {args.step}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("step", choices=("ingest", "load", "build"))
    result.add_argument("--period", required=True, help="YYYYMM, 202301 or later")
    result.add_argument("--kind", choices=KINDS)
    result.add_argument("--revision", type=int, default=1)
    result.add_argument("--run-id")
    result.add_argument("--project", default=PROJECT)
    result.add_argument("--raw", default=os.environ.get("DBT_RAW_DATASET", "trade_raw"))
    result.add_argument("--dbt-executable", type=Path)
    result.add_argument("--profiles-dir", type=Path, default=ROOT / "dbt")
    result.add_argument("--target", default="dev")
    return result


def main() -> None:
    command = parser()
    args = command.parse_args()
    if args.step in ("ingest", "load") and args.kind is None:
        command.error("--kind is required for ingest and load")
    if args.step == "ingest" and not args.run_id:
        command.error("--run-id is required for ingest")
    print(json.dumps(execute(args), default=str, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit(exit_for_error(error)) from error
