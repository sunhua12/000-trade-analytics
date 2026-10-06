"""Core source validation, raw loading and orchestration examples."""

import hashlib
import io
import json
import subprocess
from datetime import datetime
from typing import Any
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import boto3
import httpx
import pytest

from scripts import backfill_plan, monthly_plan, monthly_steps
from scripts.pipeline_exit import TRANSIENT_EXIT_CODE, exit_for_error
from trade_analytics.ingestion.exceptions import (
    ComtradeAuthenticationError,
    ComtradeRequestError,
    ComtradeTransientError,
    StorageConflictError,
)
from trade_analytics.warehouse.loader import RawLoader, decision, expected_rows
from trade_analytics.warehouse.source_validation import verify


def test_revision_decisions() -> None:
    current = [{"revision": 2, "checksum": "sha256:a"}]
    assert decision([], 1, "sha256:a") == "load"
    assert decision(current, 3, "sha256:b") == "load"
    assert decision(current, 2, "sha256:a") == "already_loaded"
    assert decision(current, 2, "sha256:b") == "conflict"
    assert decision(current, 1, "sha256:a") == "stale_revision"
    with pytest.raises(ValueError, match="mixes source versions"):
        decision(current + [{"revision": 1, "checksum": "sha256:b"}], 3, "sha256:c")


def test_preflight_checks_all_months_and_keeps_stable_run_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(backfill_plan.boto3, "client", lambda *args, **kwargs: object())
    monkeypatch.setattr(backfill_plan.httpx, "Client", lambda **kwargs: _ContextClient())
    checked: list[tuple[str, str]] = []

    def available(s3: object, http: object, period: str, kind: str, revision: int) -> bool:
        checked.append((period, kind))
        return True

    monkeypatch.setattr(backfill_plan, "source_available", available)
    conf = {"start_period": "202501", "end_period": "202503"}
    first = backfill_plan.plan(conf, "manual__same")
    second = backfill_plan.plan(conf, "manual__same")
    assert first == second
    assert [item["status"] for item in first["items"]] == ["ready", "ready", "ready"]
    assert {period for period, kind in checked} == {"202501", "202502", "202503"}
    assert first["items"][0]["run_id"] != first["items"][2]["run_id"]


class _ContextClient:
    def __enter__(self) -> "_ContextClient":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_multiple_ready_months_remain_in_old_to_new_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: object())
    monkeypatch.setattr(monthly_plan, "source_available", lambda *args: True)
    result = monthly_plan.plan(
        interval_end=datetime(2026, 10, 1, tzinfo=ZoneInfo("Asia/Taipei")), dag_run_id="scheduled-1"
    )
    assert [item["period"] for item in result["selected"]] == ["202607", "202608", "202609"]
    assert len({item["run_id"] for item in result["selected"]}) == 3


def test_build_extends_raw_and_month_spine_to_target_month(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured.extend(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    args = monthly_steps.parser().parse_args(
        ["build", "--period", "202601", "--dbt-executable", ".venv-dbt/bin/dbt"]
    )
    result = monthly_steps.execute(args)
    variables = json.loads(captured[captured.index("--vars") + 1])
    assert result["status"] == "success"
    assert variables["raw_end_date"] == "2100-01-01"
    assert variables["month_spine_end_date"] == "2026-01-01"
    assert "--target" in captured


def test_retryable_and_permanent_exit_codes() -> None:
    assert exit_for_error(ComtradeTransientError("429")) == TRANSIENT_EXIT_CODE
    assert exit_for_error(httpx.ReadTimeout("timeout")) == TRANSIENT_EXIT_CODE
    assert exit_for_error(ComtradeRequestError("HTTP 400")) == 1
    assert exit_for_error(ComtradeAuthenticationError("HTTP 401")) == 1
    assert exit_for_error(StorageConflictError("checksum conflict")) == 1


def loader_with_source() -> RawLoader:
    rows, manifest = artifacts()
    data, encoded = encode(rows, manifest)
    s3 = Mock()
    s3.get_object.side_effect = lambda **kw: {
        "Body": io.BytesIO(encoded if kw["Key"].endswith("manifest.json") else data)
    }
    return RawLoader(Mock(), s3)


def test_commit_then_same_revision_replay_does_not_write_again() -> None:
    loader = loader_with_source()
    attested = loader.source("202301", "partner_detail", 1)
    rows = expected_rows(attested, "original-run")
    calls = []

    def query(sql, params):
        calls.append((sql, params))
        if "TO_JSON_STRING" in sql:
            return [] if len(calls) == 1 else [{"payload": json.dumps(rows[0])}]
        return []

    loader.query = query
    result = loader.load("202301", "partner_detail")
    assert result["status"] == "success"
    transaction = next((params for sql, params in calls if "BEGIN TRANSACTION" in sql))
    assert transaction["old_revision"] == "0"
    assert transaction["row_count"] == "1"
    assert transaction["amount"] == "10.01"
    prior = len(calls)
    assert loader.load("202301", "partner_detail")["status"] == "already_loaded"
    assert len(calls) == prior + 1

    # A one-billionth difference in a full-precision NUMERIC must fail replay validation.
    source_rows, manifest = artifacts()
    precise_amount = "12345678901234567890123456789.123456789"
    source_rows[0]["primaryValue"] = precise_amount
    manifest["primary_value_sum"] = precise_amount
    attested = verify(*encode(source_rows, manifest), URI)
    loader.source = Mock(return_value=attested)
    rows[:] = expected_rows(attested, "original-run")
    rows[0]["primary_value"] = "12345678901234567890123456789.123456788"
    with pytest.raises(ValueError, match="raw snapshot differs"):
        loader.load("202301", "partner_detail")


URI = "s3://bucket/un_comtrade/v2/hs_version=H6/cmd_code=8542/period=202301/query_type=partner_detail/revision=1/data.ndjson"


def artifacts() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    row = {
        "period": "202301",
        "reporterCode": 842,
        "flowCode": "M",
        "cmdCode": "8542",
        "partner2Code": 0,
        "customsCode": "C00",
        "motCode": 0,
        "partnerCode": 490,
        "freqCode": "M",
        "classificationCode": "H6",
        "primaryValue": "10.01",
        "netWgt": None,
        "qty": "0",
    }
    m = {
        "schema_version": "2.0.0",
        "hs_version": "H6",
        "period": "202301",
        "query_type": "partner_detail",
        "cmd_code": "8542",
        "revision": 1,
        "row_count": 1,
        "primary_value_sum": "10.01",
        "ingested_at": "2026-09-12T12:00:00Z",
        "request_parameters": {
            k: row[k]
            for k in (
                "period",
                "reporterCode",
                "flowCode",
                "cmdCode",
                "partner2Code",
                "customsCode",
                "motCode",
            )
        },
    }
    return ([row], m)


def encode(rows: list[dict[str, Any]], m: dict[str, Any]) -> tuple[bytes, bytes]:
    data = ("\n".join(json.dumps(r) for r in rows) + "\n").encode()
    return (
        data,
        json.dumps({**m, "checksum": "sha256:" + hashlib.sha256(data).hexdigest()}).encode(),
    )


def test_source_bytes_and_490_preserved() -> None:
    data, m = encode(*artifacts())
    result = verify(data, m, URI)
    assert result["expected"][0]["partner_code"] == "490"
    assert result["expected"][0]["net_weight"] is None
    with pytest.raises(ValueError, match="checksum"):
        verify(data + b"\n", m, URI)
    with pytest.raises(ValueError, match="path"):
        verify(data, m, URI.replace("revision=1", "revision=2"))
