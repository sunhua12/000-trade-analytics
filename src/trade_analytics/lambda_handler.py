"""AWS Lambda adapter for monthly UN Comtrade ingestion."""

import json
import logging
import os
from typing import Literal, Protocol

import boto3  # type: ignore[import-untyped]
import httpx
from pydantic import BaseModel, ConfigDict

from trade_analytics.ingestion.client import ComtradeClient
from trade_analytics.ingestion.queries import ComtradeQuery, QueryType
from trade_analytics.ingestion.s3_storage import S3Storage, StoredS3Ingestion
from trade_analytics.ingestion.service import IngestionService

LOGGER = logging.getLogger(__name__)


class LambdaEvent(BaseModel):
    """Validated public event contract for one ingestion invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Literal["ingest"]
    period: str
    cmd_code: str = "8542"
    query_type: QueryType
    run_id: str | None = None


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
    del context
    validated = LambdaEvent.model_validate(event)
    query = ComtradeQuery(
        period=validated.period,
        cmd_code=validated.cmd_code,
        query_type=validated.query_type,
    )

    bucket = os.environ.get("RAW_BUCKET", "").strip()
    if not bucket:
        raise RuntimeError("RAW_BUCKET environment variable is required")
    prefix = os.environ.get("RAW_PREFIX", "un_comtrade")
    base_url = os.environ.get("COMTRADE_BASE_URL", ComtradeClient.DEFAULT_BASE_URL)

    stored = runner(
        query,
        bucket=bucket,
        prefix=prefix,
        base_url=base_url,
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
    LOGGER.info(
        json.dumps(
            {
                "run_id": validated.run_id,
                **result,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return result
