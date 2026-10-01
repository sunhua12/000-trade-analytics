"""Exercise commit, replay, conflict and uncertain query outcomes without a warehouse."""

import io
import json
from unittest.mock import Mock

import pytest

from tests.unit.warehouse.test_gate import artifacts, encode
from trade_analytics.warehouse.backfill import RawLoader, expected_rows


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
    transaction = next(params for sql, params in calls if "BEGIN TRANSACTION" in sql)
    assert transaction["old_revision"] == "0"
    assert transaction["row_count"] == "1"
    assert transaction["amount"] == "10.01"
    prior = len(calls)
    assert loader.load("202301", "partner_detail")["status"] == "already_loaded"
    assert len(calls) == prior + 1


@pytest.mark.parametrize("failure", ["conflict", "stale_revision", "snapshot"])
def test_bad_replay_fails_before_transaction(failure: str) -> None:
    loader = loader_with_source()
    rows = expected_rows(loader.source("202301", "partner_detail", 1), "prior")
    if failure == "conflict":
        rows[0]["checksum"] = "sha256:different"
    elif failure == "stale_revision":
        rows[0]["revision"] = 2
    else:
        rows[0]["primary_value"] = "999"
    loader.query = Mock(return_value=[{"payload": json.dumps(rows[0])}])
    with pytest.raises(ValueError):
        loader.load("202301", "partner_detail")
    assert loader.query.call_count == 1


def test_post_commit_mismatch_is_reported() -> None:
    loader = loader_with_source()
    loader.query = Mock(return_value=[])
    with pytest.raises(ValueError, match="post-commit"):
        loader.load("202301", "partner_detail")


@pytest.mark.parametrize(
    "error_result,status", [(None, "unknown"), ({"reason": "invalid"}, "failed")]
)
def test_query_failure_records_job_and_omits_row_payload(error_result, status) -> None:
    client = Mock()
    client.query.return_value.error_result = error_result
    client.query.return_value.result.side_effect = TimeoutError("lost response")
    loader = RawLoader(client, Mock())
    with pytest.raises(TimeoutError):
        loader.query("SELECT 1", {"period": "202301", "rows": "private payload"})
    assert loader.jobs[0]["status"] == status
    assert loader.jobs[0]["params"] == {"period": "202301"}
    assert client.query.call_args.kwargs["job_retry"] is None


def test_successful_query_records_job_and_result() -> None:
    client = Mock()
    client.query.return_value.result.return_value = [{"n": 1}]
    loader = RawLoader(client, Mock())
    assert loader.query("SELECT 1", {}) == [{"n": 1}]
    assert loader.jobs[0]["status"] == "success"


def test_rollback_probe_cannot_touch_production() -> None:
    loader = loader_with_source()
    with pytest.raises(ValueError, match="fixture"):
        loader.load("202301", "partner_detail", rollback_probe=True)
    loader.s3.get_object.assert_not_called()
