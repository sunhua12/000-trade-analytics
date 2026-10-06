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

from trade_analytics.ingestion import cli
from trade_analytics.ingestion.client import ComtradeClient
from trade_analytics.ingestion.manifest import build_manifest, checksum, serialize_ndjson
from trade_analytics.ingestion.queries import ComtradeQuery, QueryType
from trade_analytics.ingestion.s3_storage import S3Storage, StoredS3Ingestion
from trade_analytics.ingestion.schemas import ComtradeResponse, TradeRecord
from trade_analytics.ingestion.service import IngestionDataset, IngestionService
from trade_analytics.ingestion.storage import LocalStorage, StoredIngestion
from trade_analytics.lambda_handler import handler

QUERY = ComtradeQuery(period="202401", cmd_code="8542", query_type=QueryType.PARTNER_DETAIL)


@respx.mock
def test_raw_decimal_survives_http_model_storage_and_sum(preview_payload: dict[str, Any]) -> None:
    for row in preview_payload["data"]:
        row["primaryValue"] = "DECIMAL_TOKEN"
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


class FakeClient:
    def __init__(self, response: ComtradeResponse) -> None:
        self.response = response

    def fetch(self, query: ComtradeQuery) -> ComtradeResponse:
        del query
        return self.response


def partner_dataset(preview_payload: dict[str, Any]) -> IngestionDataset:
    response = ComtradeResponse.model_validate(preview_payload)
    query = ComtradeQuery(period="202401", cmd_code="8542", query_type=QueryType.PARTNER_DETAIL)
    return IngestionService(FakeClient(response)).fetch_dataset(query)


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
    query = ComtradeQuery(period="202401", cmd_code="8542", query_type=QueryType.PARTNER_DETAIL)
    assert query.to_params() == {
        "reporterCode": 842,
        "period": "202401",
        "cmdCode": "8542",
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
) -> None:
    dataset = partner_dataset(preview_payload)
    fake_s3 = FakeS3()
    storage = S3Storage(bucket="raw-bucket", client=fake_s3, clock=lambda: FIXED_TIME)
    first = storage.write(dataset)
    fake_s3.puts.clear()
    rerun = storage.write(dataset)
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


PARTNER_QUERY = ComtradeQuery(period="202401", cmd_code="8542", query_type=QueryType.PARTNER_DETAIL)


def parse_response(preview_payload: dict[str, Any]) -> ComtradeResponse:
    return ComtradeResponse.model_validate(preview_payload)


def test_partner_detail_excludes_world_row(preview_payload: dict[str, Any]) -> None:
    response = parse_response(preview_payload)
    dataset = IngestionService(FakeClient(response)).fetch_dataset(PARTNER_QUERY)
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


def successful_result(output_dir: Path, query: ComtradeQuery) -> StoredIngestion:
    target = output_dir / f"period={query.period}" / f"query_type={query.query_type.value}"
    return StoredIngestion(
        data_path=target / "data.ndjson",
        manifest_path=target / "manifest.json",
        row_count=2,
        checksum="sha256:abc123",
    )


def test_cli_uses_default_period_and_commodity(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    captured: list[ComtradeQuery] = []

    def runner(query: ComtradeQuery, output_dir: Path) -> StoredIngestion:
        captured.append(query)
        return successful_result(output_dir, query)

    exit_code = cli.main(
        ["--query-type", "partner_detail", "--output-dir", str(tmp_path)], runner=runner
    )
    assert exit_code == 0
    assert captured == [
        ComtradeQuery(period="202401", cmd_code="8542", query_type=QueryType.PARTNER_DETAIL)
    ]
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "status": "success",
        "period": "202401",
        "query_type": "partner_detail",
        "row_count": 2,
        "data_path": str(tmp_path / "period=202401" / "query_type=partner_detail" / "data.ndjson"),
        "manifest_path": str(
            tmp_path / "period=202401" / "query_type=partner_detail" / "manifest.json"
        ),
        "checksum": "sha256:abc123",
    }


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self, query: ComtradeQuery, *, bucket: str, prefix: str, base_url: str
    ) -> StoredS3Ingestion:
        self.calls.append(
            {"query": query, "bucket": bucket, "prefix": prefix, "base_url": base_url}
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
                period="202401", cmd_code="8542", query_type=QueryType.PARTNER_DETAIL
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


@pytest.fixture
def live_service() -> Iterator[IngestionService]:
    timeout = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0)
    client = httpx.Client()
    service = IngestionService(ComtradeClient(http_client=client, timeout=timeout))
    yield service
    client.close()


@pytest.mark.integration
def test_live_partner_detail_contract(live_service: IngestionService) -> None:
    query = ComtradeQuery(period="202401", cmd_code="8542", query_type=QueryType.PARTNER_DETAIL)
    dataset = live_service.fetch_dataset(query)
    assert 0 < len(dataset.rows) < ComtradeClient.PREVIEW_RECORD_LIMIT
    assert all(row.period == "202401" for row in dataset.rows)
    assert all(row.reporter_code == 842 for row in dataset.rows)
    assert all(row.flow_code == "M" for row in dataset.rows)
    assert all(row.partner_code != 0 for row in dataset.rows)
    assert all(row.cmd_code == "8542" for row in dataset.rows)
