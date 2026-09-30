"""Only transient remote failures should trigger an Airflow task retry."""

import httpx

from scripts.pipeline_exit import TRANSIENT_EXIT_CODE, exit_for_error
from trade_analytics.ingestion.exceptions import (
    ComtradeAuthenticationError,
    ComtradeRequestError,
    ComtradeTransientError,
    StorageConflictError,
)


def test_retryable_and_permanent_exit_codes() -> None:
    assert exit_for_error(ComtradeTransientError("429")) == TRANSIENT_EXIT_CODE
    assert exit_for_error(httpx.ReadTimeout("timeout")) == TRANSIENT_EXIT_CODE
    assert exit_for_error(ComtradeRequestError("HTTP 400")) == 1
    assert exit_for_error(ComtradeAuthenticationError("HTTP 401")) == 1
    assert exit_for_error(StorageConflictError("checksum conflict")) == 1
