"""Batch publication boundaries and static release failure behavior."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts import run_batch
from trade_analytics.export.schemas import MonthlyDocument, PartnerDocument
from trade_analytics.export.service import publish_snapshot
from trade_analytics.export.website import build_website
from trade_analytics.warehouse.read_settings import Settings
from trade_analytics.warehouse.writer_lock import WriterBusyError, writer_lock

ROOT = Path(__file__).resolve().parents[2]
# Legacy batch tests use v1 regression data, never the production v2 snapshot.
FIXTURES = ROOT / "frontend/tests/fixtures"


@pytest.fixture
def raw_snapshot() -> dict:
    monthly = MonthlyDocument.model_validate_json((FIXTURES / "monthly.json").read_bytes())
    partners = PartnerDocument.model_validate_json((FIXTURES / "partners.json").read_bytes())
    return {
        "monthly": [row.model_dump() for row in monthly.rows],
        "partners": [row.model_dump() for row in partners.rows],
    }


def item(period: str) -> dict:
    return {
        "period": period,
        "run_id": "test-" + period,
        "revisions": {"partner_detail": 1, "world_total": 1},
    }


def test_batch_serializes_all_months_then_exports_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw_snapshot: dict
) -> None:
    monkeypatch.setattr(run_batch, "ROOT", tmp_path)
    monkeypatch.setattr(run_batch.Settings, "from_env", lambda: Settings("trade-analytics-508604"))
    execute = Mock(return_value={"status": "success"})
    reader = Mock(jobs=[])
    reader.read.return_value = raw_snapshot
    create_reader = Mock(return_value=reader)
    build_site = Mock(return_value={"status": "built"})
    monkeypatch.setattr(run_batch, "execute", execute)
    monkeypatch.setattr(run_batch, "validate_build", lambda *args: {})
    monkeypatch.setattr(run_batch, "SnapshotReader", create_reader)
    monkeypatch.setattr(run_batch, "build_website", build_site)
    result = run_batch.run_batch(
        {"selected": [item("202412"), item("202411")]}, Path("dbt"), tmp_path / "data"
    )
    assert result["processed_months"] == ["202411", "202412"]
    assert [(call.args[0].period, call.args[0].step) for call in execute.call_args_list] == [
        (period, step)
        for period in ("202411", "202412")
        for step in ("ingest", "ingest", "load", "load", "build")
    ]
    reader.read.assert_called_once()
    build_site.assert_called_once()
    assert (tmp_path / "data/frontend/current.json").is_file()


def test_empty_or_failed_batch_cannot_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = Mock(side_effect=AssertionError("must not query or publish"))
    monkeypatch.setattr(run_batch, "ROOT", tmp_path)
    monkeypatch.setattr(run_batch, "SnapshotReader", reader)
    assert run_batch.run_batch({"selected": []}, Path("dbt"), tmp_path)["exported"] is False
    monkeypatch.setattr(run_batch, "execute", Mock(side_effect=ValueError("load failed")))
    with pytest.raises(ValueError, match="load failed"):
        run_batch.run_batch({"items": [item("202412")]}, Path("dbt"), tmp_path)
    assert not (tmp_path / "frontend/current.json").exists()
    reader.assert_not_called()
    with pytest.raises(ValueError, match="duplicate"):
        run_batch.ready_items({"selected": [item("202412"), item("202412")]})


def test_writer_lock_blocks_another_writer_and_releases_on_failure(tmp_path: Path) -> None:
    lock = tmp_path / "pipeline.lock"
    with pytest.raises(ValueError, match="simulated"), writer_lock(lock):
        with pytest.raises(WriterBusyError), writer_lock(lock):
            pytest.fail("second writer acquired the lock")
        raise ValueError("simulated failure")
    with writer_lock(lock):
        pass


def test_website_build_keeps_last_good_release_on_failure(
    tmp_path: Path, raw_snapshot: dict
) -> None:
    from datetime import date

    snapshots = tmp_path / "snapshots"
    publish_snapshot(raw_snapshot, snapshots, date(2023, 1, 1), date(2025, 1, 1), build={}, jobs=[])
    website = tmp_path / "website"
    result = build_website(snapshots, ROOT / "frontend", website)
    current = (website / "current.json").read_bytes()
    folder = Path(result["directory"])
    assert (folder / "index.html").is_file()
    assert (
        json.loads((folder / "data/manifest.json").read_bytes())["snapshot_id"]
        == result["snapshot_id"]
    )
    assert not (folder / "audit").exists()
    assert not (folder / ".env").exists()
    with pytest.raises(FileNotFoundError):
        build_website(snapshots, tmp_path / "missing-frontend", website)
    assert (website / "current.json").read_bytes() == current
    assert not list(website.glob(".website-*"))
