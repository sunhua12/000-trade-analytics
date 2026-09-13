import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from trade_analytics.ingestion.exceptions import StorageConflictError
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

    expected_dir = (
        tmp_path
        / "v2/hs_version=H6/cmd_code=8542/period=202401/query_type=partner_detail/revision=1"
    )
    assert stored.data_path == expected_dir / "data.ndjson"
    assert stored.manifest_path == expected_dir / "manifest.json"
    assert stored.data_path.read_bytes() == serialize_ndjson(dataset)
    manifest = json.loads(stored.manifest_path.read_text())
    assert manifest["row_count"] == 2
    assert manifest["primary_value_sum"] == "300"
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

    monkeypatch.setattr(os, "replace", recording_replace)

    LocalStorage(root=tmp_path, clock=lambda: FIXED_TIME).write(partner_dataset(preview_payload))

    assert [destination.name for _, destination in replacements] == [
        "data.ndjson",
        "manifest.json",
    ]
    assert all(source != destination for source, destination in replacements)
    assert not list(tmp_path.rglob("*.tmp"))


def test_local_rerun_preserves_bytes_and_timestamps(
    tmp_path: Path,
    preview_payload: dict[str, Any],
) -> None:
    dataset = partner_dataset(preview_payload)
    storage = LocalStorage(tmp_path)
    first = storage.write(dataset)
    paths = [first.data_path, first.manifest_path]
    before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths]
    assert storage.write(dataset).status == "already_exists"
    assert [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths] == before


@pytest.mark.parametrize("missing", ["data", "manifest"])
def test_local_partial_recovery_only_writes_missing_file(
    tmp_path: Path,
    preview_payload: dict[str, Any],
    missing: str,
) -> None:
    dataset = partner_dataset(preview_payload)
    storage = LocalStorage(tmp_path)
    first = storage.write(dataset)
    lost = first.data_path if missing == "data" else first.manifest_path
    kept = first.manifest_path if missing == "data" else first.data_path
    before = kept.read_bytes(), kept.stat().st_mtime_ns
    lost.unlink()
    assert storage.write(dataset).status == "success"
    assert lost.exists()
    assert (kept.read_bytes(), kept.stat().st_mtime_ns) == before


@pytest.mark.parametrize("lone", [False, True])
@pytest.mark.parametrize(
    "field",
    [
        "period",
        "cmd_code",
        "revision",
        "row_count",
        "primary_value_sum",
        "request_parameters",
        "schema_version",
        "source",
    ],
)
def test_local_manifest_identity_conflicts_do_not_write(
    tmp_path: Path,
    preview_payload: dict[str, Any],
    field: str,
    lone: bool,
) -> None:
    dataset = partner_dataset(preview_payload)
    storage = LocalStorage(tmp_path)
    first = storage.write(dataset)
    payload = json.loads(first.manifest_path.read_text())
    payload[field] = (
        {} if field == "request_parameters" else 99 if field in {"revision", "row_count"} else "999"
    )
    first.manifest_path.write_text(json.dumps(payload))
    if lone:
        first.data_path.unlink()
    before = {p.name: p.read_bytes() for p in first.data_path.parent.iterdir()}
    with pytest.raises(StorageConflictError):
        storage.write(dataset)
    assert {p.name: p.read_bytes() for p in first.data_path.parent.iterdir()} == before


def test_local_changed_content_requires_new_revision_and_preserves_legacy(
    tmp_path: Path,
    preview_payload: dict[str, Any],
) -> None:
    legacy = tmp_path / "period=202401/query_type=partner_detail/data.ndjson"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy evidence")
    dataset = partner_dataset(preview_payload)
    storage = LocalStorage(tmp_path)
    first = storage.write(dataset)
    changed = replace(
        dataset,
        rows=(
            dataset.rows[0].model_copy(update={"primary_value": Decimal("101")}),
            *dataset.rows[1:],
        ),
    )
    with pytest.raises(StorageConflictError):
        storage.write(changed)
    assert first.data_path.read_bytes() == serialize_ndjson(dataset)
    # The same content conflict must also be rejected when only data survived.
    first.manifest_path.unlink()
    with pytest.raises(StorageConflictError):
        storage.write(changed)
    assert not first.manifest_path.exists()
    revised = replace(changed, query=ComtradeQuery(query_type=QueryType.PARTNER_DETAIL, revision=2))
    second = storage.write(revised)
    assert "revision=2" in str(second.data_path)
    assert first.data_path.read_bytes() == serialize_ndjson(dataset)
    assert legacy.read_bytes() == b"legacy evidence"


def test_local_distinct_commodities_have_distinct_paths(
    tmp_path: Path,
    preview_payload: dict[str, Any],
) -> None:
    dataset = partner_dataset(preview_payload)
    other = replace(
        dataset,
        query=ComtradeQuery(query_type=QueryType.PARTNER_DETAIL, cmd_code="854231"),
        rows=tuple(row.model_copy(update={"cmd_code": "854231"}) for row in dataset.rows),
    )
    storage = LocalStorage(tmp_path)
    assert storage.write(dataset).data_path != storage.write(other).data_path


def test_storage_does_not_return_success_when_replace_fails(
    tmp_path: Path,
    preview_payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_replace(source: str | Path, destination: str | Path) -> None:
        del source, destination
        raise OSError("disk unavailable")

    monkeypatch.setattr(os, "replace", failing_replace)
    storage = LocalStorage(root=tmp_path, clock=lambda: FIXED_TIME)

    with pytest.raises(OSError, match="disk unavailable"):
        storage.write(partner_dataset(preview_payload))

    assert not list(tmp_path.rglob("*.tmp"))


def test_storage_removes_data_temp_when_manifest_temp_write_fails(
    tmp_path: Path,
    preview_payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writes = 0

    def fail_second_temporary_write(directory: Path, content: bytes) -> Path:
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("manifest temp write failed")
        temporary = directory / ".data.tmp"
        temporary.write_bytes(content)
        return temporary

    monkeypatch.setattr(
        LocalStorage,
        "_write_temporary",
        staticmethod(fail_second_temporary_write),
    )
    storage = LocalStorage(root=tmp_path, clock=lambda: FIXED_TIME)

    with pytest.raises(OSError, match="manifest temp write failed"):
        storage.write(partner_dataset(preview_payload))

    assert not list(tmp_path.rglob("*.tmp"))
