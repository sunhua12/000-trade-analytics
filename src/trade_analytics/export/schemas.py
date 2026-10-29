"""Shared JSON row types; monetary values are exact decimal strings."""

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
    cmd_code: Literal["854231", "854232", "854233", "854239", "854290"]

    hs_version: str | None = Field(pattern=r"^H[0-6]$")

    @field_validator("month")
    @classmethod
    def first_of_month(cls, value: date) -> date:
        if value.day != 1:
            raise ValueError("month must be the first day")
        return value


class MonthlyRowV2(Row):
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
    reporter_code: str = Field(pattern=r"^\d+$")


class PartnerRowV2(Row):
    hs_version: str = Field(pattern=r"^H[0-6]$")
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

    reporter_code: str = Field(pattern=r"^\d+$")

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


class FileInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    row_count: Annotated[int, Field(ge=0)]
    bytes: Annotated[int, Field(gt=0)]
    sha256: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]


class FileIndex(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    monthly: FileInfo = Field(alias="monthly.json")
    partners: FileInfo = Field(alias="partners.json")


class CurrentPointerV2(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["2.0.0"]
    snapshot_id: Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
    manifest: str
    manifest_sha256: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]


class DocumentV2(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["2.0.0"]
    snapshot_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class MonthlyDocumentV2(DocumentV2):
    rows: list[MonthlyRowV2]


class PartnerDocumentV2(DocumentV2):
    rows: list[PartnerRowV2]


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
