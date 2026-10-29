"""Stable process exit codes for Airflow's selective retry policy."""

import json
import sys

import httpx
from botocore.exceptions import (
    ClientError,
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)

from trade_analytics.ingestion.exceptions import ComtradeTransientError

TRANSIENT_EXIT_CODE = 75


def is_transient(error: Exception) -> bool:
    if isinstance(error, (ComtradeTransientError, httpx.TransportError)):
        return True
    if isinstance(error, ClientError):
        response = error.response
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
        code = str(response.get("Error", {}).get("Code", ""))
        return (
            status == 429
            or status >= 500
            or code
            in {
                "PreconditionFailed",
                "ConditionalRequestConflict",
                "TooManyRequestsException",
                "Throttling",
                "ThrottlingException",
                "RequestLimitExceeded",
            }
        )
    if isinstance(
        error,
        (ConnectionClosedError, ConnectTimeoutError, EndpointConnectionError, ReadTimeoutError),
    ):
        return True
    return type(error).__name__ in {
        "WriterBusyError",
        "TooManyRequests",
        "ServiceUnavailable",
        "DeadlineExceeded",
        "InternalServerError",
    }


def exit_for_error(error: Exception) -> int:
    transient = is_transient(error)
    print(
        json.dumps(
            {
                "event": "pipeline_step_failed",
                "error_type": type(error).__name__,
                "retryable": transient,
            },
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    return TRANSIENT_EXIT_CODE if transient else 1
