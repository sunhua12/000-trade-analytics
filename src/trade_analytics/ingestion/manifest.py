"""Deterministic serialization and manifest generation."""

import hashlib
import json
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from trade_analytics.ingestion.exceptions import DataContractError
from trade_analytics.ingestion.service import IngestionDataset


class Manifest(BaseModel):
    """Audit metadata written alongside one local raw dataset."""

    model_config = ConfigDict(frozen=True)

    request_parameters: dict[str, str | int]
    checksum: str
    schema_version: str
    hs_version: str
    row_count: int
    primary_value_sum: Decimal
    ingested_at: datetime
    source: str


def serialize_manifest(manifest: Manifest) -> bytes:
    """Serialize manifest metadata as stable, human-readable JSON bytes."""
    return (
        json.dumps(
            manifest.model_dump(mode="json"),
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
            row.model_dump(by_alias=True, mode="json", exclude_none=False),
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
    if len(hs_versions) != 1:
        raise DataContractError("dataset must contain exactly one HS classification version")

    primary_value_sum = sum(
        (Decimal(str(row.primary_value)) for row in dataset.rows if row.primary_value is not None),
        start=Decimal("0"),
    )
    return Manifest(
        request_parameters=dataset.query.to_params(),
        checksum=checksum(data),
        schema_version="1.0.0",
        hs_version=next(iter(hs_versions)),
        row_count=len(dataset.rows),
        primary_value_sum=primary_value_sum,
        ingested_at=ingested_at,
        source="UN Comtrade Preview API",
    )
