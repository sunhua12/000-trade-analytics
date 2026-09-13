import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from typing import Any

import pytest
from botocore.exceptions import ClientError

from trade_analytics.ingestion.exceptions import StorageConflictError
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

    expected_root = (
        "un_comtrade/v2/hs_version=H6/cmd_code=8542/"
        "period=202401/query_type=partner_detail/revision=1"
    )
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


def test_s3_storage_returns_already_exists_without_rewriting_identical_artifacts(
    preview_payload: dict[str, Any],
) -> None:
    dataset = partner_dataset(preview_payload)
    fake_s3 = FakeS3()
    storage = S3Storage(
        bucket="raw-bucket",
        client=fake_s3,
        clock=lambda: FIXED_TIME,
    )
    first = storage.write(dataset)
    fake_s3.puts.clear()

    rerun = storage.write(dataset)

    assert first.status == "success"
    assert rerun.status == "already_exists"
    assert rerun.checksum == first.checksum
    assert fake_s3.puts == []


def test_s3_storage_rejects_conflicting_existing_data_without_overwriting(
    preview_payload: dict[str, Any],
) -> None:
    dataset = partner_dataset(preview_payload)
    fake_s3 = FakeS3()
    storage = S3Storage(
        bucket="raw-bucket",
        client=fake_s3,
        clock=lambda: FIXED_TIME,
    )
    storage.write(dataset)
    data_object = (
        "raw-bucket",
        "un_comtrade/v2/hs_version=H6/cmd_code=8542/period=202401/query_type=partner_detail/revision=1/data.ndjson",
    )
    fake_s3.objects[data_object] = b'{"conflicting":true}\n'
    snapshot = dict(fake_s3.objects)
    fake_s3.puts.clear()

    with pytest.raises(StorageConflictError, match="checksum conflict"):
        storage.write(dataset)

    assert fake_s3.objects == snapshot
    assert fake_s3.puts == []


def test_s3_storage_repairs_missing_manifest_without_rewriting_matching_data(
    preview_payload: dict[str, Any],
) -> None:
    dataset = partner_dataset(preview_payload)
    fake_s3 = FakeS3()
    storage = S3Storage(bucket="raw-bucket", client=fake_s3, clock=lambda: FIXED_TIME)
    storage.write(dataset)
    manifest_object = (
        "raw-bucket",
        "un_comtrade/v2/hs_version=H6/cmd_code=8542/period=202401/query_type=partner_detail/revision=1/manifest.json",
    )
    del fake_s3.objects[manifest_object]
    fake_s3.puts.clear()

    repaired = storage.write(dataset)

    assert repaired.status == "success"
    assert [item["Key"] for item in fake_s3.puts] == [manifest_object[1]]


def test_s3_storage_repairs_missing_data_without_rewriting_matching_manifest(
    preview_payload: dict[str, Any],
) -> None:
    dataset = partner_dataset(preview_payload)
    fake_s3 = FakeS3()
    storage = S3Storage(bucket="raw-bucket", client=fake_s3, clock=lambda: FIXED_TIME)
    storage.write(dataset)
    data_object = (
        "raw-bucket",
        "un_comtrade/v2/hs_version=H6/cmd_code=8542/period=202401/query_type=partner_detail/revision=1/data.ndjson",
    )
    del fake_s3.objects[data_object]
    fake_s3.puts.clear()

    repaired = storage.write(dataset)

    assert repaired.status == "success"
    assert [item["Key"] for item in fake_s3.puts] == [data_object[1]]


def test_s3_storage_rejects_conflicting_lone_data_object(
    preview_payload: dict[str, Any],
) -> None:
    dataset = partner_dataset(preview_payload)
    fake_s3 = FakeS3()
    data_key = (
        "un_comtrade/v2/hs_version=H6/cmd_code=8542/"
        "period=202401/query_type=partner_detail/revision=1/data.ndjson"
    )
    fake_s3.objects[("raw-bucket", data_key)] = b'{"wrong":true}\n'
    snapshot = dict(fake_s3.objects)
    storage = S3Storage(bucket="raw-bucket", client=fake_s3, clock=lambda: FIXED_TIME)

    with pytest.raises(StorageConflictError, match="checksum conflict"):
        storage.write(dataset)

    assert fake_s3.objects == snapshot
    assert fake_s3.puts == []


def test_s3_storage_rejects_conflicting_lone_manifest_object(
    preview_payload: dict[str, Any],
) -> None:
    dataset = partner_dataset(preview_payload)
    fake_s3 = FakeS3()
    manifest_key = (
        "un_comtrade/v2/hs_version=H6/cmd_code=8542/"
        "period=202401/query_type=partner_detail/revision=1/manifest.json"
    )
    fake_s3.objects[("raw-bucket", manifest_key)] = b"{}\n"
    snapshot = dict(fake_s3.objects)
    storage = S3Storage(bucket="raw-bucket", client=fake_s3, clock=lambda: FIXED_TIME)

    with pytest.raises(StorageConflictError, match="checksum conflict"):
        storage.write(dataset)

    assert fake_s3.objects == snapshot
    assert fake_s3.puts == []


@pytest.mark.parametrize("lone", [False, True])
@pytest.mark.parametrize(
    "field",
    [
        "period",
        "cmd_code",
        "revision",
        "row_count",
        "primary_value_sum",
        "request_parameters",
        "schema_version",
        "source",
    ],
)
def test_s3_manifest_identity_conflicts_do_not_write(
    preview_payload: dict[str, Any],
    field: str,
    lone: bool,
) -> None:
    dataset = partner_dataset(preview_payload)
    fake = FakeS3()
    storage = S3Storage(bucket="raw-bucket", client=fake)
    first = storage.write(dataset)
    manifest_key = ("raw-bucket", first.manifest_uri.removeprefix("s3://raw-bucket/"))
    data_key = ("raw-bucket", first.data_uri.removeprefix("s3://raw-bucket/"))
    payload = json.loads(fake.objects[manifest_key])
    payload[field] = (
        {} if field == "request_parameters" else 99 if field in {"revision", "row_count"} else "999"
    )
    fake.objects[manifest_key] = json.dumps(payload).encode()
    if lone:
        del fake.objects[data_key]
    before = dict(fake.objects)
    fake.puts.clear()
    with pytest.raises(StorageConflictError):
        storage.write(dataset)
    assert fake.objects == before
    assert fake.puts == []


def test_s3_changed_content_revision_and_commodity_isolation(
    preview_payload: dict[str, Any],
) -> None:
    dataset = partner_dataset(preview_payload)
    fake = FakeS3()
    storage = S3Storage(bucket="raw-bucket", client=fake)
    first = storage.write(dataset)
    before = dict(fake.objects)
    assert storage.write(dataset).status == "already_exists"
    assert fake.objects == before  # Includes the original ingestion timestamp.
    changed = replace(
        dataset,
        rows=(
            dataset.rows[0].model_copy(update={"primary_value": Decimal("101")}),
            *dataset.rows[1:],
        ),
    )
    with pytest.raises(StorageConflictError):
        storage.write(changed)
    revised = replace(changed, query=ComtradeQuery(query_type=QueryType.PARTNER_DETAIL, revision=2))
    second = storage.write(revised)
    assert second.data_uri != first.data_uri
    other = replace(
        dataset,
        query=ComtradeQuery(query_type=QueryType.PARTNER_DETAIL, cmd_code="854231"),
        rows=tuple(row.model_copy(update={"cmd_code": "854231"}) for row in dataset.rows),
    )
    assert storage.write(other).data_uri not in {first.data_uri, second.data_uri}
    assert all(fake.objects[key] == value for key, value in before.items())
