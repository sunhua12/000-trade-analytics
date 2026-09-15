import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx
from tenacity import wait_none

from trade_analytics.ingestion.client import ComtradeClient
from trade_analytics.ingestion.exceptions import (
    ComtradeAuthenticationError,
    ComtradeRequestError,
    ComtradeResponseError,
    ResponseTruncatedError,
)
from trade_analytics.ingestion.manifest import build_manifest, serialize_ndjson
from trade_analytics.ingestion.queries import ComtradeQuery, QueryType
from trade_analytics.ingestion.schemas import TradeRecord
from trade_analytics.ingestion.service import IngestionService

QUERY = ComtradeQuery(
    period="202401",
    cmd_code="8542",
    query_type=QueryType.PARTNER_DETAIL,
)


@respx.mock
def test_fetch_parses_successful_response(preview_payload: dict[str, Any]) -> None:
    route = respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(
        return_value=httpx.Response(200, json=preview_payload)
    )

    with httpx.Client() as http_client:
        response = ComtradeClient(http_client=http_client, wait=wait_none()).fetch(QUERY)

    assert response.count == 3
    assert route.call_count == 1


@respx.mock
def test_fetch_sends_monthly_import_query_parameters(preview_payload: dict[str, Any]) -> None:
    route = respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(
        return_value=httpx.Response(200, json=preview_payload)
    )

    with httpx.Client() as http_client:
        ComtradeClient(http_client=http_client, wait=wait_none()).fetch(QUERY)

    params = route.calls.last.request.url.params
    assert params["reporterCode"] == "842"
    assert params["period"] == "202401"
    assert params["cmdCode"] == "8542"
    assert params["flowCode"] == "M"


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
@respx.mock
def test_retryable_status_is_retried(
    status: int,
    preview_payload: dict[str, Any],
) -> None:
    route = respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(
        side_effect=[
            httpx.Response(status, headers={"Retry-After": "1"}),
            httpx.Response(200, json=preview_payload),
        ]
    )

    with httpx.Client() as http_client:
        response = ComtradeClient(http_client=http_client, wait=wait_none()).fetch(QUERY)

    assert response.count == 3
    assert route.call_count == 2


@respx.mock
def test_timeout_is_retried(preview_payload: dict[str, Any]) -> None:
    route = respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(
        side_effect=[
            httpx.ReadTimeout("read timed out"),
            httpx.Response(200, json=preview_payload),
        ]
    )

    with httpx.Client() as http_client:
        response = ComtradeClient(http_client=http_client, wait=wait_none()).fetch(QUERY)

    assert response.count == 3
    assert route.call_count == 2


@respx.mock
def test_retry_after_header_controls_retry_delay(preview_payload: dict[str, Any]) -> None:
    delays: list[float] = []
    respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, json=preview_payload),
        ]
    )

    with httpx.Client() as http_client:
        ComtradeClient(http_client=http_client, sleep=delays.append).fetch(QUERY)

    assert delays == [7.0]


@respx.mock
def test_missing_retry_after_uses_exponential_delay(preview_payload: dict[str, Any]) -> None:
    delays: list[float] = []
    respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, json=preview_payload),
        ]
    )

    with httpx.Client() as http_client:
        ComtradeClient(http_client=http_client, sleep=delays.append).fetch(QUERY)

    assert delays == [1.0]


@respx.mock
def test_retry_exhaustion_raises_request_error() -> None:
    route = respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(return_value=httpx.Response(503))

    with (
        httpx.Client() as http_client,
        pytest.raises(ComtradeRequestError, match="after 4 attempts"),
    ):
        ComtradeClient(http_client=http_client, wait=wait_none()).fetch(QUERY)

    assert route.call_count == 4


@pytest.mark.parametrize("status", [400, 404])
@respx.mock
def test_non_retryable_client_error_is_attempted_once(status: int) -> None:
    route = respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(return_value=httpx.Response(status))

    with httpx.Client() as http_client, pytest.raises(ComtradeRequestError, match=f"HTTP {status}"):
        ComtradeClient(http_client=http_client, wait=wait_none()).fetch(QUERY)

    assert route.call_count == 1


@pytest.mark.parametrize("status", [401, 403])
@respx.mock
def test_authentication_error_is_not_retried(status: int) -> None:
    route = respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(return_value=httpx.Response(status))

    with (
        httpx.Client() as http_client,
        pytest.raises(ComtradeAuthenticationError, match=f"HTTP {status}"),
    ):
        ComtradeClient(http_client=http_client, wait=wait_none()).fetch(QUERY)

    assert route.call_count == 1


@respx.mock
def test_count_at_preview_limit_is_rejected(preview_payload: dict[str, Any]) -> None:
    preview_payload["count"] = 500
    respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(
        return_value=httpx.Response(200, json=preview_payload)
    )

    with httpx.Client() as http_client, pytest.raises(ResponseTruncatedError, match="500"):
        ComtradeClient(http_client=http_client, wait=wait_none()).fetch(QUERY)


@respx.mock
def test_api_error_field_is_rejected(preview_payload: dict[str, Any]) -> None:
    preview_payload["error"] = "preview error"
    respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(
        return_value=httpx.Response(200, json=preview_payload)
    )

    with httpx.Client() as http_client, pytest.raises(ComtradeResponseError, match="preview error"):
        ComtradeClient(http_client=http_client, wait=wait_none()).fetch(QUERY)


@respx.mock
def test_invalid_json_is_rejected() -> None:
    respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(
        return_value=httpx.Response(200, content=b"not-json")
    )

    with httpx.Client() as http_client, pytest.raises(ComtradeResponseError, match="valid JSON"):
        ComtradeClient(http_client=http_client, wait=wait_none()).fetch(QUERY)


@respx.mock
def test_raw_decimal_survives_http_model_storage_and_sum(preview_payload: dict[str, Any]) -> None:
    for row in preview_payload["data"]:
        row["primaryValue"] = "DECIMAL_TOKEN"
    # Deliberately send a JSON number token, never a Python float.
    raw = json.dumps(preview_payload).replace('"DECIMAL_TOKEN"', "123456789012345678901.123456789")
    respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(return_value=httpx.Response(200, content=raw))
    with httpx.Client() as http_client:
        dataset = IngestionService(ComtradeClient(http_client=http_client)).fetch_dataset(QUERY)
    expected = Decimal("123456789012345678901.123456789")
    assert dataset.rows[0].primary_value == expected
    data = serialize_ndjson(dataset)
    rows = [json.loads(line) for line in data.splitlines()]
    assert rows[0]["primaryValue"] == str(expected)
    assert rows[1]["netWgt"] is None
    assert TradeRecord.model_validate(rows[0]).primary_value == expected
    manifest = build_manifest(dataset, data=data, ingested_at=datetime(2026, 9, 10, tzinfo=UTC))
    assert manifest.primary_value_sum == Decimal("246913578024691357802.246913578")


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity", "null", "-1"])
@respx.mock
def test_invalid_primary_amount_never_reaches_storage(
    preview_payload: dict[str, Any],
    token: str,
) -> None:
    preview_payload["data"][0]["primaryValue"] = "INVALID_TOKEN"
    raw = json.dumps(preview_payload).replace('"INVALID_TOKEN"', token)
    respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(return_value=httpx.Response(200, content=raw))
    with httpx.Client() as http_client, pytest.raises(ComtradeResponseError):
        IngestionService(ComtradeClient(http_client=http_client)).fetch_dataset(QUERY)
