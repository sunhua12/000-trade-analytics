"""Regression tests for cross-market identity, original editions, and v2 isolation."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_ingestion import FakeClient
from trade_analytics.ingestion.manifest import (
    artifact_partition,
    build_manifest,
    serialize_manifest,
    serialize_ndjson,
)
from trade_analytics.ingestion.multi_market import accept_response, periods
from trade_analytics.ingestion.queries import ComtradeQuery, QueryType
from trade_analytics.ingestion.schemas import ComtradeResponse
from trade_analytics.ingestion.service import IngestionService
from trade_analytics.warehouse.source_validation import verify


def test_partition_and_verifier_isolate_markets(preview_payload: dict[str, Any]) -> None:
    paths = []
    for reporter in (842, 156):
        payload = json.loads(json.dumps(preview_payload))
        for row in payload["data"]:
            row.update(
                reporterCode=reporter,
                cmdCode="854231",
                classificationCode="H4",
                isOriginalClassification=True,
            )
        query = ComtradeQuery(
            period="202401",
            reporter_code=reporter,
            cmd_code="854231",
            expected_hs_version="H4",
            query_type=QueryType.PARTNER_DETAIL,
        )
        response = ComtradeResponse.model_validate(payload)
        assert accept_response(query, response).expected_hs_version == "H4"
        dataset = IngestionService(FakeClient(response)).fetch_dataset(query)
        data = serialize_ndjson(dataset)
        manifest = build_manifest(dataset, data=data, ingested_at=datetime.now(UTC))
        partition = artifact_partition(query)
        paths.append(partition)
        result = verify(
            data, serialize_manifest(manifest), f"s3://test/un_comtrade/{partition}/data.ndjson"
        )
        assert {row["reporter_code"] for row in result["expected"]} == {str(reporter)}
    assert paths[0] != paths[1]


def test_periods_cover_year_boundary_and_reject_invalid_scope() -> None:
    assert periods("201611", "201702") == ["201611", "201612", "201701", "201702"]
    with pytest.raises(ValueError):
        periods("201512", "201601")
    with pytest.raises(ValueError):
        periods("202401", "202313")


def test_quota_403_honors_retry_after(preview_payload: dict[str, Any]) -> None:
    import httpx
    import respx

    from trade_analytics.ingestion.client import ComtradeClient

    waits = []
    with respx.mock:
        route = respx.get(ComtradeClient.DEFAULT_BASE_URL)
        route.side_effect = [
            httpx.Response(403, headers={"Retry-After": "890"}),
            httpx.Response(200, json=preview_payload),
        ]
        with httpx.Client() as http:
            response = ComtradeClient(http_client=http, sleep=waits.append).fetch(
                ComtradeQuery(period="202401", query_type=QueryType.PARTNER_DETAIL)
            )
    assert response.data
    assert waits == [890.0]


def test_batch_resume_keeps_numeric_precision(preview_payload: dict[str, Any]) -> None:
    import json
    from decimal import Decimal

    from trade_analytics.warehouse.batch_loader import BatchRawLoader
    from trade_analytics.warehouse.loader import expected_rows

    amount = "12345678901234567890.123456789"
    for row in preview_payload["data"]:
        row.update(
            cmdCode="854231",
            classificationCode="H4",
            isOriginalClassification=True,
            primaryValue=amount,
        )
    response = ComtradeResponse.model_validate(preview_payload)
    query = ComtradeQuery(
        period="202401",
        cmd_code="854231",
        expected_hs_version="H4",
        query_type=QueryType.PARTNER_DETAIL,
    )
    dataset = IngestionService(FakeClient(response)).fetch_dataset(query)
    data = serialize_ndjson(dataset)
    manifest = build_manifest(dataset, data=data, ingested_at=datetime.now(UTC))
    source = verify(
        data,
        serialize_manifest(manifest),
        f"s3://test/un_comtrade/{artifact_partition(query)}/data.ndjson",
    )
    existing = expected_rows(source, "old-run")

    class FakeBatchLoader(BatchRawLoader):
        def query(self, sql: str, params: dict[str, str]) -> list[dict[str, Any]]:
            assert sql.strip().startswith("SELECT"), "resume must not write"
            if "un_comtrade_world_total" in sql:
                return []
            return [
                {
                    "payload": json.dumps(row, default=str).replace(
                        f'"primary_value": "{amount}"', f'"primary_value": {amount}'
                    )
                }
                for row in existing
            ]

    loader = FakeBatchLoader(None, None)
    assert loader.load_month("202401", [source])["status"] == "already_loaded"
    assert Decimal(amount) == dataset.rows[0].primary_value


def test_authenticated_client_requests_full_limit_without_key_in_url(
    preview_payload: dict[str, Any],
) -> None:
    import httpx
    import respx

    from trade_analytics.ingestion.client import ComtradeClient

    with respx.mock:
        route = respx.get("https://comtradeapi.un.org/data/v1/get/C/M/HS").mock(
            return_value=httpx.Response(200, json=preview_payload)
        )
        with httpx.Client() as http:
            ComtradeClient(http_client=http, api_key="test-only-key").fetch(
                ComtradeQuery(period="202401", query_type=QueryType.PARTNER_DETAIL)
            )
        request = route.calls.last.request
        assert request.url.params["maxRecords"] == "100000"
        assert request.headers["Ocp-Apim-Subscription-Key"] == "test-only-key"
        assert "test-only-key" not in str(request.url)


def test_source_audit_selects_whole_revision_before_counting(
    preview_payload: dict[str, Any], tmp_path: Path
) -> None:
    from trade_analytics.ingestion.audit import audit_sources
    from trade_analytics.ingestion.storage import LocalStorage

    reference = tmp_path / "countries.csv"
    reference.write_text(
        "partner_code,partner_type,classification_status\n156,country,verified\n392,country,verified\n"
    )
    preview_payload["data"] = [row for row in preview_payload["data"] if row["partnerCode"] != 0][
        :2
    ]
    preview_payload["count"] = len(preview_payload["data"])
    for index, row in enumerate(preview_payload["data"]):
        row.update(
            reporterCode=842,
            partnerCode=(156, 392)[index],
            cmdCode="854231",
            classificationCode="H4",
            isOriginalClassification=True,
        )
    query = ComtradeQuery(
        period="202401",
        cmd_code="854231",
        expected_hs_version="H4",
        query_type=QueryType.PARTNER_DETAIL,
    )
    service = IngestionService(FakeClient(ComtradeResponse.model_validate(preview_payload)))
    LocalStorage(tmp_path).write(service.fetch_dataset(query))
    preview_payload["data"] = preview_payload["data"][:1]
    preview_payload["count"] = 1
    preview_payload["data"][0]["classificationCode"] = "H5"
    updated = query.model_copy(update={"expected_hs_version": "H5", "revision": 2})
    service = IngestionService(FakeClient(ComtradeResponse.model_validate(preview_payload)))
    LocalStorage(tmp_path).write(service.fetch_dataset(updated))
    result = audit_sources(tmp_path, reference)
    assert result["valid_detail_count"] == 1
    assert result["accepted_extracts"] == 1
    assert result["hs_version_counts"] == {"H5": 1}


def test_lambda_forwards_market_and_historical_edition(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.unit.test_ingestion import RecordingRunner
    from trade_analytics.lambda_handler import handler

    monkeypatch.setenv("RAW_BUCKET", "test-bucket")
    runner = RecordingRunner()
    result = handler(
        {
            "action": "ingest",
            "period": "201601",
            "query_type": "partner_detail",
            "cmd_code": "854231",
            "reporter_code": 156,
            "hs_version": "H4",
        },
        None,
        runner=runner,
    )
    assert result["status"] == "success"
    query = runner.calls[0]["query"]
    assert query.reporter_code == 156
    assert query.expected_hs_version == "H4"
    assert query.to_params()["reporterCode"] == 156


def test_reported_world_zero_is_preserved_for_ic(preview_payload: dict[str, Any]) -> None:
    row = next(row for row in preview_payload["data"] if row["partnerCode"] == 0)
    row.update(
        reporterCode=156,
        cmdCode="854233",
        classificationCode="H4",
        isOriginalClassification=True,
        primaryValue="0",
    )
    response = ComtradeResponse.model_validate({"count": 1, "data": [row]})
    query = ComtradeQuery(
        period="202401",
        reporter_code=156,
        cmd_code="854233",
        expected_hs_version="H4",
        query_type=QueryType.WORLD_TOTAL,
    )
    dataset = IngestionService(FakeClient(response)).fetch_dataset(query)
    data = serialize_ndjson(dataset)
    manifest = build_manifest(dataset, data=data, ingested_at=datetime.now(UTC))
    result = verify(
        data,
        serialize_manifest(manifest),
        f"s3://test/un_comtrade/{artifact_partition(query)}/data.ndjson",
    )
    assert result["expected"][0]["primary_value"] == "0"
    assert manifest.row_count == 1


def test_checkpoints_survive_host_and_airflow_paths(tmp_path: Path) -> None:
    from trade_analytics.ingestion.paths import portable_checkpoints, resolve_artifact

    relative = (
        "v3/reporter_code=156/hs_version=H4/cmd_code=854231/period=201601/"
        "query_type=partner_detail/revision=1/data.ndjson"
    )
    host = "/Users/old-workspace/data/multi-market/" + relative
    container = "/opt/trade-analytics/data/multi-market/" + relative
    expected = (tmp_path / relative).resolve()
    assert resolve_artifact(tmp_path, host) == expected
    assert resolve_artifact(tmp_path, container) == expected
    assert resolve_artifact(tmp_path, relative) == expected
    proof = {"data": "checksum", "manifest": "manifest-checksum"}
    assert portable_checkpoints({host: proof, container: "legacy-checksum"}) == {relative: proof}
    with pytest.raises(ValueError):
        resolve_artifact(tmp_path, "v3/../../outside/data.ndjson")


def test_monthly_plan_prioritizes_recent_then_oldest_missing(
    preview_payload: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import copy

    import httpx
    import respx

    from trade_analytics.ingestion import multi_market
    from trade_analytics.ingestion.client import ComtradeClient

    monkeypatch.delenv("COMTRADE_API_KEY", raising=False)
    monkeypatch.setattr(multi_market.time, "sleep", lambda _: None)
    ledger = {}
    for period, checked in [("202601", "2026-03-15"), ("202602", "2026-02-15")]:
        for product in multi_market.PRODUCTS:
            for kind in QueryType:
                ledger[f"842/{product}/{period}/{kind.value}"] = {
                    "status": "unavailable",
                    "checked_at": checked,
                }
    (tmp_path / "batch-ledger.json").write_text(json.dumps(ledger))

    def response(request: httpx.Request) -> httpx.Response:
        payload = copy.deepcopy(preview_payload)
        for row in payload["data"]:
            row.update(
                period=request.url.params["period"],
                cmdCode=request.url.params["cmdCode"],
                reporterCode=842,
                classificationCode="H6",
                isOriginalClassification=True,
            )
        return httpx.Response(200, json=payload)

    with respx.mock:
        route = respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(side_effect=response)
        result = multi_market.run_batch(
            tmp_path,
            start="202601",
            end="202603",
            reporters=[842],
            max_requests=6,
            recent_from="202603",
        )
    called = [call.request.url.params["period"] for call in route.calls]
    assert called[:5] == ["202603"] * 5
    assert called[5] == "202602"
    assert result["requests"] == 6 and result["complete"] is False


def test_split_queries_wait_before_retrying_children(
    preview_payload: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import copy

    from trade_analytics.ingestion import multi_market
    from trade_analytics.ingestion.exceptions import ResponseTruncatedError

    events = []

    class SplitClient:
        def fetch(self, query: ComtradeQuery) -> ComtradeResponse:
            events.append(f"fetch:{len(query.reporter_codes)}")
            if len(query.reporter_codes) > 1:
                raise ResponseTruncatedError("fixture limit")
            payload = copy.deepcopy(preview_payload)
            for row in payload["data"]:
                row.update(
                    period=query.period,
                    cmdCode=query.cmd_code,
                    reporterCode=query.reporter_codes[0],
                    classificationCode="H6",
                    isOriginalClassification=True,
                )
            return ComtradeResponse.model_validate(payload)

    monkeypatch.setattr(multi_market, "ComtradeClient", lambda **_: SplitClient())
    monkeypatch.setattr(multi_market.time, "sleep", lambda _: events.append("wait"))
    multi_market.run_batch(
        tmp_path, start="202401", end="202401", reporters=[842, 156], max_requests=3
    )
    assert events == ["fetch:2", "wait", "fetch:1", "wait", "fetch:1", "wait"]


def test_recent_refresh_creates_new_revision_and_preserves_old_months(
    preview_payload: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import copy

    from trade_analytics.ingestion import multi_market

    calls = []

    class Client:
        def fetch(self, query: ComtradeQuery) -> ComtradeResponse:
            calls.append(query.period)
            payload = copy.deepcopy(preview_payload)
            for row in payload["data"]:
                row.update(
                    period=query.period,
                    cmdCode=query.cmd_code,
                    reporterCode=842,
                    classificationCode="H6",
                    isOriginalClassification=True,
                )
            return ComtradeResponse.model_validate(payload)

    monkeypatch.setattr(multi_market, "ComtradeClient", lambda **_: Client())
    monkeypatch.setattr(multi_market, "PRODUCTS", {"854231": "processors"})
    monkeypatch.setattr(multi_market.time, "sleep", lambda _: None)
    multi_market.run_batch(tmp_path, start="202601", end="202602", reporters=[842])
    calls.clear()
    multi_market.run_batch(
        tmp_path,
        start="202601",
        end="202602",
        reporters=[842],
        recent_from="202602",
        refresh_recent=True,
    )
    assert calls == ["202602"]
    ledger = json.loads((tmp_path / "batch-ledger.json").read_text())
    assert "revision=1" in ledger["842/854231/202601/partner_detail"]["data_path"]
    assert "revision=2" in ledger["842/854231/202602/partner_detail"]["data_path"]
    assert len(list(tmp_path.glob("v3/**/revision=1/data.ndjson"))) == 4

    from trade_analytics.ingestion.exceptions import DataContractError

    before = (tmp_path / "batch-ledger.json").read_bytes()

    class EmptyClient:
        def fetch(self, query: ComtradeQuery) -> ComtradeResponse:
            payload = copy.deepcopy(preview_payload)
            payload.update(count=0, data=[])
            return ComtradeResponse.model_validate(payload)

    monkeypatch.setattr(multi_market, "ComtradeClient", lambda **_: EmptyClient())
    with pytest.raises(DataContractError, match="previously accepted"):
        multi_market.run_batch(
            tmp_path,
            start="202602",
            end="202602",
            reporters=[842],
            recent_from="202602",
            refresh_recent=True,
        )
    assert (tmp_path / "batch-ledger.json").read_bytes() == before


def test_publication_stops_before_build_when_accepted_sources_remain_unloaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    from scripts import multi_market_pipeline as pipeline

    monkeypatch.setattr(pipeline, "load_environment", lambda: None)
    monkeypatch.setattr(pipeline, "sync", lambda root, limit: {"remaining": 1, "periods": []})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pipeline",
            "--sync-only",
            "--end",
            "202609",
            "--root",
            str(tmp_path),
            "--build",
            "--publish",
        ],
    )

    def unexpected_build(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("must not build or publish an incomplete load")

    monkeypatch.setattr(pipeline.subprocess, "run", unexpected_build)
    with pytest.raises(ValueError, match="all accepted sources"):
        pipeline.main()
