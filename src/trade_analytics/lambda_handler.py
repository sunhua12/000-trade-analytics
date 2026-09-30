"""AWS Lambda adapter for monthly UN Comtrade ingestion."""

import json
import os
from typing import Literal, Protocol
from uuid import uuid4

import boto3
import httpx
from pydantic import BaseModel, ConfigDict, Field

from trade_analytics.ingestion.client import ComtradeClient
from trade_analytics.ingestion.exceptions import (
    ComtradeResponseError,
    ResponseTruncatedError,
    StorageConflictError,
)
from trade_analytics.ingestion.queries import ComtradeQuery, QueryType
from trade_analytics.ingestion.s3_storage import S3Storage, StoredS3Ingestion
from trade_analytics.ingestion.service import IngestionService


class LambdaEvent(BaseModel):
    """Validated public event contract for one ingestion invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Literal["ingest"]
    period: str
    cmd_code: str = "8542"
    query_type: QueryType
    run_id: str | None = None
    revision: int = Field(default=1, gt=0, strict=True)


class IngestionRunner(Protocol):
    """Callable boundary used to isolate runtime clients in unit tests."""

    def __call__(
        self,
        query: ComtradeQuery,
        *,
        bucket: str,
        prefix: str,
        base_url: str,
    ) -> StoredS3Ingestion:
        """Fetch, validate, and store one logical dataset."""
        ...


def run_ingestion(
    query: ComtradeQuery,
    *,
    bucket: str,
    prefix: str,
    base_url: str,
) -> StoredS3Ingestion:
    """Compose real HTTP and AWS clients for one Lambda invocation."""
    timeout = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0)
    with httpx.Client() as http_client:
        client = ComtradeClient(
            http_client=http_client,
            base_url=base_url,
            timeout=timeout,
        )
        dataset = IngestionService(client).fetch_dataset(query)
    return S3Storage(
        bucket=bucket,
        prefix=prefix,
        client=boto3.client("s3"),
    ).write(dataset)


def handler(
    event: dict[str, object],
    context: object,
    *,
    runner: IngestionRunner = run_ingestion,
) -> dict[str, object]:
    """Validate an AWS event and run one monthly ingestion."""
    run_id = event.get("run_id") if isinstance(event.get("run_id"), str) else None
    run_id = run_id or f"lambda-{uuid4().hex}"
    request_id = getattr(context, "aws_request_id", None)
    identity = {
        "run_id": run_id,
        "aws_request_id": request_id,
        "period": event.get("period") if isinstance(event.get("period"), str) else None,
        "query_type": event.get("query_type") if isinstance(event.get("query_type"), str) else None,
        "revision": event.get("revision", 1) if type(event.get("revision", 1)) is int else None,
    }
    print(
        json.dumps({"event": "ingestion_started", **identity}, ensure_ascii=False, sort_keys=True),
        flush=True,
    )
    try:
        validated = LambdaEvent.model_validate(event)
        query = ComtradeQuery(
            period=validated.period,
            cmd_code=validated.cmd_code,
            query_type=validated.query_type,
            revision=validated.revision,
        )
        bucket = os.environ.get("RAW_BUCKET", "").strip()
        if not bucket:
            raise RuntimeError("RAW_BUCKET environment variable is required")
        stored = runner(
            query,
            bucket=bucket,
            prefix=os.environ.get("RAW_PREFIX", "un_comtrade"),
            base_url=os.environ.get("COMTRADE_BASE_URL", ComtradeClient.DEFAULT_BASE_URL),
        )
        result: dict[str, object] = {
            "status": stored.status,
            "period": query.period,
            "query_type": query.query_type.value,
            "row_count": stored.row_count,
            "checksum": stored.checksum,
            "data_uri": stored.data_uri,
            "manifest_uri": stored.manifest_uri,
        }
        print(
            json.dumps(
                {"event": "ingestion_succeeded", **identity, **result},
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )
        return result
    except Exception as error:
        if isinstance(error, ResponseTruncatedError):
            category = "ResponseTruncatedError"
        elif isinstance(error, ComtradeResponseError):
            category = "ComtradeResponseError"
        elif isinstance(error, StorageConflictError):
            category = "StorageConflictError"
        else:
            category = "Other"
        print(
            json.dumps(
                {
                    "event": "ingestion_failed",
                    **identity,
                    "error_type": type(error).__name__,
                    "error_category": category,
                    "message": "Ingestion failed; inspect error_type and request ID.",
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )
        raise
