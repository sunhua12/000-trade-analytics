"""Revision, source replacement and warehouse race guards."""

import json
from datetime import UTC, datetime

import pytest

from trade_analytics.ingestion.manifest import (
    artifact_partition,
    build_manifest,
    serialize_manifest,
    serialize_ndjson,
)
from trade_analytics.ingestion.queries import ComtradeQuery, QueryType
from trade_analytics.ingestion.schemas import ComtradeResponse
from trade_analytics.ingestion.service import validate_dataset
from trade_analytics.warehouse.loader import RawLoader, decision
from trade_analytics.warehouse.source_validation import verify


@pytest.fixture
def source(preview_payload):
    for row in preview_payload["data"]:
        row.update(cmdCode="854231", isOriginalClassification=True)
    query = ComtradeQuery(period="202401", cmd_code="854231", query_type=QueryType.PARTNER_DETAIL)
    dataset = validate_dataset(query, ComtradeResponse.model_validate(preview_payload))
    data = serialize_ndjson(dataset)
    manifest = build_manifest(dataset, data=data, ingested_at=datetime.now(UTC))
    return verify(
        data,
        serialize_manifest(manifest),
        f"s3://fixture/un_comtrade/{artifact_partition(query)}/data.ndjson",
    )


class Loader(RawLoader):
    def __init__(self, existing=None):
        super().__init__(None, project="fixture-project", raw_dataset="trade_fixture")
        self.existing = existing or []
        self.writes = []

    def query(self, sql, params):
        if sql.lstrip().startswith("SELECT"):
            return [] if "world_total" in sql else self.existing
        self.writes.append((sql, params))
        return []


def metadata(source):
    m = source["manifest"]
    return {
        "reporter_code": "842",
        "cmd_code": "854231",
        "hs_version": "H6",
        "revision": m["revision"],
        "checksum": m["checksum"],
        "row_count": m["row_count"],
        "revisions": 1,
        "checksums": 1,
    }


def test_revision_decisions():
    assert decision(None, 1, "a") == "load"
    old = {"revision": 2, "checksum": "a"}
    assert decision(old, 1, "a") == "stale_revision"
    assert decision(old, 2, "a") == "already_loaded"
    assert decision(old, 2, "b") == "conflict"
    assert decision(old, 3, "b") == "load"


def test_same_revision_is_metadata_only_and_does_not_write(source):
    loader = Loader([metadata(source)])
    assert loader.load_month("202401", [source])["status"] == "already_loaded"
    assert not loader.writes


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("revision", 2, "stale_revision"),
        ("checksum", "different", "conflict"),
        ("row_count", 999, "row count"),
    ],
)
def test_rejects_stale_conflicting_or_incomplete_existing(source, field, value, error):
    existing = {**metadata(source), field: value}
    loader = Loader([existing])
    with pytest.raises(ValueError, match=error):
        loader.load_month("202401", [source])
    assert not loader.writes


def test_new_revision_replaces_entire_source_in_guarded_transaction(source):
    old = {**metadata(source), "revision": 0, "checksum": "old", "row_count": 3}
    loader = Loader([old])
    assert loader.load_month("202401", [source])["status"] == "success"
    sql, params = loader.writes[0]
    assert sql.index("BEGIN TRANSACTION") < sql.index("DELETE FROM") < sql.index("INSERT INTO")
    assert sql.index("INSERT INTO") < sql.index("COMMIT TRANSACTION")
    assert "source changed during load" in sql
    assert "MERGE" not in sql and "snapshot_hash" not in sql and "EXCEPT DISTINCT" not in sql
    incoming = json.loads(params["rows"])
    assert {r["partner_code"] for r in incoming} == {"156", "410"}
    assert "490" not in {r["partner_code"] for r in incoming}


def test_duplicate_sources_rejected(source):
    with pytest.raises(ValueError, match="duplicate source"):
        Loader().load_month("202401", [source, source])
