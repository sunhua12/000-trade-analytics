"""JSON precision, calendar semantics, build gate, and last-good snapshot tests."""

import copy
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from trade_analytics.export import queries, service
from trade_analytics.export.v2 import MonthlyRowV2 as MonthlyRow
from trade_analytics.export.v2 import PartnerRowV2 as PartnerRow
from trade_analytics.export.v2 import verify_v2
from trade_analytics.warehouse.read_settings import Settings, next_month

START = date(2023, 1, 1)
END = date(2024, 2, 1)
AMOUNT = Decimal("9007199254740993.123456789")


@pytest.fixture
def snapshot() -> dict:
    monthly = []
    month = START
    while month < END:
        first, last = month == START, month == date(2024, 1, 1)
        monthly.append(
            {
                "month": month,
                "reporter_code": "842",
                "cmd_code": "854231",
                "hs_version": "H6",
                "world_value": AMOUNT if first or last else None,
                "previous_year_world_value": AMOUNT if last else None,
                "world_yoy": Decimal(0) if last else None,
                "country_value": AMOUNT if first else None,
                "country_count": 1 if first else 0,
                "country_coverage": Decimal(1) if first else None,
                "hhi": Decimal(10000) if first else None,
                "hhi_status": "ok" if first else "no_countries" if last else "missing_world",
                "has_world": first or last,
                "has_countries": first,
            }
        )
        month = next_month(month)
    return {
        "monthly": monthly,
        "partners": [
            {
                "month": START,
                "reporter_code": "842",
                "cmd_code": "854231",
                "hs_version": "H6",
                "partner_code": "004",
                "source_name": "Example",
                "map_iso3": None,
                "import_value": AMOUNT,
                "market_share": Decimal(1),
                "market_share_status": "ok",
                "previous_month_value": None,
                "previous_year_value": None,
                "mom": None,
                "yoy": None,
            }
        ],
    }


def publish(snapshot: dict, output: Path) -> dict:
    return service.publish_snapshot(snapshot, output, START, END, build={}, jobs=[])


def test_exact_roundtrip_and_month_grain(snapshot: dict, tmp_path: Path) -> None:
    result = publish(snapshot, tmp_path)
    folder = Path(result["path"])
    pointer = json.loads((tmp_path / "current.json").read_text())
    manifest_bytes = (folder / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    assert pointer["manifest_sha256"] == service.sha256(manifest_bytes)
    assert manifest["latest_data_month"] == "2024-01-01"
    assert manifest["files"]["monthly.json"]["row_count"] == 13
    for filename, model in (("monthly.json", MonthlyRow), ("partners.json", PartnerRow)):
        payload = (folder / filename).read_bytes()
        assert manifest["files"][filename]["sha256"] == service.sha256(payload)
        envelope = json.loads(payload)
        assert envelope["snapshot_id"] == pointer["snapshot_id"]
        for row in envelope["rows"]:
            model.model_validate_json(json.dumps(row))
    partner = json.loads((folder / "partners.json").read_text())["rows"][0]
    monthly = json.loads((folder / "monthly.json").read_text())["rows"]
    assert partner["import_value"] == "9007199254740993.123456789"
    assert partner["partner_code"] == "004"
    assert partner["map_iso3"] is None
    assert "world_value" not in partner
    assert monthly[1]["world_value"] is None  # missing month remains a gap
    assert monthly[-1]["world_yoy"] == "0"  # calendar-matched, World-only month
    assert sum(Decimal(row["world_value"]) for row in monthly if row["world_value"]) == AMOUNT * 2
    assert not (folder / "audit").exists()


@pytest.mark.parametrize(
    "corruption",
    ["duplicate", "float", "nan", "missing_month", "special"],
)
def test_invalid_snapshot_preserves_current(
    snapshot: dict, tmp_path: Path, corruption: str
) -> None:
    publish(snapshot, tmp_path)
    current = (tmp_path / "current.json").read_bytes()
    broken = copy.deepcopy(snapshot)
    if corruption == "duplicate":
        broken["partners"].append(broken["partners"][0])
    elif corruption == "float":
        broken["partners"][0]["import_value"] = 0.1
    elif corruption == "nan":
        broken["monthly"][0]["world_value"] = Decimal("NaN")
    elif corruption == "missing_month":
        broken["monthly"].pop(1)
    elif corruption == "special":
        broken["partners"][0]["partner_code"] = "490"
    with pytest.raises((ValueError, ValidationError)):
        publish(broken, tmp_path)
    assert (tmp_path / "current.json").read_bytes() == current
    assert not list(tmp_path.glob(".staging-*"))


def test_pointer_switch_failure_preserves_current(
    snapshot: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publish(snapshot, tmp_path)
    current = (tmp_path / "current.json").read_bytes()
    monkeypatch.setattr(service.os, "replace", Mock(side_effect=OSError("disk failure")))
    with pytest.raises(OSError, match="disk failure"):
        publish(snapshot, tmp_path)
    assert (tmp_path / "current.json").read_bytes() == current
    assert not list(tmp_path.glob(".current-*"))
    assert not list(tmp_path.glob(".staging-*"))


def write_artifacts(path: Path) -> None:
    monthly = "model.trade_analytics.mart_multi_market_ic_monthly"
    partners = "model.trade_analytics.mart_multi_market_ic_partners"
    test = "test.trade_analytics.assert_multi_market_presentation"
    metadata = {"invocation_id": "test-build", "generated_at": datetime.now(UTC).isoformat()}
    nodes = {
        key: {
            "resource_type": "model",
            "database": "trade-analytics-508604",
            "schema": "trade_analytics",
        }
        for key in (monthly, partners)
    }
    nodes[test] = {"resource_type": "test", "depends_on": {"nodes": [monthly, partners]}}
    (path / "manifest.json").write_text(json.dumps({"metadata": metadata, "nodes": nodes}))
    (path / "run_results.json").write_text(
        json.dumps(
            {
                "metadata": metadata,
                "args": {"which": "build"},
                "results": [
                    {"unique_id": monthly, "status": "success"},
                    {"unique_id": partners, "status": "success"},
                    {"unique_id": test, "status": "pass"},
                ],
            }
        )
    )


@pytest.mark.parametrize(
    "problem",
    [None, "failed", "missing_test", "wrong_target", "stale", "mismatched_invocation", "run_only"],
)
def test_build_gate(tmp_path: Path, problem: str | None) -> None:
    write_artifacts(tmp_path)
    path = tmp_path / "run_results.json"
    results = json.loads(path.read_text())
    settings = Settings("trade-analytics-508604")
    if problem == "failed":
        results["results"][-1]["status"] = "fail"
    elif problem == "missing_test":
        results["results"].pop()
    elif problem == "wrong_target":
        settings = Settings("trade-analytics-508604", dataset="other")
    elif problem == "stale":
        results["metadata"]["generated_at"] = "2020-01-01T00:00:00+00:00"
    elif problem == "mismatched_invocation":
        results["metadata"]["invocation_id"] = "another-build"
    elif problem == "run_only":
        results["args"]["which"] = "run"
    path.write_text(json.dumps(results))
    if problem:
        with pytest.raises(ValueError):
            service.validate_build(tmp_path, settings)
    else:
        assert service.validate_build(tmp_path, settings)["invocation_id"] == "test-build"


def test_verify_checks_integrity_and_schema(snapshot: dict, tmp_path: Path) -> None:
    result = publish(snapshot, tmp_path)
    assert verify_v2(tmp_path)["status"] == "verified"
    partner_path = Path(result["path"]) / "partners.json"
    partner_path.write_bytes(partner_path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="checksum"):
        verify_v2(tmp_path)


def test_v2_reader_paginates_typed_rows_without_large_array(
    snapshot: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = SimpleNamespace(
        ScalarQueryParameter=lambda *args: args,
        QueryJobConfig=lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(queries, "import_module", lambda _: api)
    client = Mock()
    client.query.return_value = SimpleNamespace(
        result=lambda timeout: iter(
            [
                {"kind": "monthly", "monthly": snapshot["monthly"][0], "partners": None},
                {"kind": "partners", "monthly": None, "partners": snapshot["partners"][0]},
            ]
        ),
        job_id="streamed",
        total_bytes_processed=100,
        total_bytes_billed=100,
    )
    raw = queries.SnapshotReader(Settings("trade-analytics-508604"), client).read(START, END)
    assert raw["partners"][0]["import_value"] == AMOUNT
    assert raw["monthly"][0]["month"] == START
    assert client.query.call_count == 1
    sql = client.query.call_args.args[0]
    assert "UNION ALL" in sql and "ARRAY(" not in sql
    assert "STRUCT<" in sql


def test_export_range_supports_full_history_with_a_finite_bound() -> None:
    from datetime import date

    settings = Settings(
        "trade-analytics-508604", first_month=date(2016, 1, 1), after_last_month=date(2026, 10, 1)
    )
    assert settings.first_month == date(2016, 1, 1)
    with pytest.raises(ValueError, match="180"):
        Settings(
            "trade-analytics-508604",
            first_month=date(2016, 1, 1),
            after_last_month=date(2031, 2, 1),
        )


def test_committed_v2_schemas_match_models():
    from trade_analytics.export.v2 import contract_schemas_v2

    for name, schema in contract_schemas_v2().items():
        assert json.loads((Path("docs/schemas") / name).read_text()) == schema


@pytest.mark.parametrize("kind", ["version", "snapshot", "row_count"])
def test_document_contract_rejects_mixed_snapshot(snapshot, tmp_path, kind):
    result = publish(snapshot, tmp_path)
    folder = Path(result["path"])
    path = folder / "partners.json"
    document = json.loads(path.read_bytes())
    if kind == "version":
        document["schema_version"] = "1.0.0"
    elif kind == "snapshot":
        document["snapshot_id"] = "0" * 32
    else:
        document["rows"] = []
    payload = json.dumps(document).encode()
    path.write_bytes(payload)
    # Keep hashes valid so this exercises the schema/identity/count gate itself.
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["files"]["partners.json"].update(sha256=service.sha256(payload), bytes=len(payload))
    manifest_payload = json.dumps(manifest).encode()
    manifest_path.write_bytes(manifest_payload)
    pointer_path = tmp_path / "current.json"
    pointer = json.loads(pointer_path.read_bytes())
    pointer["manifest_sha256"] = service.sha256(manifest_payload)
    pointer_path.write_text(json.dumps(pointer))
    with pytest.raises(ValueError):
        verify_v2(tmp_path)
