"""Run bounded multi-market extraction, verified cloud loading, and one dbt build."""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIPELINE_STATE_PATH: Path | None = None
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))


def load_environment() -> None:
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value.strip().strip("\"'"))


def sync(root: Path, limit: int) -> dict:
    from collections import defaultdict
    from concurrent.futures import ThreadPoolExecutor

    import boto3
    from google.cloud import bigquery

    from trade_analytics.ingestion.manifest import Manifest, artifact_partition
    from trade_analytics.ingestion.paths import (
        portable_checkpoints,
        relative_artifact_path,
        resolve_artifact,
    )
    from trade_analytics.ingestion.queries import ComtradeQuery
    from trade_analytics.ingestion.s3_storage import S3Storage
    from trade_analytics.ingestion.schemas import TradeRecord
    from trade_analytics.ingestion.service import IngestionDataset
    from trade_analytics.warehouse.batch_loader import BatchRawLoader
    from trade_analytics.warehouse.source_validation import verify
    from trade_analytics.warehouse.writer_lock import writer_lock

    ledger = json.loads((root / "batch-ledger.json").read_text())
    s3 = boto3.client("s3")
    client = bigquery.Client(
        project=os.environ["DBT_RAW_PROJECT"],
        location=os.environ.get("TRADE_BQ_LOCATION", "asia-northeast1"),
    )
    if limit < 1:
        raise ValueError("source limit must be positive")
    cloud_path = root / "cloud-ledger.json"
    target = {key: os.environ[key] for key in ("RAW_BUCKET", "DBT_RAW_PROJECT", "DBT_RAW_DATASET")}
    cloud = (
        json.loads(cloud_path.read_text())
        if cloud_path.exists()
        else {"target": target, "sources": {}}
    )
    if cloud["target"] != target:
        raise ValueError("cloud checkpoint belongs to a different target")
    cloud["sources"] = portable_checkpoints(cloud["sources"])
    grouped = defaultdict(list)
    for identity, entry in ledger.items():
        if entry["status"] == "success":
            path = resolve_artifact(root, entry["data_path"])
            manifest = json.loads(path.with_name("manifest.json").read_bytes())
            from trade_analytics.ingestion.manifest import checksum

            if checksum(path.read_bytes()) != manifest["checksum"]:
                raise ValueError("source checksum mismatch")
            if cloud["sources"].get(relative_artifact_path(path).as_posix()) == {
                "data": manifest["checksum"],
                "manifest": checksum(path.with_name("manifest.json").read_bytes()),
            }:
                continue
            grouped[identity.split("/")[2]].append(entry)
    loaded = 0
    refreshed_periods = []

    def upload(entry: dict) -> dict:
        path = resolve_artifact(root, entry["data_path"])
        data, manifest_bytes = path.read_bytes(), path.with_name("manifest.json").read_bytes()
        manifest = Manifest.model_validate_json(manifest_bytes)
        query = ComtradeQuery.model_validate(
            dict(
                period=manifest.period,
                reporter_code=manifest.request_parameters["reporterCode"],
                cmd_code=manifest.cmd_code,
                query_type=manifest.query_type,
                expected_hs_version=manifest.hs_version,
                revision=manifest.revision,
            )
        )
        uri = f"s3://{os.environ['RAW_BUCKET']}/un_comtrade/{artifact_partition(query)}/data.ndjson"
        source = verify(data, manifest_bytes, uri)
        rows = tuple(TradeRecord.model_validate_json(line) for line in data.splitlines())
        S3Storage(
            bucket=os.environ["RAW_BUCKET"], client=s3, clock=lambda: manifest.ingested_at
        ).write(IngestionDataset(query=query, rows=rows))
        return source

    with writer_lock(ROOT / "data/pipeline.lock"):
        loader = BatchRawLoader(client, s3)
        for month, entries in sorted(grouped.items()):
            if loaded >= limit:
                break
            selected = entries[: limit - loaded]
            with ThreadPoolExecutor(max_workers=4) as executor:
                sources = list(executor.map(upload, selected))
            result = loader.load_month(month, sources)
            for entry, source in zip(selected, sources, strict=True):
                cloud["sources"][relative_artifact_path(entry["data_path"]).as_posix()] = {
                    "data": source["manifest"]["checksum"],
                    "manifest": checksum(
                        resolve_artifact(root, entry["data_path"])
                        .with_name("manifest.json")
                        .read_bytes()
                    ),
                }
            temporary = cloud_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(cloud, indent=2) + "\n")
            temporary.replace(cloud_path)
            refreshed_periods.append(month)
            loaded += len(sources)
            print(json.dumps(result), flush=True)
    return {
        "sources_checked": loaded,
        "periods": refreshed_periods,
        "remaining": sum(map(len, grouped.values())) - loaded,
    }


def main() -> None:
    global PIPELINE_STATE_PATH
    load_environment()
    from trade_analytics.ingestion.multi_market import MARKETS, run_batch

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="201601")
    parser.add_argument("--end", required=True)
    parser.add_argument("--root", type=Path, default=ROOT / "data/multi-market")
    parser.add_argument("--max-requests", type=int, default=100)
    parser.add_argument("--max-sources", type=int, default=100)
    parser.add_argument("--sync-only", action="store_true")
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--complete-backfill", action="store_true")
    parser.add_argument("--full-refresh", action="store_true")
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--require-row-target", action="store_true")
    parser.add_argument("--retry-unavailable", action="store_true")
    args = parser.parse_args()
    if args.publish and not args.build:
        parser.error("--publish requires --build")
    if args.complete_backfill and (args.sync_only or not args.build or not args.publish):
        parser.error("--complete-backfill requires ingestion, --build and --publish")
    state_path = args.state_file or args.root / "pipeline-state.json"
    if not args.complete_backfill and args.state_file is None and state_path.exists():
        previous_state = json.loads(state_path.read_text())
        if previous_state.get("history_complete") is True:
            state_path = args.root / "refresh-state.json"
    PIPELINE_STATE_PATH = state_path
    args.root.mkdir(parents=True, exist_ok=True)
    history_complete = args.complete_backfill
    if not history_complete:
        try:
            history = json.loads((args.root / "pipeline-state.json").read_text())
            history_complete = (
                history.get("stage") == "complete" and history.get("history_complete") is True
            )
        except (ValueError, OSError):
            pass

    def state(stage: str, **details) -> None:
        from datetime import UTC

        temporary = state_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {"stage": stage, "updated_at": datetime.now(UTC).isoformat(), **details}, indent=2
            )
            + "\n"
        )
        temporary.replace(state_path)

    if not args.sync_only:
        import time

        from trade_analytics.ingestion.exceptions import ComtradeTransientError
        from trade_analytics.warehouse.writer_lock import WriterBusyError

        while True:
            try:
                state("ingesting")
                result = run_batch(
                    args.root,
                    start="201601" if args.retry_unavailable else args.start,
                    end=args.end,
                    reporters=list(MARKETS),
                    max_requests=args.max_requests,
                    recent_from=args.start if args.retry_unavailable else None,
                    refresh_recent=args.retry_unavailable,
                )
                print(json.dumps(result), flush=True)
                if result["complete"] or not args.complete_backfill:
                    break
            except WriterBusyError:
                if not args.complete_backfill:
                    raise
                state("waiting_for_ingestion")
                time.sleep(10)
            except ComtradeTransientError:
                if not args.complete_backfill:
                    raise
                state("waiting_for_api")
                time.sleep(60)
    state("loading")
    sync_result = sync(args.root, args.max_sources)
    print(json.dumps(sync_result), flush=True)
    if (args.complete_backfill or args.publish) and sync_result["remaining"]:
        raise ValueError(
            "source limit was too small to load all accepted sources before publication"
        )
    if args.publish and not args.build:
        parser.error("--publish requires --build")
    if args.build:
        state("building")
        end = datetime.strptime(args.end, "%Y%m").strftime("%Y-%m-01")
        executable = os.environ.get("TRADE_DBT_EXECUTABLE", str(ROOT / ".venv-dbt/bin/dbt"))
        subprocess.run(
            [
                executable,
                "build",
                "--project-dir",
                str(ROOT / "dbt"),
                "--profiles-dir",
                str(ROOT / "dbt"),
                "--select",
                "+mart_multi_market_ic_monthly",
                "+mart_multi_market_ic_partners",
                "--indirect-selection",
                "cautious",
                *(["--full-refresh"] if args.full_refresh else []),
                "--vars",
                json.dumps(
                    {
                        "multi_market_end_date": end,
                        "multi_market_refresh_periods": sync_result["periods"],
                    }
                ),
            ],
            check=True,
        )
    if args.publish:
        state("publishing")
        from datetime import date

        from trade_analytics.warehouse.read_settings import next_month

        end_exclusive = next_month(date(int(args.end[:4]), int(args.end[4:]), 1)).isoformat()
        environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        subprocess.run(
            [
                sys.executable,
                "-m",
                "trade_analytics.export.cli",
                "--multi-market",
                *(
                    ["--require-row-target"]
                    if args.complete_backfill or args.require_row_target
                    else []
                ),
                "--start-month",
                "2016-01-01",
                "--end-exclusive",
                end_exclusive,
                "--dbt-artifacts",
                str(ROOT / "dbt/target"),
                "--output-dir",
                str(ROOT / "data/frontend-v2"),
            ],
            check=True,
            env=environment,
        )
        from trade_analytics.export.website import build_website

        release = build_website(ROOT / "data/frontend-v2", ROOT / "frontend", ROOT / "data/website")
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/build_standalone.py"),
                "--website-dir",
                release["directory"],
                "--output",
                str(ROOT / "data/website/index.html"),
            ],
            check=True,
        )
    state(
        "complete" if history_complete else "preview_ready",
        history_complete=history_complete,
    )
    print(json.dumps({"status": "success"}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        if PIPELINE_STATE_PATH is not None:
            payload = json.loads(PIPELINE_STATE_PATH.read_text())
            payload.update(stage="failed", error_type=type(error).__name__)
            PIPELINE_STATE_PATH.write_text(json.dumps(payload, indent=2) + "\n")
        from scripts.pipeline_exit import exit_for_error

        raise SystemExit(exit_for_error(error)) from error
