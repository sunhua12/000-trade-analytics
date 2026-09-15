from typing import Any

import pytest

from trade_analytics.ingestion.exceptions import DataContractError, EmptyDataError
from trade_analytics.ingestion.queries import ComtradeQuery, QueryType
from trade_analytics.ingestion.schemas import ComtradeResponse
from trade_analytics.ingestion.service import IngestionService

PARTNER_QUERY = ComtradeQuery(
    period="202401",
    cmd_code="8542",
    query_type=QueryType.PARTNER_DETAIL,
)
WORLD_QUERY = ComtradeQuery(
    period="202401",
    cmd_code="8542",
    query_type=QueryType.WORLD_TOTAL,
)


class FakeClient:
    def __init__(self, response: ComtradeResponse) -> None:
        self.response = response

    def fetch(self, query: ComtradeQuery) -> ComtradeResponse:
        del query
        return self.response


def parse_response(preview_payload: dict[str, Any]) -> ComtradeResponse:
    return ComtradeResponse.model_validate(preview_payload)


def test_partner_detail_excludes_world_row(preview_payload: dict[str, Any]) -> None:
    response = parse_response(preview_payload)

    dataset = IngestionService(FakeClient(response)).fetch_dataset(PARTNER_QUERY)

    assert {row.partner_code for row in dataset.rows} == {156, 410}
    assert dataset.query == PARTNER_QUERY


def test_world_total_contains_exactly_one_world_row(preview_payload: dict[str, Any]) -> None:
    world_row = preview_payload["data"][2]
    response = parse_response({**preview_payload, "count": 1, "data": [world_row]})

    dataset = IngestionService(FakeClient(response)).fetch_dataset(WORLD_QUERY)

    assert len(dataset.rows) == 1
    assert dataset.rows[0].partner_code == 0


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("period", "202402", "period"),
        ("reporterCode", 124, "reporter"),
        ("flowCode", "X", "flow"),
        ("cmdCode", "8541", "commodity"),
    ],
)
def test_mismatched_core_contract_is_rejected(
    preview_payload: dict[str, Any],
    field: str,
    value: str | int,
    message: str,
) -> None:
    preview_payload["data"][0][field] = value
    response = parse_response(preview_payload)

    with pytest.raises(DataContractError, match=message):
        IngestionService(FakeClient(response)).fetch_dataset(PARTNER_QUERY)


def test_partner_detail_rejects_duplicate_grain(preview_payload: dict[str, Any]) -> None:
    duplicate = preview_payload["data"][0].copy()
    preview_payload["data"].append(duplicate)
    preview_payload["count"] = 4
    response = parse_response(preview_payload)

    with pytest.raises(DataContractError, match="duplicate"):
        IngestionService(FakeClient(response)).fetch_dataset(PARTNER_QUERY)


def test_partner_detail_rejects_empty_result_after_world_is_removed(
    preview_payload: dict[str, Any],
) -> None:
    world_row = preview_payload["data"][2]
    response = parse_response({**preview_payload, "count": 1, "data": [world_row]})

    with pytest.raises(EmptyDataError, match="partner_detail"):
        IngestionService(FakeClient(response)).fetch_dataset(PARTNER_QUERY)


def test_world_total_rejects_non_world_rows(preview_payload: dict[str, Any]) -> None:
    response = parse_response(preview_payload)

    with pytest.raises(DataContractError, match="non-world"):
        IngestionService(FakeClient(response)).fetch_dataset(WORLD_QUERY)


def test_world_total_rejects_multiple_world_rows(preview_payload: dict[str, Any]) -> None:
    world_row = preview_payload["data"][2]
    response = parse_response({**preview_payload, "count": 2, "data": [world_row, world_row]})

    with pytest.raises(DataContractError, match="exactly one"):
        IngestionService(FakeClient(response)).fetch_dataset(WORLD_QUERY)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("classificationCode", "H5"),
        ("freqCode", "A"),
        ("partner2Code", 1),
        ("customsCode", "C01"),
        ("motCode", 1),
        ("primaryValue", None),
        ("primaryValue", -1),
    ],
)
def test_day3_contract_rejects_invalid_rows(
    preview_payload: dict[str, Any],
    field: str,
    value: object,
) -> None:
    preview_payload["data"][0][field] = value
    response = parse_response(preview_payload)
    with pytest.raises(DataContractError):
        IngestionService(FakeClient(response)).fetch_dataset(PARTNER_QUERY)


def test_world_zero_value_is_rejected(preview_payload: dict[str, Any]) -> None:
    row = preview_payload["data"][2]
    row["primaryValue"] = 0
    response = parse_response({"count": 1, "data": [row]})
    with pytest.raises(DataContractError):
        IngestionService(FakeClient(response)).fetch_dataset(WORLD_QUERY)


def test_zero_detail_and_special_partner_with_missing_metadata_are_retained(
    preview_payload: dict[str, Any],
) -> None:
    row = preview_payload["data"][0]
    row.update(partnerCode=490, primaryValue=0, netWgt=None, partnerISO=None, partnerDesc=None)
    dataset = IngestionService(FakeClient(parse_response(preview_payload))).fetch_dataset(
        PARTNER_QUERY
    )
    assert dataset.rows[1].partner_code == 410
    assert dataset.rows[0].partner_code == 490
    assert dataset.rows[0].primary_value == 0
