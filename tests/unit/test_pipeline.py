"""Pipeline gates, CLI exit codes, publication rollback and configuration."""

import json
from pathlib import Path

import httpx
import pytest

from tests.unit.test_export import publish, snapshot  # noqa: F401, F811
from trade_analytics import pipeline
from trade_analytics.config import PipelineConfig
from trade_analytics.export.website import stage_snapshot


@pytest.fixture
def config(tmp_path, monkeypatch):
    for key, value in {
        "RAW_BUCKET": "fixture",
        "DBT_RAW_PROJECT": "fixture-project",
        "DBT_RAW_DATASET": "trade_fixture",
    }.items():
        monkeypatch.setenv(key, value)
    return PipelineConfig(
        start="202401",
        end="202401",
        root=tmp_path / "raw",
        output=tmp_path / "snapshots",
        frontend_data=tmp_path / "public/data",
    )


def accepted():
    return [{"manifest": {"period": "202401", "request_parameters": {"reporterCode": 842}}}]


def test_successful_pipeline_order(config, monkeypatch):
    events = []
    for stage in ("extract", "load", "transform", "publish"):

        def execute(*args, stage=stage):
            events.append(stage)
            return stage

        monkeypatch.setattr(pipeline, stage, execute)
    assert pipeline.run_pipeline(config)["complete"]
    assert events == ["extract", "load", "transform", "publish"]


def test_incomplete_extraction_never_loads_or_publishes(config, monkeypatch):
    def fail(*args):
        raise pipeline.IncompleteExtraction("budget")

    monkeypatch.setattr(pipeline, "extract", fail)
    monkeypatch.setattr(pipeline, "load", lambda *args: pytest.fail("incomplete load"))
    with pytest.raises(pipeline.IncompleteExtraction):
        pipeline.run_pipeline(config)


def test_dbt_failure_does_not_export(config, monkeypatch):
    monkeypatch.setattr(pipeline, "extract", lambda *args: "extract")
    monkeypatch.setattr(pipeline, "load", lambda *args: "load")

    def fail(*args):
        raise RuntimeError("dbt failed")

    monkeypatch.setattr(pipeline, "transform", fail)
    monkeypatch.setattr(pipeline, "publish", lambda *args: pytest.fail("export after failure"))
    with pytest.raises(RuntimeError, match="dbt failed"):
        pipeline.run_pipeline(config)


def test_cli_incomplete_exit_code(monkeypatch):
    import sys

    monkeypatch.setattr(pipeline, "load_environment", lambda: None)
    monkeypatch.setattr(
        sys, "argv", ["trade-pipeline", "--start", "202401", "--end", "202401", "--extract-only"]
    )
    monkeypatch.setattr(pipeline, "run_pipeline", lambda config: {"complete": False})
    assert pipeline.main() == 2


def test_config_rejects_invalid_inputs(tmp_path):
    for kwargs in [
        {"max_requests": 0},
        {"reporters": (999,)},
        {"reporters": (842, 842)},
        {"sync_only": True},
    ]:
        with pytest.raises(ValueError):
            PipelineConfig(start="202401", end="202401", root=tmp_path, extract_only=True, **kwargs)


def test_stage_snapshot_rollback(snapshot, tmp_path, monkeypatch):  # noqa: F811
    root = tmp_path / "snapshots"
    publish(snapshot, root)
    destination = tmp_path / "public/data"
    stage_snapshot(root, destination)
    before = {p.name: p.read_bytes() for p in destination.iterdir()}
    original = Path.rename

    def fail_stage(self, target):
        if self.name.startswith(".data-") and not self.name.endswith("-backup"):
            raise OSError("stage failure")
        return original(self, target)

    monkeypatch.setattr(Path, "rename", fail_stage)
    with pytest.raises(OSError, match="stage failure"):
        stage_snapshot(root, destination)
    assert {p.name: p.read_bytes() for p in destination.iterdir()} == before


def test_mixed_snapshot_rejected_before_staging(snapshot, tmp_path):  # noqa: F811
    root = tmp_path / "snapshots"
    result = publish(snapshot, root)
    destination = tmp_path / "public/data"
    stage_snapshot(root, destination)
    before = (destination / "manifest.json").read_bytes()
    partner_path = Path(result["path"]) / "partners.json"
    raw = json.loads(partner_path.read_bytes())
    raw["snapshot_id"] = "0" * 32
    partner_path.write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        stage_snapshot(root, destination)
    assert (destination / "manifest.json").read_bytes() == before


@pytest.mark.parametrize(
    "error,code", [(ValueError("bad source"), 1), (httpx.ReadTimeout("timeout"), 75)]
)
def test_cli_error_exit_codes(monkeypatch, error, code):
    import sys

    monkeypatch.setattr(pipeline, "load_environment", lambda: None)
    monkeypatch.setattr(sys, "argv", ["pipeline", "--end", "202401", "--extract-only"])

    def fail(config):
        raise error

    monkeypatch.setattr(pipeline, "run_pipeline", fail)
    assert pipeline.main() == code


def test_dbt_command_keeps_quality_gate(config, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        pipeline.subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs))
    )
    pipeline.run_dbt_build(config, ["202401"], tmp_path)
    command, kwargs = calls[0]
    assert "build" in command and kwargs["check"] is True
    assert json.loads(command[-1])["multi_market_refresh_periods"] == ["202401"]


def test_writer_lock_covers_other_cli_processes(config):
    from trade_analytics.warehouse.writer_lock import WriterBusyError, writer_lock

    with writer_lock(config.root / "pipeline.lock"), pytest.raises(WriterBusyError):
        pipeline.run_pipeline(config)


def test_load_reads_back_s3_before_warehouse(config, preview_payload, monkeypatch):
    import boto3
    from google.cloud import bigquery

    from tests.unit.test_ingestion import FakeS3
    from trade_analytics.ingestion.manifest import artifact_partition
    from trade_analytics.ingestion.queries import ComtradeQuery, QueryType
    from trade_analytics.ingestion.s3_storage import S3Storage
    from trade_analytics.ingestion.schemas import ComtradeResponse
    from trade_analytics.ingestion.service import validate_dataset
    from trade_analytics.ingestion.storage import LocalStorage

    for row in preview_payload["data"]:
        row.update(cmdCode="854231", isOriginalClassification=True)
    query = ComtradeQuery(period="202401", cmd_code="854231", query_type=QueryType.PARTNER_DETAIL)
    LocalStorage(config.root).write(
        validate_dataset(query, ComtradeResponse.model_validate(preview_payload))
    )
    s3 = FakeS3()
    monkeypatch.setattr(boto3, "client", lambda *args: s3)
    monkeypatch.setattr(bigquery, "Client", lambda **kwargs: None)
    loaded = []

    class Loader:
        def __init__(self, *args, **kwargs):
            self.jobs = []

        def load_month(self, month, sources):
            loaded.extend(sources)
            return {"status": "success"}

    monkeypatch.setattr(pipeline, "RawLoader", Loader)
    path = next(config.root.rglob("data.ndjson"))
    stored = S3Storage(bucket="fixture", client=s3).write(path)
    sources = [
        {
            "data_uri": stored.data_uri,
            "manifest_uri": stored.manifest_uri,
            "checksum": stored.checksum,
            "revision": 1,
        }
    ]
    assert pipeline.load_bigquery(sources, config)["months"] == ["202401"]
    assert (
        loaded[0]["source_file"]
        == f"s3://fixture/un_comtrade/{artifact_partition(query)}/data.ndjson"
    )
    assert len(s3.puts) == 2
    assert loaded[0]["manifest"]["row_count"] == 2
    # Replay uses the same immutable S3 pair and remains eligible for warehouse metadata skip.
    pipeline.load_bigquery(sources, config)
    assert len(s3.puts) == 2


@pytest.mark.parametrize(
    "overrides",
    [
        {"end": "203101"},
        {"end": "202401", "raw_project": "bad`project"},
        {"end": "202401", "raw_dataset": "bad.dataset"},
    ],
)
def test_invalid_targets_and_export_range_fail_before_extract(monkeypatch, overrides):
    monkeypatch.setenv("RAW_BUCKET", "fixture")
    monkeypatch.setenv("DBT_RAW_PROJECT", overrides.get("raw_project", "fixture-project"))
    monkeypatch.setenv("DBT_RAW_DATASET", overrides.get("raw_dataset", "trade_fixture"))
    with pytest.raises(ValueError):
        PipelineConfig(start="201601", end=overrides["end"])
