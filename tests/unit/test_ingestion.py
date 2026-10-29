"""Core API ingestion, serialization, storage, CLI and Lambda examples."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from botocore.exceptions import ClientError

from trade_analytics.ingestion.client import ComtradeClient
from trade_analytics.ingestion.manifest import build_manifest, checksum, serialize_ndjson
from trade_analytics.ingestion.queries import ComtradeQuery, QueryType
from trade_analytics.ingestion.s3_storage import S3Storage
from trade_analytics.ingestion.schemas import ComtradeResponse, TradeRecord
from trade_analytics.ingestion.service import IngestionDataset, validate_dataset
from trade_analytics.ingestion.storage import LocalStorage

QUERY = ComtradeQuery(period="202401", cmd_code="854231", query_type=QueryType.PARTNER_DETAIL)


@respx.mock
def test_raw_decimal_survives_http_model_storage_and_sum(preview_payload: dict[str, Any]) -> None:
    for row in preview_payload["data"]:
        row["primaryValue"] = "DECIMAL_TOKEN"
    raw = json.dumps(preview_payload).replace('"DECIMAL_TOKEN"', "123456789012345678901.123456789")
    respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(return_value=httpx.Response(200, content=raw))
    with httpx.Client() as http_client:
        dataset = validate_dataset(QUERY, ComtradeClient(http_client=http_client).fetch(QUERY))
    expected = Decimal("123456789012345678901.123456789")
    assert dataset.rows[0].primary_value == expected
    data = serialize_ndjson(dataset)
    rows = [json.loads(line) for line in data.splitlines()]
    assert rows[0]["primaryValue"] == str(expected)
    assert rows[1]["netWgt"] is None
    assert TradeRecord.model_validate(rows[0]).primary_value == expected
    manifest = build_manifest(dataset, data=data, ingested_at=datetime(2026, 9, 10, tzinfo=UTC))
    assert manifest.primary_value_sum == Decimal("246913578024691357802.246913578")


class FakeClient:
    def __init__(self, response: ComtradeResponse) -> None:
        self.response = response

    def fetch(self, query: ComtradeQuery) -> ComtradeResponse:
        del query
        return self.response


def partner_dataset(preview_payload: dict[str, Any]) -> IngestionDataset:
    response = ComtradeResponse.model_validate(preview_payload)
    query = ComtradeQuery(period="202401", cmd_code="854231", query_type=QueryType.PARTNER_DETAIL)
    return validate_dataset(query, response)


def test_manifest_summarizes_dataset_without_float_drift(preview_payload: dict[str, Any]) -> None:
    dataset = partner_dataset(preview_payload)
    data = serialize_ndjson(dataset)
    ingested_at = datetime(2026, 8, 28, tzinfo=UTC)
    manifest = build_manifest(dataset, data=data, ingested_at=ingested_at)
    assert manifest.request_parameters == dataset.query.to_params()
    assert manifest.checksum == checksum(data)
    assert manifest.schema_version == "2.0.0"
    assert manifest.hs_version == "H6"
    assert manifest.row_count == 2
    assert str(manifest.primary_value_sum) == "300.0"
    assert manifest.ingested_at == ingested_at
    assert manifest.source == "UN Comtrade Preview API"


def test_partner_detail_parameters_fix_us_monthly_import_scope() -> None:
    query = ComtradeQuery(period="202401", cmd_code="854231", query_type=QueryType.PARTNER_DETAIL)
    assert query.to_params() == {
        "reporterCode": 842,
        "period": "202401",
        "cmdCode": "854231",
        "flowCode": "M",
        "partner2Code": 0,
        "customsCode": "C00",
        "motCode": 0,
    }


FIXED_TIME = datetime(2026, 8, 29, tzinfo=UTC)


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.puts: list[dict[str, Any]] = []

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        object_id = (kwargs["Bucket"], kwargs["Key"])
        if object_id not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey", "Message": "missing"}}, "GetObject")
        return {"Body": BytesIO(self.objects[object_id])}

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.puts.append(kwargs)
        self.objects[kwargs["Bucket"], kwargs["Key"]] = kwargs["Body"]
        return {"ETag": '"fake-etag"'}


def test_s3_storage_returns_already_exists_without_rewriting_identical_artifacts(
    preview_payload: dict[str, Any],
    tmp_path: Path,
) -> None:
    dataset = partner_dataset(preview_payload)
    local = LocalStorage(tmp_path).write(dataset)
    fake_s3 = FakeS3()
    storage = S3Storage(bucket="raw-bucket", client=fake_s3)
    first = storage.write(local.data_path)
    fake_s3.puts.clear()
    rerun = storage.write(local.data_path)
    assert first.status == "success"
    assert rerun.status == "already_exists"
    assert rerun.checksum == first.checksum
    assert fake_s3.puts == []


FIXTURE = Path("tests/fixtures/comtrade_preview_response.json")


def test_preview_response_maps_camel_case_fields() -> None:
    payload = json.loads(FIXTURE.read_text())
    response = ComtradeResponse.model_validate(payload)
    assert response.count == 3
    assert response.data[0].reporter_code == 842
    assert response.data[0].primary_value == 100.0


PARTNER_QUERY = ComtradeQuery(
    period="202401", cmd_code="854231", query_type=QueryType.PARTNER_DETAIL
)


def parse_response(preview_payload: dict[str, Any]) -> ComtradeResponse:
    return ComtradeResponse.model_validate(preview_payload)


def test_partner_detail_excludes_world_row(preview_payload: dict[str, Any]) -> None:
    response = parse_response(preview_payload)
    dataset = validate_dataset(PARTNER_QUERY, response)
    assert {row.partner_code for row in dataset.rows} == {156, 410}
    assert dataset.query == PARTNER_QUERY


def test_local_rerun_preserves_bytes_and_timestamps(
    tmp_path: Path, preview_payload: dict[str, Any]
) -> None:
    dataset = partner_dataset(preview_payload)
    storage = LocalStorage(tmp_path)
    first = storage.write(dataset)
    paths = [first.data_path, first.manifest_path]
    before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths]
    assert storage.write(dataset).status == "already_exists"
    assert [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths] == before


@pytest.fixture
def live_service() -> Iterator[ComtradeClient]:
    timeout = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0)
    client = httpx.Client()
    service = ComtradeClient(http_client=client, timeout=timeout)
    yield service
    client.close()


@pytest.mark.integration
def test_live_partner_detail_contract(live_service: ComtradeClient) -> None:
    query = ComtradeQuery(period="202401", cmd_code="854231", query_type=QueryType.PARTNER_DETAIL)
    dataset = validate_dataset(query, live_service.fetch(query))
    assert 0 < len(dataset.rows) < ComtradeClient.PREVIEW_RECORD_LIMIT
    assert all(row.period == "202401" for row in dataset.rows)
    assert all(row.reporter_code == 842 for row in dataset.rows)
    assert all(row.flow_code == "M" for row in dataset.rows)
    assert all(row.partner_code != 0 for row in dataset.rows)
    assert all(row.cmd_code == "854231" for row in dataset.rows)


def test_local_interrupted_directory_install_is_not_committed(
    tmp_path, preview_payload, monkeypatch
):
    dataset = partner_dataset(preview_payload)
    monkeypatch.setattr(
        Path, "rename", lambda *args: (_ for _ in ()).throw(OSError("disk failure"))
    )
    with pytest.raises(OSError):
        LocalStorage(tmp_path).write(dataset)
    assert not list(tmp_path.rglob("data.ndjson"))
    assert not list(tmp_path.rglob("manifest.json"))


def test_s3_manifest_is_commit_marker_and_partial_upload_can_retry(preview_payload, tmp_path):
    dataset = partner_dataset(preview_payload)
    local = LocalStorage(tmp_path).write(dataset)
    s3 = FakeS3()
    original = s3.put_object

    def interrupted(**kwargs):
        if kwargs["Key"].endswith("manifest.json"):
            raise OSError("upload interrupted")
        return original(**kwargs)

    s3.put_object = interrupted
    storage = S3Storage(bucket="fixture", client=s3)
    with pytest.raises(OSError):
        storage.write(local.data_path)
    assert all(key.endswith("data.ndjson") for bucket, key in s3.objects)
    s3.put_object = original
    assert storage.write(local.data_path).status == "success"
    assert storage.write(local.data_path).status == "already_exists"


def test_s3_upload_uses_create_only_writes(preview_payload, tmp_path):
    storage_client = FakeS3()
    S3Storage(bucket="fixture", client=storage_client).write(
        LocalStorage(tmp_path).write(partner_dataset(preview_payload)).data_path
    )
    assert all(put["IfNoneMatch"] == "*" for put in storage_client.puts)
    assert storage_client.puts[-1]["Key"].endswith("manifest.json")


def test_s3_preserves_noncanonical_committed_bytes(preview_payload, tmp_path):
    from trade_analytics.ingestion.manifest import serialize_manifest

    local = LocalStorage(tmp_path).write(partner_dataset(preview_payload))
    # Valid NDJSON with different whitespace must not be reserialized during upload.
    data = b"".join(
        (json.dumps(json.loads(line), separators=(", ", ": ")) + "\n").encode()
        for line in local.data_path.read_bytes().splitlines()
    )
    from trade_analytics.ingestion.manifest import Manifest

    manifest = Manifest.model_validate_json(local.manifest_path.read_bytes())
    local.data_path.write_bytes(data)
    local.manifest_path.write_bytes(
        serialize_manifest(manifest.model_copy(update={"checksum": checksum(data)}))
    )
    client = FakeS3()
    S3Storage(bucket="fixture", client=client).write(local.data_path)
    assert client.puts[0]["Body"] == data
    assert client.puts[1]["Body"] == local.manifest_path.read_bytes()


def test_retired_commodity_rejected_and_zero_world_is_valid(preview_payload):
    with pytest.raises(ValueError, match="unsupported IC commodity"):
        ComtradeQuery(cmd_code="8542", query_type=QueryType.WORLD_TOTAL)
    preview_payload["data"] = [row for row in preview_payload["data"] if row["partnerCode"] == 0]
    preview_payload["data"][0]["primaryValue"] = "0"
    preview_payload["count"] = 1
    dataset = validate_dataset(
        ComtradeQuery(query_type=QueryType.WORLD_TOTAL),
        ComtradeResponse.model_validate(preview_payload),
    )
    assert dataset.rows[0].primary_value == 0
