"""Multi-market JSON v2; exact decimal fields and per-scope validation."""

import hashlib
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from trade_analytics.export.schemas import (
    CurrentPointerV2,
    MonthlyDocumentV2,
    MonthlyRowV2,
    PartnerDocumentV2,
    PartnerRowV2,
    SnapshotManifestV2,
)
from trade_analytics.ingestion.multi_market import MARKETS, PRODUCTS


def sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def contract_schemas_v2() -> dict[str, Any]:
    return {
        name: model.model_json_schema(mode="serialization")
        for name, model in (
            ("monthly.schema.json", MonthlyDocumentV2),
            ("partners.schema.json", PartnerDocumentV2),
            ("manifest.schema.json", SnapshotManifestV2),
            ("current.schema.json", CurrentPointerV2),
        )
    }


def validate_v2(raw: dict[str, Any], start: date, end: date) -> tuple[list[Any], list[Any]]:
    monthly = [MonthlyRowV2.model_validate(row) for row in raw["monthly"]]
    partners = [PartnerRowV2.model_validate(row) for row in raw["partners"]]
    scopes = {(row.reporter_code, row.cmd_code) for row in monthly}
    if not scopes or any(int(reporter) not in MARKETS for reporter, _ in scopes):
        raise ValueError("missing or unsupported market scope")
    if any((row.reporter_code, row.cmd_code) not in scopes for row in partners):
        raise ValueError("partner has no corresponding market/product scope")
    from trade_analytics.warehouse.read_settings import next_month

    expected = []
    month = start
    while month < end:
        expected.append(month)
        month = next_month(month)
    grouped = defaultdict(list)
    for row in monthly:
        grouped[row.reporter_code, row.cmd_code].append(row)
    for rows in grouped.values():
        if not expected or [r.month for r in rows] != expected:
            raise ValueError("monthly snapshot must contain the complete ordered month spine")
    if not any(r.has_world or r.has_countries for r in monthly):
        raise ValueError("refusing to publish an entirely empty dataset")
    monthly_keys = {(r.reporter_code, r.cmd_code, r.month) for r in monthly}
    keys = [(r.reporter_code, r.cmd_code, r.month, r.partner_code) for r in partners]
    if len(set(keys)) != len(keys) or any(k[:3] not in monthly_keys for k in keys):
        raise ValueError("duplicate partner grain or partner outside monthly range")
    return monthly, partners


def verify_v2(output: Path) -> dict[str, Any]:
    pointer = CurrentPointerV2.model_validate_json(
        (output / "current.json").read_bytes()
    ).model_dump()
    snapshot_id = pointer["snapshot_id"]
    if pointer["manifest"] != f"{snapshot_id}/manifest.json":
        raise ValueError("invalid manifest path")
    folder = output / snapshot_id
    payload = (folder / "manifest.json").read_bytes()
    if sha256(payload) != pointer["manifest_sha256"]:
        raise ValueError("manifest checksum mismatch")
    manifest = SnapshotManifestV2.model_validate_json(payload).model_dump(
        mode="json", by_alias=True
    )
    if manifest["schema_version"] != "2.0.0" or manifest["snapshot_id"] != snapshot_id:
        raise ValueError("manifest identity mismatch")
    raw = {}
    for name in ("monthly", "partners"):
        data = (folder / f"{name}.json").read_bytes()
        metadata = manifest["files"][f"{name}.json"]
        if sha256(data) != metadata["sha256"] or len(data) != metadata["bytes"]:
            raise ValueError("data checksum mismatch")
        document_model = MonthlyDocumentV2 if name == "monthly" else PartnerDocumentV2
        document = document_model.model_validate_json(data)
        if document.snapshot_id != snapshot_id or len(document.rows) != metadata["row_count"]:
            raise ValueError("data identity mismatch")
        raw[name] = [row.model_dump() for row in document.rows]
    monthly, partners = validate_v2(
        raw,
        date.fromisoformat(manifest["start_month"]),
        date.fromisoformat(manifest["end_exclusive"]),
    )
    expected_metadata = scope_metadata(monthly, partners)
    if any(manifest[key] != value for key, value in expected_metadata.items()):
        raise ValueError("manifest scope metadata differs from data")
    latest = max(row.month.isoformat() for row in monthly if row.has_world or row.has_countries)
    if latest != manifest["latest_data_month"]:
        raise ValueError("latest data month differs from manifest")
    return {
        "status": "verified",
        "snapshot_id": snapshot_id,
        "latest_data_month": manifest["latest_data_month"],
    }


def scope_metadata(monthly: list[Any], partners: list[Any]) -> dict[str, Any]:
    availability = []
    grouped = defaultdict(list)
    for row in monthly:
        if row.has_world or row.has_countries:
            grouped[row.reporter_code, row.cmd_code].append(row.month.isoformat())
    for (reporter, product), values in sorted(grouped.items()):
        months = sorted(values)
        availability.append(
            {
                "reporter_code": reporter,
                "cmd_code": product,
                "months": months,
                "start_month": min(months),
                "latest_data_month": max(months),
            }
        )
    return {
        "valid_detail_count": len(partners),
        "positive_amount_count": sum(row.import_value > 0 for row in partners),
        "row_target_met": len(partners) >= 100000,
        "markets": [{"reporter_code": str(code), "name": name} for code, name in MARKETS.items()],
        "products": [
            {"cmd_code": code, "name": name, "is_parts": code == "854290"}
            for code, name in PRODUCTS.items()
        ],
        "availability": availability,
    }
