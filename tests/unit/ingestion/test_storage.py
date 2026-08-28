import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import trade_analytics.ingestion.storage as storage_module
from trade_analytics.ingestion.manifest import serialize_ndjson
from trade_analytics.ingestion.queries import ComtradeQuery, QueryType
from trade_analytics.ingestion.schemas import ComtradeResponse
from trade_analytics.ingestion.service import IngestionDataset, IngestionService
from trade_analytics.ingestion.storage import LocalStorage

FIXED_TIME = datetime(2026, 8, 28, tzinfo=UTC)


class FakeClient:
    def __init__(self, response: ComtradeResponse) -> None:
        self.response = response

    def fetch(self, query: ComtradeQuery) -> ComtradeResponse:
        del query
        return self.response


def partner_dataset(preview_payload: dict[str, Any]) -> IngestionDataset:
    response = ComtradeResponse.model_validate(preview_payload)
    query = ComtradeQuery(
        period="202401",
        cmd_code="8542",
        query_type=QueryType.PARTNER_DETAIL,
    )
    return IngestionService(FakeClient(response)).fetch_dataset(query)


def test_storage_writes_expected_partitioned_paths(
    tmp_path: Path,
    preview_payload: dict[str, Any],
) -> None:
    dataset = partner_dataset(preview_payload)
    storage = LocalStorage(root=tmp_path, clock=lambda: FIXED_TIME)

    stored = storage.write(dataset)

    expected_dir = tmp_path / "period=202401" / "query_type=partner_detail"
    assert stored.data_path == expected_dir / "data.ndjson"
    assert stored.manifest_path == expected_dir / "manifest.json"
    assert stored.data_path.read_bytes() == serialize_ndjson(dataset)
    manifest = json.loads(stored.manifest_path.read_text())
    assert manifest["row_count"] == 2
    assert manifest["primary_value_sum"] == "300.0"
    assert manifest["ingested_at"] == "2026-08-28T00:00:00Z"
    assert stored.checksum == manifest["checksum"]


def test_storage_uses_temporary_files_before_atomic_replace(
    tmp_path: Path,
    preview_payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replacements: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def recording_replace(source: str | Path, destination: str | Path) -> None:
        replacements.append((Path(source), Path(destination)))
        real_replace(source, destination)

    monkeypatch.setattr(storage_module.os, "replace", recording_replace)

    LocalStorage(root=tmp_path, clock=lambda: FIXED_TIME).write(partner_dataset(preview_payload))

    assert [destination.name for _, destination in replacements] == [
        "data.ndjson",
        "manifest.json",
    ]
    assert all(source != destination for source, destination in replacements)
    assert not list(tmp_path.rglob("*.tmp"))


def test_storage_does_not_return_success_when_replace_fails(
    tmp_path: Path,
    preview_payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_replace(source: str | Path, destination: str | Path) -> None:
        del source, destination
        raise OSError("disk unavailable")

    monkeypatch.setattr(storage_module.os, "replace", failing_replace)
    storage = LocalStorage(root=tmp_path, clock=lambda: FIXED_TIME)

    with pytest.raises(OSError, match="disk unavailable"):
        storage.write(partner_dataset(preview_payload))

    assert not list(tmp_path.rglob("*.tmp"))
