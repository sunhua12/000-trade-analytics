import json
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

from botocore.exceptions import ClientError

from trade_analytics.ingestion.manifest import serialize_ndjson
from trade_analytics.ingestion.queries import ComtradeQuery, QueryType
from trade_analytics.ingestion.s3_storage import S3Storage
from trade_analytics.ingestion.schemas import ComtradeResponse
from trade_analytics.ingestion.service import IngestionDataset, IngestionService

FIXED_TIME = datetime(2026, 8, 29, tzinfo=UTC)


class FakeClient:
    def __init__(self, response: ComtradeResponse) -> None:
        self.response = response

    def fetch(self, query: ComtradeQuery) -> ComtradeResponse:
        del query
        return self.response


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.puts: list[dict[str, Any]] = []

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        object_id = (kwargs["Bucket"], kwargs["Key"])
        if object_id not in self.objects:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "missing"}},
                "GetObject",
            )
        return {"Body": BytesIO(self.objects[object_id])}

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.puts.append(kwargs)
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = kwargs["Body"]
        return {"ETag": '"fake-etag"'}


def partner_dataset(preview_payload: dict[str, Any]) -> IngestionDataset:
    response = ComtradeResponse.model_validate(preview_payload)
    query = ComtradeQuery(
        period="202401",
        cmd_code="8542",
        query_type=QueryType.PARTNER_DETAIL,
    )
    return IngestionService(FakeClient(response)).fetch_dataset(query)


def test_s3_storage_writes_stable_partitioned_artifacts(
    preview_payload: dict[str, Any],
) -> None:
    dataset = partner_dataset(preview_payload)
    fake_s3 = FakeS3()

    stored = S3Storage(
        bucket="raw-bucket",
        prefix="/un_comtrade/",
        client=fake_s3,
        clock=lambda: FIXED_TIME,
    ).write(dataset)

    expected_root = "un_comtrade/period=202401/query_type=partner_detail"
    assert stored.status == "success"
    assert stored.data_uri == f"s3://raw-bucket/{expected_root}/data.ndjson"
    assert stored.manifest_uri == f"s3://raw-bucket/{expected_root}/manifest.json"
    assert stored.row_count == 2
    assert stored.checksum.startswith("sha256:")
    assert [item["Key"] for item in fake_s3.puts] == [
        f"{expected_root}/data.ndjson",
        f"{expected_root}/manifest.json",
    ]
    assert [item["ContentType"] for item in fake_s3.puts] == [
        "application/x-ndjson",
        "application/json",
    ]
    assert fake_s3.puts[0]["Body"] == serialize_ndjson(dataset)
    manifest = json.loads(fake_s3.puts[1]["Body"])
    assert manifest["checksum"] == stored.checksum
    assert manifest["ingested_at"] == "2026-08-29T00:00:00Z"
