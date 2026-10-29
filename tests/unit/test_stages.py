"""Durable handoffs across empty worker disks and stage failure boundaries."""

import json
import subprocess
from dataclasses import replace

import boto3
import pytest
import respx

from tests.unit.test_export import publish as fixture_publish
from tests.unit.test_export import snapshot  # noqa: F401
from tests.unit.test_ingestion import FakeS3
from tests.unit.test_multi_market import response_for
from trade_analytics import pipeline
from trade_analytics.config import PipelineConfig
from trade_analytics.export.website import stage_snapshot
from trade_analytics.ingestion import multi_market
from trade_analytics.ingestion.client import ComtradeClient


class RemoteS3(FakeS3):
    def get_paginator(self, operation):
        assert operation == "list_objects_v2"
        return self

    def paginate(self, *, Bucket, Prefix):
        yield {
            "Contents": [
                {"Key": key}
                for bucket, key in self.objects
                if bucket == Bucket and key.startswith(Prefix)
            ]
        }


@pytest.fixture
def stages(tmp_path, monkeypatch):
    monkeypatch.setenv("RAW_BUCKET", "fixture")
    monkeypatch.setenv("DBT_RAW_PROJECT", "fixture-project")
    monkeypatch.setenv("DBT_RAW_DATASET", "fixture_raw")
    monkeypatch.delenv("COMTRADE_API_KEY", raising=False)
    monkeypatch.setattr(multi_market, "PRODUCTS", {"854231": "processors"})
    monkeypatch.setattr(multi_market.time, "sleep", lambda _: None)
    s3 = RemoteS3()
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: s3)
    config = PipelineConfig(
        start="202401",
        end="202402",
        reporters=(842,),
        refresh=True,
        max_requests=1,
        run_id="test",
        root=tmp_path / "unused",
    )
    return config, s3


@respx.mock
def test_extract_resume_without_worker_disk(stages, preview_payload):
    config, s3 = stages
    route = respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(
        side_effect=lambda request: response_for(preview_payload, request)
    )
    with pytest.raises(pipeline.IncompleteExtraction):
        pipeline.extract(config)
    store = pipeline.artifact_store(config)
    assert store.optional("extract.json") is None
    assert len(store.read(store.uri("extract-progress.json"))["sources"]) == 2
    assert not config.root.exists()
    uri = pipeline.extract(config)
    assert len(route.calls) == 2
    assert [call.request.url.params["period"] for call in route.calls] == ["202401", "202402"]
    record = store.read(uri)
    assert len(record["sources"]) == 4
    assert pipeline.extract(config) == uri
    assert len(route.calls) == 2
    assert s3.objects


@respx.mock
def test_new_refresh_batch_creates_revision(stages, preview_payload):
    config, _ = stages
    config = replace(config, end="202401")
    route = respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(
        side_effect=lambda request: response_for(preview_payload, request)
    )
    pipeline.extract(config)
    route.mock(side_effect=lambda request: response_for(preview_payload, request, amount="999"))
    config = replace(config, run_id="new")
    record = pipeline.artifact_store(config).read(pipeline.extract(config))
    assert {item["revision"] for item in record["sources"]} == {2}


@respx.mock
def test_corrupt_remote_raw_blocks_load(stages, preview_payload, monkeypatch):
    config, s3 = stages
    config = replace(config, end="202401")
    respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(
        side_effect=lambda request: response_for(preview_payload, request)
    )
    upstream = pipeline.extract(config)
    source = pipeline.artifact_store(config).read(upstream)["sources"][0]
    s3.objects[("fixture", source["data_uri"].split("/", 3)[3])] = b"corrupt"
    from google.cloud import bigquery

    monkeypatch.setattr(bigquery, "Client", lambda **kwargs: None)
    with pytest.raises(ValueError, match="checksum"):
        pipeline.load(config, upstream)
    assert pipeline.artifact_store(config).optional("load.json") is None


def prepare_transform(config, monkeypatch):
    store = pipeline.artifact_store(config)
    uri = store.write("load.json", {"scope": pipeline.batch_scope(config), "months": ["202401"]})
    monkeypatch.setattr(pipeline, "raw_watermark", lambda _: "1:now")
    monkeypatch.setattr(pipeline, "validate_build", lambda *args: {"invocation_id": "fixture"})
    folders = []

    def dbt(config, months, workspace):
        folders.append(workspace)
        (workspace / "target").mkdir()
        for name in ("manifest.json", "run_results.json"):
            (workspace / "target" / name).write_text("{}")

    monkeypatch.setattr(pipeline, "run_dbt_build", dbt)
    return store, uri, folders


def test_transform_failure_invalidates_previous_success(stages, monkeypatch):
    config, _ = stages
    store, uri, folders = prepare_transform(config, monkeypatch)
    successful = pipeline.transform(config, uri)
    assert all(not folder.exists() for folder in folders)

    def fail(*args):
        raise subprocess.CalledProcessError(1, "dbt")

    monkeypatch.setattr(pipeline, "run_dbt_build", fail)
    with pytest.raises(subprocess.CalledProcessError):
        pipeline.transform(config, uri)
    with pytest.raises(ValueError, match="latest transform"):
        pipeline.publish(config, successful)
    assert store.optional("publish.json") is None


def test_publish_rejects_changed_raw(stages, monkeypatch):
    config, _ = stages
    _, uri, _ = prepare_transform(config, monkeypatch)
    transformed = pipeline.transform(config, uri)
    monkeypatch.setattr(pipeline, "raw_watermark", lambda _: "2:later")
    with pytest.raises(ValueError, match="Raw changed"):
        pipeline.publish(config, transformed)


def test_publish_build_and_s3_handoff_without_upstream_disk(stages, monkeypatch, snapshot):  # noqa: F811
    config, _ = stages
    store, uri, folders = prepare_transform(config, monkeypatch)
    transformed = pipeline.transform(config, uri)
    assert all(not folder.exists() for folder in folders)
    workspaces = []

    def export(local, build):
        assert build == {"invocation_id": "fixture"}
        workspaces.append(local.output.parent)
        result = fixture_publish(snapshot, local.output)
        stage_snapshot(local.output, local.frontend_data)
        return result

    monkeypatch.setattr(pipeline, "export_json_snapshot", export)
    published = store.read(pipeline.publish(config, transformed))
    website = published["website"]
    assert (
        json.loads(store.get(website + "/data/manifest.json"))["snapshot_id"]
        == published["snapshot_id"]
    )
    assert store.get(website + "/index.html")
    assert all(not folder.exists() for folder in workspaces)
    previous = store.read(store.uri("publish.json"))

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "node")

    monkeypatch.setattr(pipeline.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        pipeline.publish(config, transformed)
    assert store.read(store.uri("publish.json")) == previous


def test_stage_rejects_mismatched_run_and_settings(stages):
    config, _ = stages
    store = pipeline.artifact_store(config)
    uri = store.write("extract.json", {"scope": pipeline.batch_scope(config)})
    with pytest.raises(ValueError, match="different run"):
        pipeline.load(replace(config, run_id="other"), uri)
    with pytest.raises(ValueError, match="settings differ"):
        pipeline.load(replace(config, end="202401"), uri)


def test_publish_upload_failure_preserves_previous_completion(stages, monkeypatch, snapshot):  # noqa: F811
    config, s3 = stages
    store, uri, _ = prepare_transform(config, monkeypatch)
    transformed = pipeline.transform(config, uri)

    def export(local, build):
        result = fixture_publish(snapshot, local.output)
        stage_snapshot(local.output, local.frontend_data)
        return result

    monkeypatch.setattr(pipeline, "export_json_snapshot", export)
    first = store.read(pipeline.publish(config, transformed))
    original = s3.put_object

    def interrupted(**kwargs):
        if "/website/" in kwargs["Key"]:
            raise OSError("upload interrupted")
        return original(**kwargs)

    monkeypatch.setattr(s3, "put_object", interrupted)
    with pytest.raises(OSError, match="upload interrupted"):
        pipeline.publish(config, transformed)
    assert store.read(store.uri("publish.json")) == first


def test_transform_detects_raw_change_during_build(stages, monkeypatch):
    config, _ = stages
    store, uri, _ = prepare_transform(config, monkeypatch)
    values = iter(["1:old", "2:new"])
    monkeypatch.setattr(pipeline, "raw_watermark", lambda _: next(values))
    with pytest.raises(ValueError, match="Raw changed during"):
        pipeline.transform(config, uri)
    assert store.optional("transform.json") is None


@respx.mock
def test_non_refresh_batch_reuses_committed_s3_without_api(stages, preview_payload):
    config, _ = stages
    config = replace(config, end="202401")
    route = respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(
        side_effect=lambda request: response_for(preview_payload, request)
    )
    pipeline.extract(config)
    reused = replace(config, refresh=False, run_id="reuse")
    record = pipeline.artifact_store(reused).read(pipeline.extract(reused))
    assert len(record["sources"]) == 2 and record["requests"] == 0
    assert len(route.calls) == 1
