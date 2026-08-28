"""Resilient HTTP client for the UN Comtrade Preview API."""

from collections.abc import Callable
from time import sleep as sleep_seconds
from typing import Any

import httpx
from pydantic import ValidationError
from tenacity import RetryCallState, Retrying, retry_if_exception_type, stop_after_attempt
from tenacity.wait import wait_base

from trade_analytics.ingestion.exceptions import (
    ComtradeAuthenticationError,
    ComtradeRequestError,
    ComtradeResponseError,
    ResponseTruncatedError,
)
from trade_analytics.ingestion.queries import ComtradeQuery
from trade_analytics.ingestion.schemas import ComtradeResponse


class _RetryableRequestError(Exception):
    """Internal marker for request failures that may be retried."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class _RetryAfterOrExponential(wait_base):
    """Honor Retry-After when present, otherwise use bounded exponential wait."""

    def __call__(self, retry_state: RetryCallState) -> float:
        outcome = retry_state.outcome
        if outcome is not None:
            error = outcome.exception()
            if isinstance(error, _RetryableRequestError) and error.retry_after is not None:
                return error.retry_after
        return float(min(2 ** max(retry_state.attempt_number - 1, 0), 8))


class ComtradeClient:
    """Fetch and parse monthly U.S. import records from the Preview API."""

    DEFAULT_BASE_URL = "https://comtradeapi.un.org/public/v1/preview/C/M/HS"
    MAX_ATTEMPTS = 4
    PREVIEW_RECORD_LIMIT = 500

    def __init__(
        self,
        *,
        http_client: httpx.Client,
        base_url: str = DEFAULT_BASE_URL,
        timeout: httpx.Timeout | float = 30.0,
        wait: wait_base | Callable[[RetryCallState], float] | None = None,
        sleep: Callable[[float], None] = sleep_seconds,
    ) -> None:
        self._http_client = http_client
        self._base_url = base_url
        self._timeout = timeout
        self._wait = wait or _RetryAfterOrExponential()
        self._sleep = sleep

    def fetch(self, query: ComtradeQuery) -> ComtradeResponse:
        """Fetch one validated Preview API response."""
        retrying = Retrying(
            stop=stop_after_attempt(self.MAX_ATTEMPTS),
            retry=retry_if_exception_type(_RetryableRequestError),
            wait=self._wait,
            sleep=self._sleep,
            reraise=True,
        )
        try:
            for attempt in retrying:
                with attempt:
                    return self._request(query)
        except _RetryableRequestError as error:
            raise ComtradeRequestError(
                f"UN Comtrade request failed after {self.MAX_ATTEMPTS} attempts: {error}"
            ) from error
        raise AssertionError("retry loop completed without a response")

    def _request(self, query: ComtradeQuery) -> ComtradeResponse:
        try:
            response = self._http_client.get(
                self._base_url,
                params=query.to_params(),
                timeout=self._timeout,
            )
        except (httpx.TimeoutException, httpx.TransportError) as error:
            raise _RetryableRequestError(type(error).__name__) from error

        self._raise_for_status(response)
        payload = self._decode_payload(response)
        try:
            parsed = ComtradeResponse.model_validate(payload)
        except ValidationError as error:
            raise ComtradeResponseError(
                "UN Comtrade response violated the response schema"
            ) from error

        if parsed.error:
            raise ComtradeResponseError(f"UN Comtrade API error: {parsed.error}")
        if parsed.count >= self.PREVIEW_RECORD_LIMIT:
            raise ResponseTruncatedError(
                f"Preview response count {parsed.count} reached the "
                f"{self.PREVIEW_RECORD_LIMIT}-row limit"
            )
        return parsed

    @staticmethod
    def _decode_payload(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as error:
            raise ComtradeResponseError("UN Comtrade response was not valid JSON") from error
        if not isinstance(payload, dict):
            raise ComtradeResponseError("UN Comtrade response must be a JSON object")
        return payload

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        status = response.status_code
        if status in {401, 403}:
            raise ComtradeAuthenticationError(
                f"UN Comtrade authentication failed with HTTP {status}"
            )
        if status == 429 or status in {500, 502, 503, 504}:
            raise _RetryableRequestError(
                f"HTTP {status}",
                retry_after=ComtradeClient._parse_retry_after(response.headers.get("Retry-After")),
            )
        if status >= 400:
            raise ComtradeRequestError(f"UN Comtrade request failed with HTTP {status}")

    @staticmethod
    def _parse_retry_after(value: str | None) -> float | None:
        if value is None:
            return None
        try:
            delay = float(value)
        except ValueError:
            return None
        return max(delay, 0.0)
