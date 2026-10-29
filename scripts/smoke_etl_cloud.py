"""Explicit, isolated S3/BigQuery/dbt smoke test; never writes production tables."""

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

import boto3
from google.cloud import bigquery

from trade_analytics import pipeline
from trade_analytics.config import ROOT, PipelineConfig
from trade_analytics.export.queries import SnapshotReader
from trade_analytics.export.service import publish_snapshot, validate_build
from trade_analytics.export.v2 import verify_v2 as verify_snapshot
from trade_analytics.export.website import stage_snapshot
from trade_analytics.ingestion.manifest import artifact_partition
from trade_analytics.ingestion.queries import ComtradeQuery, QueryType
from trade_analytics.ingestion.s3_storage import S3Storage
from trade_analytics.ingestion.schemas import ComtradeResponse
from trade_analytics.ingestion.service import validate_dataset
from trade_analytics.ingestion.storage import LocalStorage
from trade_analytics.pipeline import load_environment
from trade_analytics.warehouse.loader import RawLoader
from trade_analytics.warehouse.read_settings import Settings
from trade_analytics.warehouse.source_validation import verify


def cleanup_s3(s3: Any, bucket: str, prefix: str, keys: set[str]) -> None:
    """Delete only this run's exact keys, including retained S3 object versions."""
    versions = []
    for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket, Prefix=prefix):
        versions.extend(
            {"Key": item["Key"], "VersionId": item["VersionId"]}
            for name in ("Versions", "DeleteMarkers")
            for item in page.get(name, [])
            if item["Key"] in keys
        )
    if versions:
        response = s3.delete_objects(Bucket=bucket, Delete={"Objects": versions})
        assert not response.get("Errors"), "test S3 version cleanup failed"


def main() -> None:
    load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", args.run_id):
        parser.error("run-id must be a lowercase identifier up to 41 characters")
    dataset = "trade_etl_fixture_" + args.run_id
    prefix = f"_smoke/etl/{args.run_id}/un_comtrade"
    evidence = args.evidence_dir
    evidence.mkdir(parents=True, exist_ok=True)
    client = bigquery.Client(project=args.project, location="asia-northeast1")
    s3 = boto3.client("s3")
    target = bigquery.Dataset(f"{args.project}.{dataset}")
    target.location = "asia-northeast1"
    target.default_table_expiration_ms = 24 * 60 * 60 * 1000
    target.labels = {"purpose": "etl_smoke_test"}
    artifact_prefix = f"_smoke/etl/{args.run_id}/stages"
    assert not s3.list_objects_v2(Bucket=args.bucket, Prefix=f"_smoke/etl/{args.run_id}/").get(
        "Contents"
    ), "run id already exists in S3; choose a fresh id"
    client.create_dataset(target, exists_ok=False)
    loader = RawLoader(client, project=args.project, raw_dataset=dataset)
    keys: set[str] = set()
    checks: dict[str, Any] = {}
    status = "failed"
    try:
        for name in ("raw-tables.sql", "audit-ingestion-runs.sql"):
            sql = (
                (ROOT / "sql" / name)
                .read_text()
                .replace("trade-analytics-508604.trade_raw", f"{args.project}.{dataset}")
            )
            loader.query(sql, {})
        with tempfile.TemporaryDirectory(prefix="trade-etl-smoke-") as temporary:
            workspace = Path(temporary)
            fixture = json.loads(
                (ROOT / "tests/fixtures/comtrade_preview_response.json").read_text()
            )

            def source(reporter: int, kind: QueryType, revision: int) -> dict[str, Any]:
                payload = copy.deepcopy(fixture)
                for row in payload["data"]:
                    row.update(
                        period="201601",
                        reporterCode=reporter,
                        cmdCode="854231",
                        classificationCode="H4" if revision == 1 else "H5",
                        isOriginalClassification=True,
                    )
                    row["primaryValue"] = str({0: 300, 156: 100, 410: 200}[row["partnerCode"]])
                payload["data"] = [
                    r
                    for r in payload["data"]
                    if (r["partnerCode"] == 0) == (kind == QueryType.WORLD_TOTAL)
                    and not (revision > 1 and r["partnerCode"] == 410)
                ]
                if revision > 1:
                    for row in payload["data"]:
                        row["primaryValue"] = "150"
                payload["count"] = len(payload["data"])
                query = ComtradeQuery(
                    period="201601",
                    reporter_code=reporter,
                    cmd_code="854231",
                    expected_hs_version="H4" if revision == 1 else "H5",
                    query_type=kind,
                    revision=revision,
                )
                data = validate_dataset(query, ComtradeResponse.model_validate(payload))
                local = LocalStorage(workspace / "raw").write(data)
                storage = S3Storage(
                    bucket=args.bucket,
                    client=s3,
                    prefix=prefix,
                )
                # Track only keys owned by this fresh test invocation for cleanup.
                data_key = f"{prefix}/{artifact_partition(query)}/data.ndjson"
                manifest_key = data_key.removesuffix("data.ndjson") + "manifest.json"
                keys.update((data_key, manifest_key))
                storage.write(local.data_path)
                assert storage.write(local.data_path).status == "already_exists"
                raw = s3.get_object(Bucket=args.bucket, Key=data_key)["Body"].read()
                manifest = s3.get_object(Bucket=args.bucket, Key=manifest_key)["Body"].read()
                assert raw == local.data_path.read_bytes()
                return verify(raw, manifest, f"s3://{args.bucket}/{data_key}")

            original = [source(r, k, 1) for r in (842, 156) for k in QueryType]
            checks["initial_load"] = loader.load_month("201601", original)
            checks["idempotent_replay"] = loader.load_month("201601", original)
            assert checks["idempotent_replay"]["status"] == "already_loaded"
            revised = [source(842, k, 2) for k in QueryType]
            checks["replacement"] = loader.load_month("201601", revised)
            rows = loader.query(
                f"SELECT reporter_code,partner_code,revision,hs_version FROM "
                f"{loader.table('partner_detail')} WHERE period_start_date=DATE '2016-01-01'",
                {},
            )
            assert {(r["reporter_code"], r["partner_code"], r["revision"]) for r in rows} == {
                ("842", "156", 2),
                ("156", "156", 1),
                ("156", "410", 1),
            }
            assert all(r["hs_version"] == "H5" for r in rows if r["reporter_code"] == "842")
            checks["removed_partner_and_hs_replacement"] = True
            try:
                loader.load_month("201601", [original[0]])
            except ValueError as error:
                assert str(error) == "stale_revision"
                checks["stale_revision_rejected"] = True
            else:
                raise AssertionError("stale revision was accepted")

            # Force two independent clients to observe the same pre-transaction metadata.
            from threading import Barrier

            barrier = Barrier(2)

            class RacingLoader(RawLoader):
                def query(self, sql: str, params: dict[str, str]) -> list[dict[str, Any]]:
                    if "BEGIN TRANSACTION" in sql:
                        barrier.wait(timeout=60)
                    return super().query(sql, params)

            third = [source(842, k, 3) for k in QueryType]

            def race(_: int) -> str:
                try:
                    RacingLoader(client, project=args.project, raw_dataset=dataset).load_month(
                        "201601", third
                    )
                    return "committed"
                except Exception as error:
                    message = str(error).lower()
                    if not any(
                        term in message
                        for term in (
                            "source changed during load",
                            "concurrent update",
                            "could not serialize",
                            "transaction is aborted",
                        )
                    ):
                        raise
                    return "conflict_rejected"

            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(race, range(2)))
            assert outcomes.count("committed") == 1, outcomes
            checks["concurrent_writer_outcomes"] = outcomes

            project = workspace / "dbt"
            shutil.copytree(
                ROOT / "dbt",
                project,
                ignore=shutil.ignore_patterns(
                    "target", "logs", "profiles.yml", "dbt_packages", "local", ".user.yml"
                ),
            )
            profile = {
                "trade_analytics": {
                    "target": "fixture",
                    "outputs": {
                        "fixture": {
                            "type": "bigquery",
                            "method": "oauth",
                            "project": args.project,
                            "dataset": dataset,
                            "location": "asia-northeast1",
                            "threads": 1,
                            "maximum_bytes_billed": 10**9,
                            "job_execution_timeout_seconds": 180,
                        }
                    },
                }
            }
            (workspace / "profiles.yml").write_text(json.dumps(profile))
            environment = {
                **os.environ,
                "DBT_RAW_PROJECT": args.project,
                "DBT_RAW_DATASET": dataset,
                "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
            }
            executable = str(ROOT / ".venv-dbt/bin/dbt")
            common = ["--project-dir", str(project), "--profiles-dir", str(workspace)]
            variables = json.dumps(
                {"multi_market_start_date": "2016-01-01", "multi_market_end_date": "2016-01-01"}
            )
            for command, extra in [
                ("seed", []),
                (
                    "build",
                    [
                        "--select",
                        "+mart_multi_market_ic_monthly",
                        "+mart_multi_market_ic_partners",
                        "--indirect-selection",
                        "cautious",
                        "--vars",
                        variables,
                    ],
                ),
            ]:
                result = subprocess.run(
                    [executable, command, *common, *extra],
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                (evidence / f"dbt-{command}.log").write_text(result.stdout + result.stderr)
                assert result.returncode == 0, f"dbt {command} failed; see evidence logs"
            settings = Settings(
                project=args.project,
                dataset=dataset,
                first_month=date(2016, 1, 1),
                after_last_month=date(2016, 2, 1),
            )
            build = validate_build(project / "target", settings)
            reader = SnapshotReader(settings, client)
            raw = reader.read(settings.first_month, settings.after_last_month)
            release = publish_snapshot(
                raw,
                workspace / "snapshot",
                settings.first_month,
                settings.after_last_month,
                build=build,
                jobs=reader.jobs,
            )
            stage_snapshot(workspace / "snapshot", workspace / "public/data")
            assert verify_snapshot(workspace / "snapshot")["snapshot_id"] == release["snapshot_id"]
            checks["dbt_and_json_v2"] = {
                "monthly_rows": len(raw["monthly"]),
                "partner_rows": len(raw["partners"]),
            }
            for filename in ("manifest.json", "run_results.json"):
                shutil.copyfile(project / "target" / filename, evidence / filename)
            pointer_before = (workspace / "snapshot/current.json").read_bytes()
            public_before = (workspace / "public/data/manifest.json").read_bytes()
            (project / "tests/smoke_failure.sql").write_text(
                "select 1 as deliberate_failure "
                "from {{ ref('mart_multi_market_ic_monthly') }} limit 1"
            )
            failed = subprocess.run(
                [executable, "build", *common, "--select", "smoke_failure"],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            (evidence / "dbt-expected-failure.log").write_text(failed.stdout + failed.stderr)
            assert failed.returncode != 0, "deliberate dbt failure was not detected"
            try:
                validate_build(project / "target", settings)
            except ValueError:
                checks["failed_dbt_build_rejected"] = True
            else:
                raise AssertionError("failed build evidence accepted")
            assert (workspace / "snapshot/current.json").read_bytes() == pointer_before
            assert (workspace / "public/data/manifest.json").read_bytes() == public_before
            checks["previous_snapshot_preserved"] = True
            # Exercise the production four-stage functions with independent temporary disks.
            with patch.dict(
                os.environ,
                {
                    "RAW_BUCKET": args.bucket,
                    "DBT_RAW_PROJECT": args.project,
                    "DBT_RAW_DATASET": dataset,
                    "TRADE_BQ_PROJECT": args.project,
                    "TRADE_BQ_DATASET": dataset,
                    "TRADE_BQ_LOCATION": "asia-northeast1",
                    "TRADE_DBT_EXECUTABLE": executable,
                },
            ):
                config = PipelineConfig(
                    start="201601",
                    end="201601",
                    reporters=(842, 156),
                    sync_only=True,
                    root=workspace / "raw",
                    run_id="fixture",
                    raw_prefix=prefix,
                    artifact_prefix=artifact_prefix,
                )
                extracted = pipeline.extract(config)
                # Extract output must survive removal of all local source files.
                shutil.rmtree(config.root)
                loaded = pipeline.load(config, extracted)
                pipeline.load(config, extracted)
                transformed = pipeline.transform(config, loaded)
                published = pipeline.publish(config, transformed)
                store = pipeline.artifact_store(config)
                release = store.read(published)
                website_manifest = json.loads(store.get(release["website"] + "/data/manifest.json"))
                assert website_manifest["snapshot_id"] == release["snapshot_id"]
                assert store.get(release["website"] + "/index.html")
                checks["four_durable_stages"] = {
                    "extract": extracted,
                    "load": loaded,
                    "transform": transformed,
                    "publish": published,
                    "worker_local_raw_removed": True,
                    "website_built": True,
                }
                # Use the disposable dbt project, never inject failures into production sources.
                (project / "profiles.yml").write_text(json.dumps(profile))
                with patch.object(pipeline, "ROOT", workspace):
                    try:
                        pipeline.transform(config, loaded)
                    except subprocess.CalledProcessError:
                        checks["stage_transform_failure"] = True
                    else:
                        raise AssertionError("deliberate transform failure was accepted")
                try:
                    pipeline.publish(config, transformed)
                except ValueError as error:
                    assert "latest transform" in str(error)
                    checks["failed_latest_transform_blocks_publish"] = True
                else:
                    raise AssertionError("publish accepted stale successful transform")
                (project / "tests/smoke_failure.sql").unlink()
                with patch.object(pipeline, "ROOT", workspace):
                    recovered = pipeline.transform(config, loaded)
                recovered_publish = pipeline.publish(config, recovered)
                assert store.read(recovered_publish)["snapshot_id"] != release["snapshot_id"]
                checks["transform_publish_recovery_without_extract_or_load"] = True
            status = "success"
    finally:
        # These resources were freshly created by this run, never production resources.
        client.delete_dataset(target, delete_contents=True)
        cleanup_s3(s3, args.bucket, prefix, keys)
        artifact_keys = {
            item["Key"]
            for page in s3.get_paginator("list_objects_v2").paginate(
                Bucket=args.bucket, Prefix=artifact_prefix + "/"
            )
            for item in page.get("Contents", [])
        }
        cleanup_s3(s3, args.bucket, artifact_prefix + "/", artifact_keys)
        summary = {
            "status": status,
            "dataset": dataset,
            "s3_prefix": prefix,
            "checks": checks,
            "cleanup": "complete",
        }
        (evidence / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
        print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
