from typing import Any

import pytest
from pydantic import ValidationError

from trade_analytics.ingestion.queries import ComtradeQuery, QueryType
from trade_analytics.ingestion.s3_storage import StoredS3Ingestion
from trade_analytics.lambda_handler import handler


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        query: ComtradeQuery,
        *,
        bucket: str,
        prefix: str,
        base_url: str,
    ) -> StoredS3Ingestion:
        self.calls.append(
            {
                "query": query,
                "bucket": bucket,
                "prefix": prefix,
                "base_url": base_url,
            }
        )
        return StoredS3Ingestion(
            status="success",
            data_uri="s3://raw-bucket/un_comtrade/data.ndjson",
            manifest_uri="s3://raw-bucket/un_comtrade/manifest.json",
            row_count=2,
            checksum="sha256:abc123",
        )


def test_handler_maps_a_valid_event_to_ingestion_and_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAW_BUCKET", "raw-bucket")
    monkeypatch.setenv("RAW_PREFIX", "custom-prefix")
    monkeypatch.setenv("COMTRADE_BASE_URL", "https://example.test/comtrade")
    runner = RecordingRunner()

    result = handler(
        {
            "action": "ingest",
            "period": "202401",
            "cmd_code": "8542",
            "query_type": "partner_detail",
            "run_id": "manual-test",
        },
        None,
        runner=runner,
    )

    assert runner.calls == [
        {
            "query": ComtradeQuery(
                period="202401",
                cmd_code="8542",
                query_type=QueryType.PARTNER_DETAIL,
            ),
            "bucket": "raw-bucket",
            "prefix": "custom-prefix",
            "base_url": "https://example.test/comtrade",
        }
    ]
    assert result == {
        "status": "success",
        "period": "202401",
        "query_type": "partner_detail",
        "row_count": 2,
        "checksum": "sha256:abc123",
        "data_uri": "s3://raw-bucket/un_comtrade/data.ndjson",
        "manifest_uri": "s3://raw-bucket/un_comtrade/manifest.json",
    }


@pytest.mark.parametrize(
    "event",
    [
        {"action": "unknown", "period": "202401", "query_type": "partner_detail"},
        {"action": "ingest", "period": "202413", "query_type": "partner_detail"},
        {"action": "ingest", "period": "202401", "query_type": "unknown"},
    ],
)
def test_handler_rejects_invalid_events_before_runtime_configuration(
    event: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RAW_BUCKET", raising=False)
    runner = RecordingRunner()

    with pytest.raises(ValidationError):
        handler(event, None, runner=runner)

    assert runner.calls == []


def test_handler_requires_raw_bucket_after_event_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RAW_BUCKET", raising=False)
    runner = RecordingRunner()

    with pytest.raises(RuntimeError, match="RAW_BUCKET"):
        handler(
            {"action": "ingest", "period": "202401", "query_type": "world_total"},
            None,
            runner=runner,
        )

    assert runner.calls == []
