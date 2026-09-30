"""Check the non-Airflow task contract before wiring an orchestration DAG."""

import io
import json
import subprocess
from types import SimpleNamespace
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError

from scripts import monthly_steps


def test_job_output_excludes_sql_parameters_and_source_rows() -> None:
    jobs = [
        {
            "job_id": "job-1",
            "result": "success",
            "sql": "SELECT secret",
            "parameters": {"rows": "raw source data"},
        }
    ]
    assert monthly_steps.job_metadata(jobs) == [{"job_id": "job-1", "result": "success"}]


def test_ingest_rejects_mismatched_source_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scripts.monthly_steps.time.sleep", lambda seconds: None)

    class FakeLambda:
        def invoke(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "StatusCode": 200,
                "Payload": io.BytesIO(
                    json.dumps(
                        {
                            "status": "success",
                            "period": "202602",
                            "query_type": "world_total",
                            "row_count": 1,
                            "checksum": "sha256:" + "a" * 64,
                            "data_uri": "s3://wrong-bucket/data.ndjson",
                            "manifest_uri": "s3://wrong-bucket/manifest.json",
                        }
                    ).encode()
                ),
            }

    class FakeS3:
        def get_object(self, **kwargs: Any) -> None:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")

    def fake_client(service: str, **kwargs: Any) -> FakeLambda | FakeS3:
        assert service in ("lambda", "s3")
        assert kwargs["region_name"] == "ap-northeast-1"
        return FakeLambda() if service == "lambda" else FakeS3()

    monkeypatch.setattr(boto3, "client", fake_client)
    with pytest.raises(ValueError, match="metadata does not match"):
        monthly_steps.invoke_lambda("202602", "world_total", 1, "run-1")


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
    assert variables["raw_end_date"] == "2026-02-01"
    assert variables["month_spine_end_date"] == "2026-01-01"
    assert "--target" in captured


def test_quality_fail_stops_gate_before_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePublisher:
        release = "release"
        jobs: list[dict[str, Any]] = []

        def table(self, dataset: str, name: str) -> str:
            return f"{dataset}.{name}"

        def query(self, sql: str, params: dict[str, str]) -> list[dict[str, str]]:
            return [{"period": "202602", "status": "FAIL"}]

    monkeypatch.setattr(monthly_steps, "publisher", lambda args: FakePublisher())
    args = monthly_steps.parser().parse_args(["gate", "--period", "202602", "--run-id", "r1"])
    with pytest.raises(ValueError, match="quality gate blocked: FAIL"):
        monthly_steps.execute(args)


def test_load_error_is_not_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeLoader:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def load(self, period: str, kind: str, revision: int) -> dict[str, Any]:
            raise ValueError("checksum conflict")

    monkeypatch.setattr(monthly_steps, "RawLoader", FakeLoader)
    monkeypatch.setattr(
        monthly_steps, "import_module", lambda name: SimpleNamespace(Client=lambda **kw: None)
    )
    args = monthly_steps.parser().parse_args(
        ["load", "--period", "202602", "--kind", "partner_detail"]
    )
    with pytest.raises(ValueError, match="checksum conflict"):
        monthly_steps.execute(args)


def test_publish_requires_explicit_replacement_of_existing_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePublisher:
        release = "release"

        def table(self, dataset: str, name: str) -> str:
            return f"{dataset}.{name}"

        def query(self, sql: str, params: dict[str, str]) -> list[dict[str, str]]:
            return [{"published_run_id": "earlier-run"}]

        def publish(self, run_id: str, period: str) -> str:
            raise AssertionError("publish must not run")

    monkeypatch.setattr(monthly_steps, "publisher", lambda args: FakePublisher())
    args = monthly_steps.parser().parse_args(["publish", "--period", "202602", "--run-id", "r2"])
    with pytest.raises(ValueError, match="already published"):
        monthly_steps.execute(args)
