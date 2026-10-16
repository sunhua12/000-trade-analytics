"""Public JSON v1 contract. Monetary values and ratios are decimal strings."""

import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    WithJsonSchema,
    field_validator,
)

SCHEMA_VERSION = "1.0.0"


def decimal_value(value: Any) -> Decimal:
    # Reject floats: converting an already rounded float cannot recover precision.
    if not isinstance(value, (str, Decimal)):
        raise ValueError("decimal fields require Decimal or a decimal string")
    if isinstance(value, str) and not re.fullmatch(r"-?\d+(?:\.\d+)?", value):
        raise ValueError("expected a plain decimal string")
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError("non-finite decimals are forbidden")
    return result


def decimal_string(value: Decimal) -> str:
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


ExactDecimal = Annotated[
    Decimal,
    BeforeValidator(decimal_value),
    PlainSerializer(decimal_string, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": r"^-?\d+(?:\.\d+)?$"}, mode="serialization"),
]
HHIStatus = Literal[
    "ok",
    "missing_world",
    "invalid_world",
    "no_countries",
    "missing_country_value",
    "negative_country_value",
    "unreviewed_country",
    "insufficient_coverage",
]


class Row(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    month: date
    cmd_code: Literal["8542"]
    hs_version: Literal["H6"]

    @field_validator("month")
    @classmethod
    def first_of_month(cls, value: date) -> date:
        if value.day != 1:
            raise ValueError("month must be the first day")
        return value


class MonthlyRow(Row):
    world_value: ExactDecimal | None
    previous_year_world_value: ExactDecimal | None
    world_yoy: ExactDecimal | None
    country_value: ExactDecimal | None
    country_count: int
    country_coverage: ExactDecimal | None
    hhi: ExactDecimal | None
    hhi_status: HHIStatus
    has_world: bool
    has_countries: bool


class PartnerRow(Row):
    partner_code: str
    source_name: str | None
    map_iso3: str | None
    import_value: ExactDecimal
    market_share: ExactDecimal | None
    market_share_status: Literal["ok", "missing_world", "invalid_world", "missing_value"]
    previous_month_value: ExactDecimal | None
    previous_year_value: ExactDecimal | None
    mom: ExactDecimal | None
    yoy: ExactDecimal | None

    @field_validator("partner_code")
    @classmethod
    def code_is_digits(cls, value: str) -> str:
        if not re.fullmatch(r"\d+", value) or int(value) in (0, 490):
            raise ValueError("expected a confirmed non-World, non-special partner code")
        return value

    @field_validator("map_iso3")
    @classmethod
    def iso3_code(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[A-Z]{3}", value):
            raise ValueError("expected ISO alpha-3 or null")
        return value


class Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["1.0.0"]
    snapshot_id: Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]


class MonthlyDocument(Envelope):
    rows: list[MonthlyRow]


class PartnerDocument(Envelope):
    rows: list[PartnerRow]


class FileInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    row_count: Annotated[int, Field(ge=0)]
    bytes: Annotated[int, Field(gt=0)]
    sha256: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]


class FileIndex(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    monthly: FileInfo = Field(alias="monthly.json")
    partners: FileInfo = Field(alias="partners.json")


class SnapshotManifest(Envelope):
    generated_at: AwareDatetime
    start_month: date
    end_exclusive: date
    latest_data_month: date
    currency: Literal["USD"]
    reporter_code: Literal["842"]
    cmd_code: Literal["8542"]
    hs_version: Literal["H6"]
    decimal_encoding: Literal["string"]
    hhi_coverage_tolerance: Literal["0.005"]
    files: FileIndex


class CurrentPointer(Envelope):
    manifest: str
    manifest_sha256: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]


def contract_schemas() -> dict[str, dict[str, Any]]:
    return {
        filename: model.model_json_schema(mode="serialization")
        for filename, model in (
            ("monthly.schema.json", MonthlyDocument),
            ("partners.schema.json", PartnerDocument),
            ("manifest.schema.json", SnapshotManifest),
            ("current.schema.json", CurrentPointer),
        )
    }


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Generate public JSON Schema documents")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for filename, schema in contract_schemas().items():
        (args.output_dir / filename).write_text(json.dumps(schema, indent=2) + "\n")
