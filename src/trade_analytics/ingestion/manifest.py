"""Deterministic serialization and manifest generation."""

import hashlib
import json
from datetime import datetime
from decimal import Decimal, localcontext
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from trade_analytics.ingestion.exceptions import DataContractError, StorageConflictError
from trade_analytics.ingestion.queries import ComtradeQuery, QueryType
from trade_analytics.ingestion.service import IngestionDataset


class Manifest(BaseModel):
    """Audit metadata written alongside one local raw dataset."""

    model_config = ConfigDict(frozen=True)

    request_parameters: dict[str, str | int]
    checksum: str
    schema_version: Literal["2.0.0"]
    hs_version: Literal["H6"]
    period: str
    query_type: QueryType
    cmd_code: str
    revision: int = Field(gt=0, strict=True)
    row_count: int = Field(gt=0)
    primary_value_sum: Decimal = Field(allow_inf_nan=False, ge=0)
    ingested_at: datetime
    source: str


def _decimal_string(value: object) -> str:
    """Encode decimal values without context rounding or exponent notation."""
    if not isinstance(value, Decimal):
        raise TypeError(f"Cannot serialize {type(value).__name__}")
    if not value.is_finite():
        raise DataContractError("non-finite decimal cannot be serialized")
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def serialize_manifest(manifest: Manifest) -> bytes:
    """Serialize manifest metadata as stable, human-readable JSON bytes."""
    return (
        json.dumps(
            {
                **manifest.model_dump(mode="json"),
                "primary_value_sum": _decimal_string(manifest.primary_value_sum),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode()


def serialize_ndjson(dataset: IngestionDataset) -> bytes:
    """Serialize records to stable, newline-delimited JSON bytes."""
    ordered_rows = sorted(
        dataset.rows,
        key=lambda row: (row.period, row.partner_code, row.cmd_code),
    )
    lines = [
        json.dumps(
            row.model_dump(by_alias=True, mode="python", exclude_none=False),
            default=_decimal_string,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        for row in ordered_rows
    ]
    return ("\n".join(lines) + "\n").encode()


def checksum(data: bytes) -> str:
    """Return a namespaced SHA-256 checksum."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def build_manifest(
    dataset: IngestionDataset,
    *,
    data: bytes,
    ingested_at: datetime,
) -> Manifest:
    """Build audit metadata from a validated dataset and serialized bytes."""
    hs_versions = {row.classification_code for row in dataset.rows}
    if hs_versions != {dataset.query.expected_hs_version}:
        raise DataContractError(
            "dataset must contain exactly the expected HS classification version"
        )

    amounts = [row.primary_value for row in dataset.rows]
    if any(value is None or not value.is_finite() or value < 0 for value in amounts):
        raise DataContractError("primaryValue must be a finite non-negative amount")
    values = [value for value in amounts if value is not None]
    # Decimal's default precision (28) can round sums of otherwise exact inputs.
    scale = max(max(-int(value.as_tuple().exponent), 0) for value in values)
    integer_digits = max(max(value.adjusted() + 1, 1) for value in values)
    with localcontext() as context:
        context.prec = max(38, integer_digits + scale + len(str(len(values))))
        primary_value_sum = sum(values, start=Decimal("0"))
    return Manifest(
        request_parameters=dataset.query.to_params(),
        checksum=checksum(data),
        schema_version="2.0.0",
        hs_version=dataset.query.expected_hs_version,
        period=dataset.query.period,
        query_type=dataset.query.query_type,
        cmd_code=dataset.query.cmd_code,
        revision=dataset.query.revision,
        row_count=len(dataset.rows),
        primary_value_sum=primary_value_sum,
        ingested_at=ingested_at,
        source="UN Comtrade Preview API",
    )


def artifact_partition(query: ComtradeQuery) -> str:
    """Common local/S3 identity; never reuse the legacy directory."""
    return (
        f"v2/hs_version={query.expected_hs_version}/cmd_code={query.cmd_code}/"
        f"period={query.period}/query_type={query.query_type.value}/revision={query.revision}"
    )


def validate_existing_artifacts(
    *,
    data: bytes | None,
    manifest_data: bytes | None,
    expected: Manifest,
    location: str,
) -> None:
    """Validate all existing content before either storage fills missing artifacts."""
    if data is not None and checksum(data) != expected.checksum:
        raise StorageConflictError(f"checksum conflict at {location}")
    if manifest_data is None:
        return
    try:
        existing = Manifest.model_validate_json(manifest_data)
    except ValidationError as error:
        raise StorageConflictError(f"checksum conflict at {location}: invalid manifest") from error
    # Timestamps describe the original write, so a rerun must preserve them.
    if existing.model_dump(exclude={"ingested_at"}) != expected.model_dump(exclude={"ingested_at"}):
        raise StorageConflictError(f"checksum conflict at {location}: manifest identity or totals")
