"""Multi-market JSON v2; exact decimal fields and per-scope validation."""

import json
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from trade_analytics.export.schemas import (
    CurrentPointer,
    ExactDecimal,
    FileIndex,
    MonthlyRow,
    PartnerRow,
)
from trade_analytics.export.service import sha256, validate_snapshot
from trade_analytics.ingestion.multi_market import MARKETS, PRODUCTS


class MonthlyRowV2(MonthlyRow):
    reporter_code: str = Field(pattern=r"^\d+$")
    cmd_code: Literal["854231", "854232", "854233", "854239", "854290"]  # type: ignore[assignment]
    hs_version: str | None = Field(pattern=r"^H[0-6]$")  # type: ignore[assignment]


class PartnerRowV2(PartnerRow):
    reporter_code: str = Field(pattern=r"^\d+$")
    cmd_code: Literal["854231", "854232", "854233", "854239", "854290"]  # type: ignore[assignment]
    hs_version: str = Field(pattern=r"^H[0-6]$")  # type: ignore[assignment]
    import_value: ExactDecimal


class DocumentV2(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["2.0.0"]
    snapshot_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    rows: list[dict[str, Any]]


class MonthlyDocumentV2(DocumentV2):
    rows: list[MonthlyRowV2]  # type: ignore[assignment]


class PartnerDocumentV2(DocumentV2):
    rows: list[PartnerRowV2]  # type: ignore[assignment]


class MarketMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    reporter_code: str
    name: str


class ProductMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    cmd_code: str
    name: str
    is_parts: bool


class Availability(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    reporter_code: str
    cmd_code: str
    months: list[date]
    start_month: date
    latest_data_month: date


class SnapshotManifestV2(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["2.0.0"]
    snapshot_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    generated_at: AwareDatetime
    start_month: date
    end_exclusive: date
    latest_data_month: date
    currency: Literal["USD"]
    decimal_encoding: Literal["string"]
    hhi_coverage_tolerance: Literal["0.005"]
    files: FileIndex
    valid_detail_count: int = Field(ge=0)
    positive_amount_count: int = Field(ge=0)
    row_target_met: bool
    markets: list[MarketMetadata]
    products: list[ProductMetadata]
    availability: list[Availability]


class CurrentPointerV2(CurrentPointer):
    schema_version: Literal["2.0.0"]  # type: ignore[assignment]


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
    for reporter, product in scopes:
        # Reuse the v1 monetary/calendar validator independently for each scope.
        subset: dict[str, Any] = {}
        for name, rows in (("monthly", monthly), ("partners", partners)):
            subset[name] = [
                {
                    **row.model_dump(exclude={"reporter_code"}),
                    "cmd_code": "8542",
                    "hs_version": "H6",
                }
                for row in rows
                if row.reporter_code == reporter and row.cmd_code == product
            ]
        validate_snapshot(subset, start, end)
    return monthly, partners


def verify_v2(output: Path) -> dict[str, Any]:
    pointer = CurrentPointerV2.model_validate_json(
        (output / "current.json").read_bytes()
    ).model_dump()
    snapshot_id = pointer["snapshot_id"]
    import re

    if not re.fullmatch(r"[a-f0-9]{32}", snapshot_id):
        raise ValueError("invalid snapshot identity")
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
        document = DocumentV2.model_validate_json(data)
        if document.snapshot_id != snapshot_id or len(document.rows) != metadata["row_count"]:
            raise ValueError("data identity mismatch")
        model = MonthlyRowV2 if name == "monthly" else PartnerRowV2
        raw[name] = [
            model.model_validate_json(json.dumps(row)).model_dump() for row in document.rows
        ]
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
    for reporter, product in sorted({(row.reporter_code, row.cmd_code) for row in monthly}):
        months = sorted(
            row.month.isoformat()
            for row in monthly
            if row.reporter_code == reporter
            and row.cmd_code == product
            and (row.has_world or row.has_countries)
        )
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
