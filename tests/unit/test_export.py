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
from trade_analytics.export.schemas import MonthlyRow, PartnerRow
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
                "cmd_code": "8542",
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
                "cmd_code": "8542",
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
    ["duplicate", "float", "nan", "total", "growth", "hhi", "missing_month", "special"],
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
    elif corruption == "total":
        broken["monthly"][0]["country_value"] = Decimal("1")
    elif corruption == "growth":
        broken["monthly"][-1]["world_yoy"] = Decimal("0.5")
    elif corruption == "hhi":
        broken["monthly"][0]["hhi_status"] = "insufficient_coverage"
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


def test_partner_growth_uses_calendar_month(snapshot: dict) -> None:
    # January 2024 has a country row, but its preceding row is not December.
    raw = copy.deepcopy(snapshot)
    partner = copy.deepcopy(raw["partners"][0])
    partner.update(month=date(2024, 1, 1), previous_year_value=AMOUNT, yoy=Decimal(0))
    raw["partners"].append(partner)
    raw["monthly"][-1].update(
        country_value=AMOUNT,
        country_count=1,
        country_coverage=Decimal(1),
        hhi=Decimal(10000),
        hhi_status="ok",
        has_countries=True,
    )
    service.validate_snapshot(raw, START, END)
    partner.update(previous_month_value=AMOUNT, mom=Decimal(0))
    with pytest.raises(ValueError, match="calendar-matched"):
        service.validate_snapshot(raw, START, END)


def write_artifacts(path: Path) -> None:
    monthly = "model.trade_analytics.mart_dashboard_monthly"
    partners = "model.trade_analytics.mart_dashboard_partners"
    test = "test.trade_analytics.assert_presentation"
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


def test_export_query_is_single_bounded_statement(
    snapshot: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = SimpleNamespace(
        ScalarQueryParameter=lambda name, kind, value: (name, kind, value),
        QueryJobConfig=lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(queries, "import_module", lambda _: api)
    client = Mock()
    client.query.return_value = SimpleNamespace(
        result=lambda timeout: [snapshot],
        job_id="job",
        total_bytes_processed=100,
        total_bytes_billed=100,
    )
    reader = queries.SnapshotReader(Settings("trade-analytics-508604"), client)
    assert reader.read(START, END) == snapshot
    assert client.query.call_count == 1
    sql = client.query.call_args.args[0]
    config = client.query.call_args.kwargs["job_config"]
    assert "mart_dashboard_monthly" in sql and "mart_dashboard_partners" in sql
    assert "month >= @start_date AND month < @end_exclusive" in sql
    assert config.maximum_bytes_billed == 10**9
    assert config.use_query_cache is False
    assert [value for name, kind, value in config.query_parameters][:2] == [START, END]


def test_verify_checks_integrity_and_schema(snapshot: dict, tmp_path: Path) -> None:
    result = publish(snapshot, tmp_path)
    assert service.verify_snapshot(tmp_path)["status"] == "verified"
    partner_path = Path(result["path"]) / "partners.json"
    partner_path.write_bytes(partner_path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="checksum"):
        service.verify_snapshot(tmp_path)


def test_committed_json_schemas_match_models() -> None:
    from trade_analytics.export.schemas import contract_schemas

    folder = Path(__file__).resolve().parents[2] / "docs/schemas"
    for filename, schema in contract_schemas().items():
        assert json.loads((folder / filename).read_text()) == schema


def test_verify_cli_needs_no_cloud(
    snapshot: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from trade_analytics.export import cli

    publish(snapshot, tmp_path)
    monkeypatch.setattr(
        "sys.argv", ["trade-export", "--verify-only", "--output-dir", str(tmp_path)]
    )
    monkeypatch.setattr(cli, "SnapshotReader", Mock(side_effect=AssertionError("must be offline")))
    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "verified"
