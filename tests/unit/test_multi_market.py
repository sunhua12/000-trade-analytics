"""Manifest resume, refresh, budget and response completeness regressions."""

import copy
import json

import httpx
import pytest
import respx

from trade_analytics.ingestion import multi_market as extract
from trade_analytics.ingestion.client import ComtradeClient
from trade_analytics.ingestion.exceptions import DataContractError, StorageConflictError
from trade_analytics.ingestion.storage import scan_sources


@pytest.fixture(autouse=True)
def bounded(monkeypatch):
    monkeypatch.setattr(extract, "PRODUCTS", {"854231": "processors"})
    monkeypatch.setattr(extract.time, "sleep", lambda _: None)
    monkeypatch.delenv("COMTRADE_API_KEY", raising=False)


def response_for(payload, request, *, amount=None, empty=False):
    payload = copy.deepcopy(payload)
    reporters = request.url.params["reporterCode"].split(",")
    rows = []
    for reporter in reporters:
        for row in payload["data"]:
            row = {
                **row,
                "reporterCode": int(reporter),
                "cmdCode": "854231",
                "period": request.url.params["period"],
                "isOriginalClassification": True,
            }
            if amount is not None:
                row["primaryValue"] = amount
            rows.append(row)
    payload.update(data=[] if empty else rows, count=0 if empty else len(rows))
    return httpx.Response(200, json=payload)


def run(root, **kwargs):
    return extract.run_batch(root, months=["202401"], reporters=(842, 156), **kwargs)


@respx.mock
def test_manifest_resume_and_unchanged_refresh(preview_payload, tmp_path):
    route = respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(
        side_effect=lambda request: response_for(preview_payload, request)
    )
    first = run(tmp_path)
    assert first.complete and first.requests == 1 and len(first.accepted) == 4
    assert not first.unavailable
    assert not (tmp_path / "batch-ledger.json").exists()
    assert run(tmp_path).requests == 0
    run(tmp_path, refresh=True)
    assert len(route.calls) == 2
    assert {s["manifest"]["revision"] for s in scan_sources(tmp_path).values()} == {1}
    assert {s["manifest"]["query_type"] for s in first.accepted} == {
        "world_total",
        "partner_detail",
    }


@respx.mock
def test_refresh_revision_and_missing_source_preserves_previous(preview_payload, tmp_path):
    route = respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(
        side_effect=lambda request: response_for(preview_payload, request)
    )
    run(tmp_path)
    route.mock(side_effect=lambda request: response_for(preview_payload, request, amount="999"))
    run(tmp_path, refresh=True)
    assert {s["manifest"]["revision"] for s in scan_sources(tmp_path).values()} == {2}
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*.ndjson")}
    route.mock(side_effect=lambda request: response_for(preview_payload, request, empty=True))
    with pytest.raises(DataContractError, match="previously accepted"):
        run(tmp_path, refresh=True)
    assert {str(p): p.read_bytes() for p in tmp_path.rglob("*.ndjson")} == before


@respx.mock
def test_budget_counts_retries_and_does_not_accept_partial_response(preview_payload, tmp_path):
    route = respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(503),
            httpx.Response(200, json=preview_payload),
        ]
    )
    result = run(tmp_path, max_requests=2)
    assert not result.complete and result.requests == 2
    assert len(route.calls) == 2 and result.accepted == []


@respx.mock
def test_truncation_split_counts_every_http_attempt(preview_payload, tmp_path):
    def response(request):
        if "," in request.url.params["reporterCode"]:
            payload = copy.deepcopy(preview_payload)
            payload["data"] = [payload["data"][0]] * 500
            payload["count"] = 500
            return httpx.Response(200, json=payload)
        return response_for(preview_payload, request)

    route = respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(side_effect=response)
    result = run(tmp_path, max_requests=3)
    assert result.complete and result.requests == 3 and len(result.accepted) == 4
    assert len(route.calls) == 3


@respx.mock
def test_split_budget_keeps_completed_child_for_resume(preview_payload, tmp_path):
    def response(request):
        if "," in request.url.params["reporterCode"]:
            payload = copy.deepcopy(preview_payload)
            payload.update(data=[payload["data"][0]] * 500, count=500)
            return httpx.Response(200, json=payload)
        return response_for(preview_payload, request)

    respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(side_effect=response)
    result = run(tmp_path, max_requests=2)
    assert not result.complete and len(result.accepted) == 2
    result = run(tmp_path, max_requests=1)
    assert result.complete and len(result.accepted) == 4


@respx.mock
def test_missing_initial_sources_are_unavailable_not_zero(preview_payload, tmp_path):
    respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(
        side_effect=lambda request: response_for(preview_payload, request, empty=True)
    )
    result = run(tmp_path)
    assert result.complete and len(result.unavailable) == 4 and result.accepted == []


@respx.mock
def test_corruption_and_identity_conflicts_are_not_refetched(preview_payload, tmp_path):
    route = respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(
        side_effect=lambda request: response_for(preview_payload, request)
    )
    run(tmp_path)
    source = next(tmp_path.rglob("data.ndjson"))
    source.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        run(tmp_path)
    assert len(route.calls) == 1


def test_uncommitted_source_is_rejected_but_staging_is_ignored(tmp_path):
    stage = tmp_path / "v3/.source-aborted"
    stage.mkdir(parents=True)
    (stage / "data.ndjson").write_bytes(b"partial")
    assert scan_sources(tmp_path) == {}
    final = tmp_path / "v3/reporter_code=842/revision=1"
    final.mkdir(parents=True)
    (final / "data.ndjson").write_bytes(b"partial")
    with pytest.raises(StorageConflictError, match="uncommitted"):
        scan_sources(tmp_path)


def test_periods():
    assert extract.periods("201611", "201702") == ["201611", "201612", "201701", "201702"]
    for start, end in [("201512", "201601"), ("202402", "202401"), ("202413", "202501")]:
        with pytest.raises(ValueError):
            extract.periods(start, end)


@respx.mock
def test_single_reporter_truncation_fails(tmp_path, preview_payload):
    from trade_analytics.ingestion.exceptions import ResponseTruncatedError

    payload = copy.deepcopy(preview_payload)
    payload.update(data=[payload["data"][0]] * 500, count=500)
    respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(return_value=httpx.Response(200, json=payload))
    with pytest.raises(ResponseTruncatedError):
        extract.run_batch(tmp_path, months=["202401"], reporters=(842,))
    assert not scan_sources(tmp_path)


@respx.mock
def test_timeout_retry_and_retry_exhaustion(tmp_path, monkeypatch):
    from tenacity import wait_none

    from trade_analytics.ingestion.exceptions import ComtradeTransientError

    route = respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(
        side_effect=httpx.ReadTimeout("timeout")
    )
    real = extract.ComtradeClient
    monkeypatch.setattr(
        extract, "ComtradeClient", lambda **kwargs: real(**kwargs, wait=wait_none())
    )
    with pytest.raises(ComtradeTransientError):
        run(tmp_path, max_requests=10)
    assert len(route.calls) == 4
    assert not scan_sources(tmp_path)


@respx.mock
def test_original_hs_required(preview_payload, tmp_path):
    payload = copy.deepcopy(preview_payload)

    def bad_response(request):
        response = response_for(payload, request)
        data = response.json()
        data["data"][0]["isOriginalClassification"] = False
        return httpx.Response(200, json=data)

    respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(side_effect=bad_response)
    with pytest.raises(DataContractError, match="original"):
        run(tmp_path)


@respx.mock
def test_filling_missing_kind_does_not_refresh_accepted_kind(preview_payload, tmp_path):
    def missing_world(request):
        response = response_for(preview_payload, request)
        payload = response.json()
        payload["data"] = [row for row in payload["data"] if row["partnerCode"] != 0]
        payload["count"] = len(payload["data"])
        return httpx.Response(200, json=payload)

    route = respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(side_effect=missing_world)
    assert len(run(tmp_path).accepted) == 2
    route.mock(side_effect=lambda request: response_for(preview_payload, request, amount="999"))
    result = run(tmp_path)
    partners = [s for s in result.accepted if s["manifest"]["query_type"] == "partner_detail"]
    assert len(result.accepted) == 4
    assert {s["manifest"]["revision"] for s in partners} == {1}
    assert all(
        json.loads(s["path"].read_text().splitlines()[0])["primaryValue"] != "999" for s in partners
    )


@respx.mock
def test_batch_scans_once_and_retains_only_source_metadata(preview_payload, tmp_path, monkeypatch):
    scans = []
    original = extract.scan_sources

    def scan(root):
        scans.append(root)
        return original(root)

    monkeypatch.setattr(extract, "scan_sources", scan)
    respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(
        side_effect=lambda request: response_for(preview_payload, request)
    )
    result = run(tmp_path)
    assert result.complete and len(result.accepted) == 4
    assert scans == [tmp_path]
    assert all("expected" not in source for source in result.accepted)
    assert set(original(tmp_path)) == {
        f"{reporter}/854231/202401/{kind}"
        for reporter in (842, 156)
        for kind in ("world_total", "partner_detail")
    }
