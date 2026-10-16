"""Cross-check dbt output, then publish an immutable local snapshot."""

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

from trade_analytics.export.schemas import SCHEMA_VERSION, MonthlyRow, PartnerRow, SnapshotManifest
from trade_analytics.warehouse.read_settings import Settings, next_month

RATIO_TOLERANCE = Decimal("0.000000001")  # BigQuery NUMERIC has nine fractional digits.
HHI_COVERAGE_TOLERANCE = Decimal("0.005")


def json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()


def sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def validate_build(artifacts: Path, settings: Settings) -> dict[str, str]:
    """Require a fresh successful build including both views and their data tests."""
    manifest_bytes = (artifacts / "manifest.json").read_bytes()
    results_bytes = (artifacts / "run_results.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    results = json.loads(results_bytes)
    invocation = results["metadata"]["invocation_id"]
    if invocation != manifest["metadata"]["invocation_id"]:
        raise ValueError("dbt artifacts must come from the same invocation")
    generated = datetime.fromisoformat(results["metadata"]["generated_at"].replace("Z", "+00:00"))
    if generated.tzinfo is None:
        raise ValueError("dbt build timestamp must include a timezone")
    age = datetime.now(UTC) - generated
    if not timedelta(0) <= age <= timedelta(hours=24):
        raise ValueError("dbt build evidence must be from the last 24 hours")
    if results.get("args", {}).get("which") != "build":
        raise ValueError("export requires dbt build evidence, not dbt run or compile")
    nodes = manifest["nodes"]
    models = {
        "model.trade_analytics.mart_dashboard_monthly",
        "model.trade_analytics.mart_dashboard_partners",
    }
    for key in models:
        node = nodes[key]
        if node["database"] != settings.project or node["schema"] != settings.dataset:
            raise ValueError("dbt build target differs from export target")
    tests = {
        key
        for key, node in nodes.items()
        if node["resource_type"] == "test"
        and models.intersection(node.get("depends_on", {}).get("nodes", []))
    }
    if "test.trade_analytics.assert_presentation" not in tests:
        raise ValueError("missing presentation consistency test")
    statuses = {result["unique_id"]: result["status"] for result in results["results"]}
    if any(status not in ("success", "pass") for status in statuses.values()):
        raise ValueError("dbt invocation contains failed, warned, or skipped nodes")
    if any(statuses.get(key) != "success" for key in models) or any(
        statuses.get(key) != "pass" for key in tests
    ):
        raise ValueError("both presentation models and all their data tests must pass")
    return {
        "invocation_id": invocation,
        "manifest_sha256": sha256(manifest_bytes),
        "run_results_sha256": sha256(results_bytes),
    }


def assert_ratio(
    actual: Decimal | None,
    numerator: Decimal | None,
    denominator: Decimal | None,
    *,
    growth: bool = False,
) -> None:
    expected = (
        numerator / denominator - (1 if growth else 0)
        if numerator is not None and denominator is not None and denominator > 0
        else None
    )
    if (actual is None) != (expected is None) or (
        actual is not None and expected is not None and abs(actual - expected) > RATIO_TOLERANCE
    ):
        raise ValueError("ratio does not match its numerator and denominator")


def validate_snapshot(
    raw: dict[str, Any], start: date, end_exclusive: date
) -> tuple[list[MonthlyRow], list[PartnerRow]]:
    monthly = [MonthlyRow.model_validate(row) for row in raw["monthly"]]
    partners = [PartnerRow.model_validate(row) for row in raw["partners"]]
    expected = []
    month = start
    while month < end_exclusive:
        expected.append(month)
        month = next_month(month)
    if not expected or [row.month for row in monthly] != expected:
        raise ValueError("monthly snapshot must contain the complete ordered month spine")
    if not any(row.has_world or row.has_countries for row in monthly):
        raise ValueError("refusing to publish an entirely empty dataset")
    by_month = {row.month: row for row in monthly}
    grouped: dict[date, list[PartnerRow]] = {month: [] for month in expected}
    seen = set()
    for partner_row in partners:
        key = (partner_row.month, partner_row.partner_code)
        if key in seen or partner_row.month not in by_month:
            raise ValueError("duplicate partner grain or partner outside monthly range")
        seen.add(key)
        grouped[partner_row.month].append(partner_row)
    with localcontext() as context:
        context.prec = 80
        for row in monthly:
            detail = grouped[row.month]
            total = (
                sum((partner.import_value for partner in detail), Decimal(0)) if detail else None
            )
            if row.country_count != len(detail) or row.country_value != total:
                raise ValueError("monthly country amount/count does not reconcile with partners")
            if row.has_world != (row.world_value is not None) or row.has_countries != bool(detail):
                raise ValueError("source presence flags do not match data")
            if any(v is not None and v < 0 for v in (row.world_value, row.country_value)):
                raise ValueError("negative import amounts are forbidden")
            assert_ratio(row.world_yoy, row.world_value, row.previous_year_world_value, growth=True)
            assert_ratio(row.country_coverage, row.country_value, row.world_value)
            prior = by_month.get(date(row.month.year - 1, row.month.month, 1))
            if prior is not None and row.previous_year_world_value != prior.world_value:
                raise ValueError("World previous-year amount differs from calendar-matched month")
            if (row.hhi_status == "ok") != (row.hhi is not None):
                raise ValueError("HHI availability differs from status")
            if row.hhi is not None:
                if (
                    row.country_coverage is None
                    or abs(1 - row.country_coverage) > HHI_COVERAGE_TOLERANCE
                ):
                    raise ValueError("HHI requires sufficient country coverage")
                hhi = sum(
                    ((p.market_share * 100) ** 2 for p in detail if p.market_share is not None),
                    Decimal(0),
                )
                # HHI source uses FLOAT64 and shares rounded to NUMERIC scale.
                if abs(row.hhi - hhi) > Decimal("0.0001"):
                    raise ValueError("HHI does not reconcile with country shares")
            for partner in detail:
                if partner.import_value < 0:
                    raise ValueError("negative partner import value")
                assert_ratio(partner.market_share, partner.import_value, row.world_value)
                assert_ratio(
                    partner.mom, partner.import_value, partner.previous_month_value, growth=True
                )
                assert_ratio(
                    partner.yoy, partner.import_value, partner.previous_year_value, growth=True
                )
                expected_status = (
                    "missing_world"
                    if row.world_value is None
                    else "invalid_world"
                    if row.world_value <= 0
                    else "ok"
                )
                if partner.market_share_status != expected_status:
                    raise ValueError("market share status differs from World availability")
                for prior_month, previous_value in (
                    ((row.month - timedelta(days=1)).replace(day=1), partner.previous_month_value),
                    (date(row.month.year - 1, row.month.month, 1), partner.previous_year_value),
                ):
                    if prior_month in grouped:
                        prior_value = next(
                            (
                                p.import_value
                                for p in grouped[prior_month]
                                if p.partner_code == partner.partner_code
                            ),
                            None,
                        )
                        if previous_value != prior_value:
                            raise ValueError(
                                "partner growth base differs from calendar-matched month"
                            )
    return monthly, sorted(partners, key=lambda row: (row.month, row.partner_code))


def publish_snapshot(
    raw: dict[str, Any],
    output: Path,
    start: date,
    end_exclusive: date,
    *,
    build: dict[str, str],
    jobs: list[dict[str, Any]],
) -> dict[str, Any]:
    monthly, partners = validate_snapshot(raw, start, end_exclusive)
    snapshot_id = uuid.uuid4().hex
    output.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".staging-", dir=output))
    pointer_temp: Path | None = None
    try:
        files = {}
        for name, rows in (("monthly.json", monthly), ("partners.json", partners)):
            payload = json_bytes(
                {
                    "schema_version": SCHEMA_VERSION,
                    "snapshot_id": snapshot_id,
                    "rows": [row.model_dump(mode="json") for row in rows],
                }
            )
            (stage / name).write_bytes(payload)
            files[name] = {"row_count": len(rows), "sha256": sha256(payload), "bytes": len(payload)}
        available = [row.month for row in monthly if row.has_world or row.has_countries]
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": snapshot_id,
            "generated_at": datetime.now(UTC).isoformat(),
            "start_month": start.isoformat(),
            "end_exclusive": end_exclusive.isoformat(),
            "latest_data_month": max(available).isoformat(),
            "currency": "USD",
            "reporter_code": "842",
            "cmd_code": "8542",
            "hs_version": "H6",
            "decimal_encoding": "string",
            "hhi_coverage_tolerance": "0.005",
            "files": files,
        }
        manifest_payload = json_bytes(manifest)
        SnapshotManifest.model_validate_json(manifest_payload)
        (stage / "manifest.json").write_bytes(manifest_payload)
        # Internal evidence stays outside the directory consumed by the website.
        audit = output / "audit"
        audit.mkdir(exist_ok=True)
        (audit / f"{snapshot_id}.json").write_bytes(json_bytes({"dbt": build, "jobs": jobs}))
        destination = output / snapshot_id
        stage.rename(destination)
        pointer = {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": snapshot_id,
            "manifest": f"{snapshot_id}/manifest.json",
            "manifest_sha256": sha256(manifest_payload),
        }
        descriptor, temp_name = tempfile.mkstemp(prefix=".current-", dir=output)
        pointer_temp = Path(temp_name)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(json_bytes(pointer))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(pointer_temp, output / "current.json")
        return {
            "status": "success",
            "snapshot_id": snapshot_id,
            "path": str(destination.resolve()),
            "files": files,
        }
    finally:
        if stage.exists():
            shutil.rmtree(stage)
        if pointer_temp is not None:
            pointer_temp.unlink(missing_ok=True)


def verify_snapshot(output: Path) -> dict[str, Any]:
    """Verify the current snapshot from disk without cloud access or credentials."""
    from trade_analytics.export.schemas import (
        CurrentPointer,
        MonthlyDocument,
        PartnerDocument,
        SnapshotManifest,
    )

    pointer = CurrentPointer.model_validate_json((output / "current.json").read_bytes())
    if pointer.manifest != f"{pointer.snapshot_id}/manifest.json":
        raise ValueError("manifest path does not match snapshot ID")
    folder = output / pointer.snapshot_id
    manifest_bytes = (folder / "manifest.json").read_bytes()
    if sha256(manifest_bytes) != pointer.manifest_sha256:
        raise ValueError("manifest checksum mismatch")
    manifest = SnapshotManifest.model_validate_json(manifest_bytes)
    if manifest.snapshot_id != pointer.snapshot_id:
        raise ValueError("manifest and pointer refer to different snapshots")
    raw = {}
    for name, model, metadata in (
        ("monthly", MonthlyDocument, manifest.files.monthly),
        ("partners", PartnerDocument, manifest.files.partners),
    ):
        payload = (folder / f"{name}.json").read_bytes()
        if sha256(payload) != metadata.sha256 or len(payload) != metadata.bytes:
            raise ValueError("data checksum or size mismatch")
        document = model.model_validate_json(payload)
        if document.snapshot_id != pointer.snapshot_id or len(document.rows) != metadata.row_count:
            raise ValueError("data version or row count mismatch")
        raw[name] = [row.model_dump() for row in document.rows]
    monthly, _ = validate_snapshot(raw, manifest.start_month, manifest.end_exclusive)
    latest = max(row.month for row in monthly if row.has_world or row.has_countries)
    if latest != manifest.latest_data_month:
        raise ValueError("latest data month differs from manifest")
    return {
        "status": "verified",
        "snapshot_id": pointer.snapshot_id,
        "latest_data_month": latest.isoformat(),
    }
