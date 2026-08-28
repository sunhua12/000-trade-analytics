import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from trade_analytics.ingestion.manifest import build_manifest, checksum, serialize_ndjson
from trade_analytics.ingestion.queries import ComtradeQuery, QueryType
from trade_analytics.ingestion.schemas import ComtradeResponse
from trade_analytics.ingestion.service import IngestionDataset, IngestionService


class FakeClient:
    def __init__(self, response: ComtradeResponse) -> None:
        self.response = response

    def fetch(self, query: ComtradeQuery) -> ComtradeResponse:
        del query
        return self.response


def partner_dataset(preview_payload: dict[str, Any]) -> IngestionDataset:
    response = ComtradeResponse.model_validate(preview_payload)
    query = ComtradeQuery(
        period="202401",
        cmd_code="8542",
        query_type=QueryType.PARTNER_DETAIL,
    )
    return IngestionService(FakeClient(response)).fetch_dataset(query)


def test_serialization_is_independent_of_input_row_order(
    preview_payload: dict[str, Any],
) -> None:
    dataset = partner_dataset(preview_payload)
    reversed_dataset = replace(dataset, rows=tuple(reversed(dataset.rows)))

    first = serialize_ndjson(dataset)
    second = serialize_ndjson(reversed_dataset)

    assert first == second
    assert first.endswith(b"\n")
    assert len(first.splitlines()) == 2


def test_serialization_preserves_api_field_names_and_numeric_values(
    preview_payload: dict[str, Any],
) -> None:
    lines = serialize_ndjson(partner_dataset(preview_payload)).splitlines()
    records = [json.loads(line) for line in lines]

    assert [record["partnerCode"] for record in records] == [156, 410]
    assert [record["primaryValue"] for record in records] == [100.0, 200.0]
    assert "partner_code" not in records[0]


def test_checksum_uses_sha256_with_explicit_prefix() -> None:
    assert checksum(b"abc") == (
        "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_manifest_summarizes_dataset_without_float_drift(
    preview_payload: dict[str, Any],
) -> None:
    dataset = partner_dataset(preview_payload)
    data = serialize_ndjson(dataset)
    ingested_at = datetime(2026, 8, 28, tzinfo=UTC)

    manifest = build_manifest(dataset, data=data, ingested_at=ingested_at)

    assert manifest.request_parameters == dataset.query.to_params()
    assert manifest.checksum == checksum(data)
    assert manifest.schema_version == "1.0.0"
    assert manifest.hs_version == "H6"
    assert manifest.row_count == 2
    assert str(manifest.primary_value_sum) == "300.0"
    assert manifest.ingested_at == ingested_at
    assert manifest.source == "UN Comtrade Preview API"
