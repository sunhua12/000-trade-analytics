"""Extract → persist raw → load BigQuery → dbt → JSON v2."""

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

from trade_analytics.artifacts import Artifacts
from trade_analytics.config import ROOT, PipelineConfig
from trade_analytics.export.queries import SnapshotReader
from trade_analytics.export.service import publish_snapshot, validate_build
from trade_analytics.export.website import stage_snapshot
from trade_analytics.ingestion.multi_market import MARKETS, BatchResult, run_batch
from trade_analytics.ingestion.s3_storage import S3Storage
from trade_analytics.ingestion.storage import scan_sources
from trade_analytics.warehouse.loader import RawLoader
from trade_analytics.warehouse.source_validation import verify
from trade_analytics.warehouse.writer_lock import writer_lock

INCOMPLETE_EXIT_CODE = 2


def load_environment() -> None:
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value.strip().strip("\"'"))


def load_bigquery(sources: list[dict[str, Any]], config: PipelineConfig) -> dict[str, Any]:
    import boto3
    from google.cloud import bigquery

    s3 = boto3.client("s3")
    client = bigquery.Client(
        project=config.raw_project,
        location=config.settings.location,
    )
    loader = RawLoader(
        client,
        project=config.raw_project,
        raw_dataset=config.raw_dataset,
        location=config.settings.location,
        maximum_bytes_billed=config.settings.maximum_bytes_billed,
    )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    artifacts = Artifacts(config.raw_bucket, "", s3)
    for source in sources:
        accepted = verify(
            artifacts.get(source["data_uri"]),
            artifacts.get(source["manifest_uri"]),
            source["data_uri"],
        )
        if (
            accepted["manifest"]["checksum"] != source["checksum"]
            or accepted["manifest"]["revision"] != source["revision"]
        ):
            raise ValueError("source differs from extract handoff")
        grouped[accepted["manifest"]["period"]].append(accepted)
    results = [loader.load_month(month, sources) for month, sources in sorted(grouped.items())]
    return {"months": sorted(grouped), "results": results, "jobs": loader.jobs}


def run_dbt_build(config: PipelineConfig, months: list[str], workspace: Path) -> None:
    subprocess.run(
        [
            config.dbt_executable,
            "build",
            "--project-dir",
            str(ROOT / "dbt"),
            "--profiles-dir",
            str(ROOT / "dbt"),
            "--target-path",
            str(workspace / "target"),
            "--log-path",
            str(workspace / "logs"),
            "--select",
            "+mart_multi_market_ic_monthly",
            "+mart_multi_market_ic_partners",
            "--indirect-selection",
            "cautious",
            *(["--full-refresh"] if config.full_refresh else []),
            "--vars",
            json.dumps(
                {
                    "multi_market_end_date": f"{config.end[:4]}-{config.end[4:]}-01",
                    "multi_market_refresh_periods": months,
                }
            ),
        ],
        check=True,
        env={
            **os.environ,
            "DBT_PROJECT": config.settings.project,
            "DBT_RAW_PROJECT": config.raw_project,
            "DBT_RAW_DATASET": config.raw_dataset,
            "TRADE_BQ_DATASET": config.settings.dataset,
            "TRADE_BQ_LOCATION": config.settings.location,
        },
    )


def export_json_snapshot(config: PipelineConfig, build: dict[str, str]) -> dict[str, Any]:
    settings = config.settings
    reader = SnapshotReader(settings)
    raw = reader.read(settings.first_month, settings.after_last_month)
    with writer_lock(config.output.parent / "publish.lock"):
        result = publish_snapshot(
            raw,
            config.output,
            settings.first_month,
            settings.after_last_month,
            build=build,
            jobs=reader.jobs,
        )
        stage_snapshot(config.output, config.frontend_data)
    return result


def batch_scope(config: PipelineConfig) -> dict[str, Any]:
    return {
        "start": config.start,
        "end": config.end,
        "reporters": list(config.reporters),
        "refresh": config.refresh,
        "raw_project": config.raw_project,
        "raw_dataset": config.raw_dataset,
        "project": config.settings.project,
        "dataset": config.settings.dataset,
        "location": config.settings.location,
        "raw_prefix": config.raw_prefix,
        "full_refresh": config.full_refresh,
    }


def artifact_store(config: PipelineConfig) -> Artifacts:
    if not config.run_id:
        raise ValueError("stage execution requires --run-id")
    return Artifacts(config.raw_bucket, f"{config.artifact_prefix}/{config.run_id}")


def read_stage(store: Artifacts, uri: str, stage: str, config: PipelineConfig) -> dict[str, Any]:
    if uri != store.uri(f"{stage}.json"):
        raise ValueError("upstream artifact belongs to a different run or stage")
    record = store.read(uri)
    if record["scope"] != batch_scope(config):
        raise ValueError("stage settings differ from upstream settings")
    return record


def raw_watermark(config: PipelineConfig) -> str:
    from google.cloud import bigquery

    client = bigquery.Client(project=config.raw_project, location=config.settings.location)
    job = client.query(
        f"SELECT COUNT(*) n, MAX(event_at) latest FROM "
        f"`{config.raw_project}.{config.raw_dataset}.audit_ingestion_runs` WHERE status='success'",
        location=config.settings.location,
        job_config=bigquery.QueryJobConfig(
            maximum_bytes_billed=config.settings.maximum_bytes_billed
        ),
    )
    row = next(iter(job.result(timeout=180)))
    return f"{row['n']}:{row['latest']}"


def extract(config: PipelineConfig) -> str:
    store = artifact_store(config)
    scope = batch_scope(config)
    previous = store.optional("extract.json")
    if previous is not None:
        read_stage(store, store.uri("extract.json"), "extract", config)
        return store.uri("extract.json")
    progress = store.optional("extract-progress.json") or {
        "scope": scope,
        "sources": [],
        "completed": [],
        "unavailable": [],
    }
    if progress["scope"] != scope:
        raise ValueError("run id already used with different settings")
    with tempfile.TemporaryDirectory(prefix="trade-extract-") as directory:
        root = Path(directory)
        # Reconstruct validated Raw from S3, never from another worker's disk.
        paginator = store.client.get_paginator("list_objects_v2")
        prefix = config.raw_prefix.strip("/") + "/"
        for page in paginator.paginate(Bucket=config.raw_bucket, Prefix=prefix + "v3/"):
            for item in page.get("Contents", []):
                key = item["Key"]
                if not key.endswith("/manifest.json"):
                    continue
                payload = store.get(f"s3://{config.raw_bucket}/{key}")
                manifest = json.loads(payload)
                if not (config.start <= manifest["period"] <= config.end):
                    continue
                if int(manifest["request_parameters"]["reporterCode"]) not in config.reporters:
                    continue
                relative = key.removeprefix(prefix)
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
                target.with_name("data.ndjson").write_bytes(
                    store.get(
                        f"s3://{config.raw_bucket}/{key.removesuffix('manifest.json')}data.ndjson"
                    )
                )
        storage = S3Storage(bucket=config.raw_bucket, client=store.client, prefix=config.raw_prefix)
        remote = {item["identity"]: item for item in progress["sources"]}
        completed = set(progress["completed"])

        def persist(existing: dict[str, Any], identities: list[str]) -> None:
            for identity in identities:
                if identity in existing:
                    source = existing[identity]
                    saved = storage.write(source["path"])
                    remote[identity] = {
                        "identity": identity,
                        "data_uri": saved.data_uri,
                        "manifest_uri": saved.manifest_uri,
                        "checksum": saved.checksum,
                        "revision": source["manifest"]["revision"],
                    }
                else:
                    progress["unavailable"].append(identity)
            completed.update(identities)
            progress.update(sources=list(remote.values()), completed=sorted(completed))
            store.write("extract-progress.json", progress)

        if config.sync_only:
            existing = scan_sources(config.root)
            selected = {
                k: v
                for k, v in existing.items()
                if config.start <= v["manifest"]["period"] <= config.end
                and int(v["manifest"]["request_parameters"]["reporterCode"]) in config.reporters
            }
            persist(selected, list(selected))
            batch = BatchResult(complete=True)
        else:
            batch = run_batch(
                root,
                months=config.months,
                reporters=config.reporters,
                api_key=config.api_key,
                max_requests=config.max_requests,
                refresh=config.refresh,
                completed=completed,
                on_group=persist,
            )
        if not batch.complete:
            raise IncompleteExtraction("request budget exhausted; resume with the same run id")
        if not remote:
            raise ValueError("no accepted sources in requested range")
        return store.write(
            "extract.json",
            {
                **progress,
                "requests": batch.requests,
                "complete": True,
            },
        )


class IncompleteExtraction(ValueError):
    """Sources are durable, but extraction has not finished."""


def load(config: PipelineConfig, upstream: str) -> str:
    store = artifact_store(config)
    record = read_stage(store, upstream, "extract", config)
    loaded = load_bigquery(record["sources"], config)
    return store.write(
        "load.json",
        {
            "scope": batch_scope(config),
            **loaded,
            "extract": upstream,
            "watermark": raw_watermark(config),
        },
    )


def transform(config: PipelineConfig, upstream: str) -> str:
    store = artifact_store(config)
    record = read_stage(store, upstream, "load", config)
    attempt = uuid.uuid4().hex
    store.write("transform-attempt.json", {"attempt": attempt})
    before = raw_watermark(config)
    with tempfile.TemporaryDirectory(prefix="trade-dbt-") as directory:
        workspace = Path(directory)
        try:
            run_dbt_build(config, record["months"], workspace)
            build = validate_build(workspace / "target", config.settings)
        finally:
            # Diagnostic artifacts never constitute a successful handoff.
            store.upload_tree(workspace, f"dbt/{attempt}")
        if before != raw_watermark(config):
            raise ValueError("Raw changed during dbt build; rerun transform")
        for name in ("manifest.json", "run_results.json"):
            store.put(f"build/{attempt}/{name}", (workspace / "target" / name).read_bytes())
        return store.write(
            "transform.json",
            {
                "scope": batch_scope(config),
                "watermark": before,
                "attempt": attempt,
                "build": build,
                "artifacts": {
                    name: store.uri(f"build/{attempt}/{name}")
                    for name in ("manifest.json", "run_results.json")
                },
            },
        )


def publish(config: PipelineConfig, upstream: str) -> str:
    store = artifact_store(config)
    record = read_stage(store, upstream, "transform", config)
    if store.read(store.uri("transform-attempt.json"))["attempt"] != record["attempt"]:
        raise ValueError("latest transform attempt did not succeed; rerun transform")
    if raw_watermark(config) != record["watermark"]:
        raise ValueError("Raw changed after dbt build; rerun transform")
    with tempfile.TemporaryDirectory(prefix="trade-publish-") as directory:
        workspace = Path(directory)
        artifacts = workspace / "dbt"
        artifacts.mkdir()
        for name in ("manifest.json", "run_results.json"):
            (artifacts / name).write_bytes(store.get(record["artifacts"][name]))
        build = validate_build(artifacts, config.settings)
        if build != record["build"]:
            raise ValueError("dbt evidence differs from successful transform")
        frontend = workspace / "frontend"
        shutil.copytree(
            ROOT / "frontend",
            frontend,
            ignore=shutil.ignore_patterns("dist", "node_modules", ".dist-*"),
        )
        local = replace(
            config, output=workspace / "snapshot", frontend_data=frontend / "public/data"
        )
        result = export_json_snapshot(local, build)
        subprocess.run(["node", str(frontend / "build.mjs")], check=True)
        if raw_watermark(config) != record["watermark"]:
            raise ValueError("Raw changed during publish; rerun transform")
        release = f"releases/{result['snapshot_id']}"
        store.upload_tree(local.output, f"{release}/snapshot")
        store.upload_tree(frontend / "dist", f"{release}/website")
        return store.write(
            "publish.json",
            {
                "scope": batch_scope(config),
                "snapshot_id": result["snapshot_id"],
                "snapshot": store.uri(f"{release}/snapshot"),
                "website": store.uri(f"{release}/website"),
            },
        )


def run_pipeline(config: PipelineConfig) -> dict[str, Any]:
    if config.extract_only:
        batch = run_batch(
            config.root,
            months=config.months,
            api_key=config.api_key,
            reporters=config.reporters,
            max_requests=config.max_requests,
            refresh=config.refresh,
        )
        return {
            "complete": batch.complete,
            "requests": batch.requests,
            "unavailable": batch.unavailable,
            "status": "extracted" if batch.complete else "incomplete",
        }
    config = replace(config, run_id=config.run_id or uuid.uuid4().hex)
    print(json.dumps({"run_id": config.run_id}), flush=True)
    with writer_lock(config.root / "pipeline.lock"):
        uri = extract(config)
        uri = load(config, uri)
        uri = transform(config, uri)
        uri = publish(config, uri)
    return {"complete": True, "status": "success", "artifact_uri": uri, "run_id": config.run_id}


def main() -> int:
    load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="201601")
    parser.add_argument("--end", required=True)
    parser.add_argument("--root", type=Path, default=ROOT / "data/multi-market")
    parser.add_argument("--reporters", type=int, nargs="+", default=list(MARKETS))
    parser.add_argument("--max-requests", type=int, default=100)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--full-refresh", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--extract-only", action="store_true")
    mode.add_argument("--sync-only", action="store_true")
    parser.add_argument(
        "--run-id", default="", help="stable batch id; required for stage execution"
    )
    parser.add_argument("--artifact-prefix", default="_pipeline")
    parser.add_argument("--raw-prefix", default="un_comtrade")
    parser.add_argument("--stage", choices=("extract", "load", "transform", "publish"))
    parser.add_argument("--upstream", help="successful upstream S3 artifact URI")
    args = vars(parser.parse_args())
    stage, upstream = args.pop("stage"), args.pop("upstream")
    args["reporters"] = tuple(args["reporters"])
    try:
        config = PipelineConfig(**args)
        if upstream and stage in (None, "extract"):
            raise ValueError("--upstream requires load, transform or publish stage")
        if stage:
            if config.extract_only or (config.sync_only and stage != "extract"):
                raise ValueError("legacy modes cannot be combined with this stage")
            if stage == "extract":
                uri = extract(config)
            else:
                if not upstream:
                    raise ValueError("stage requires --upstream")
                uri = {"load": load, "transform": transform, "publish": publish}[stage](
                    config, upstream
                )
            result = {"complete": True, "artifact_uri": uri}
        else:
            result = run_pipeline(config)
        print(json.dumps(result), flush=True)
        return 0 if result["complete"] else INCOMPLETE_EXIT_CODE
    except IncompleteExtraction as error:
        print(json.dumps({"complete": False, "error": str(error)}), flush=True)
        return INCOMPLETE_EXIT_CODE
    except Exception as error:
        from trade_analytics.errors import exit_for_error

        return exit_for_error(error)


if __name__ == "__main__":
    raise SystemExit(main())
