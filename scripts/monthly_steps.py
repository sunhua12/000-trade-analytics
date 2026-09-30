"""Airflow-independent, single-month pipeline steps. Run one subcommand per task."""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime
from importlib import import_module
from pathlib import Path
from typing import Any

import boto3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.verify_publication_sources import verify as verify_sources  # noqa: E402
from trade_analytics.warehouse.backfill import (  # noqa: E402
    BUCKET,
    KINDS,
    PROJECT,
    RawLoader,
    source_key,
)
from trade_analytics.warehouse.gate import verify as verify_source  # noqa: E402
from trade_analytics.warehouse.publish import Publisher  # noqa: E402

LAMBDA_FUNCTION = "trade-analytics-ingestion"
AWS_REGION = "ap-northeast-1"
LOCATION = "asia-northeast1"


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
    invocation = boto3.client("lambda", region_name=AWS_REGION).invoke(
        FunctionName=LAMBDA_FUNCTION,
        InvocationType="RequestResponse",
        Payload=payload.encode(),
    )
    body = json.loads(invocation["Payload"].read())
    if invocation.get("StatusCode") != 200 or invocation.get("FunctionError"):
        raise RuntimeError("Lambda invocation failed; inspect the Lambda log for this run")
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


def publisher(args: argparse.Namespace) -> Publisher:
    bigquery = import_module("google.cloud.bigquery")
    return Publisher(
        bigquery.Client(project=args.project, location=LOCATION),
        args.project,
        args.models,
        args.raw,
        args.release,
    )


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
            "raw_end_date": next_month(args.period).isoformat(),
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
        environment.setdefault("DBT_RAW_PROJECT", args.project)
        environment.setdefault("DBT_SEND_ANONYMOUS_USAGE_STATS", "false")
        subprocess.run(command, cwd=ROOT, env=environment, check=True)
        return {"step": "build", "period": args.period, "status": "success", "vars": variables}
    runner = publisher(args)
    if args.step == "attest":
        with tempfile.TemporaryDirectory() as directory:
            s3 = boto3.client("s3", region_name=AWS_REGION)
            for kind in KINDS:
                raw_table = runner.table(args.raw, "un_comtrade_" + kind)
                identities = runner.query(
                    f"SELECT DISTINCT source_file,revision FROM {raw_table} "
                    "WHERE period_start_date=PARSE_DATE('%Y%m',@period) "
                    "AND cmd_code='8542' AND hs_version='H6'",
                    {"period": args.period},
                )
                if len(identities) != 1:
                    raise ValueError(f"raw source identity missing or mixed: {kind}")
                revision = identities[0]["revision"]
                prefix = source_key(args.period, kind, revision)
                expected_uri = f"s3://{BUCKET}/{prefix}/data.ndjson"
                if identities[0]["source_file"] != expected_uri:
                    raise ValueError(f"raw source URI mismatch: {kind}")
                for key, filename in (
                    (prefix + "/data.ndjson", f"{kind}.ndjson"),
                    (prefix + "/manifest.json", f"{kind}.manifest.json"),
                ):
                    contents = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
                    (Path(directory) / filename).write_bytes(contents)
            reports = verify_sources(runner, args.period, Path(directory), download=False)
        return {
            "step": "attest",
            "period": args.period,
            "status": "verified",
            "sources": [
                {
                    key: report[key]
                    for key in (
                        "query_type",
                        "revision",
                        "checksum",
                        "source_file",
                        "snapshot_hash",
                    )
                }
                for report in reports
            ],
            "jobs": job_metadata(runner.jobs),
        }
    if args.step == "audit":
        result = runner.audit(args.run_id, args.period)
        return {
            "step": "audit",
            "period": args.period,
            "run_id": args.run_id,
            "status": result["status"],
            "reason_codes": result["reason_codes"],
            "jobs": job_metadata(runner.jobs),
        }
    if args.step == "gate":
        audit_table = runner.table(runner.release, "quality_audit_history")
        rows = runner.query(
            f"SELECT period,status,reason_codes FROM {audit_table} WHERE run_id=@run_id",
            {"run_id": args.run_id},
        )
        if len(rows) != 1 or rows[0]["period"] != args.period:
            raise ValueError("quality audit missing or run ID belongs to another month")
        if rows[0]["status"] not in ("PASS", "WARN"):
            raise ValueError(f"quality gate blocked: {rows[0]['status']}")
        return {
            "step": "gate",
            "period": args.period,
            "run_id": args.run_id,
            "status": rows[0]["status"],
            "jobs": job_metadata(runner.jobs),
        }
    if args.step == "publish":
        published_table = runner.table(runner.release, "mart_us_semiconductor_supply_chain")
        current = runner.query(
            f"SELECT DISTINCT published_run_id FROM {published_table} "
            "WHERE period_start_date=PARSE_DATE('%Y%m',@period) "
            "AND cmd_code='8542' AND hs_version='H6'",
            {"period": args.period},
        )
        if len(current) > 1:
            raise ValueError("published month contains multiple run IDs")
        if current and current[0]["published_run_id"] != args.run_id and not args.allow_republish:
            raise ValueError(
                "month already published by another run; revision requires --allow-republish"
            )
        runner.publish(args.run_id, args.period)
        attempts_table = runner.table(runner.release, "publication_attempts")
        attempts = runner.query(
            f"SELECT publish_status FROM {attempts_table} "
            "WHERE run_id=@run_id AND period=@period "
            "ORDER BY attempted_at DESC,attempt_id DESC LIMIT 1",
            {"run_id": args.run_id, "period": args.period},
        )
        if len(attempts) != 1 or attempts[0]["publish_status"] not in (
            "published",
            "already_published",
        ):
            raise RuntimeError("publication outcome could not be confirmed from audit history")
        return {
            "step": "publish",
            "period": args.period,
            "run_id": args.run_id,
            "status": attempts[0]["publish_status"],
            "jobs": job_metadata(runner.jobs),
        }
    raise ValueError(f"unknown step: {args.step}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "step", choices=("ingest", "load", "attest", "build", "audit", "gate", "publish")
    )
    result.add_argument("--period", required=True, help="YYYYMM, 202301 or later")
    result.add_argument("--kind", choices=KINDS)
    result.add_argument("--revision", type=int, default=1)
    result.add_argument("--run-id")
    result.add_argument("--allow-republish", action="store_true")
    result.add_argument("--project", default=PROJECT)
    result.add_argument("--models", default="trade_analytics_day10_dev")
    result.add_argument("--raw", default="trade_raw")
    result.add_argument("--release", default="trade_analytics_published")
    result.add_argument("--dbt-executable", type=Path)
    result.add_argument("--profiles-dir", type=Path, default=ROOT / "dbt/day11-profile")
    result.add_argument("--target", default="day11")
    return result


def main() -> None:
    command = parser()
    args = command.parse_args()
    if args.step in ("ingest", "load") and args.kind is None:
        command.error("--kind is required for ingest and load")
    if args.step in ("ingest", "audit", "gate", "publish") and not args.run_id:
        command.error("--run-id is required for ingest, audit, gate and publish")
    print(json.dumps(execute(args), default=str, sort_keys=True))


if __name__ == "__main__":
    main()
