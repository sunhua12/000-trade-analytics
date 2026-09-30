"""Month selection and safe replay rules for the Airflow planner."""

from datetime import datetime
from zoneinfo import ZoneInfo

import boto3
import pytest
from botocore.exceptions import ClientError

from scripts import monthly_plan


def test_candidate_periods_handle_month_and_year_boundaries() -> None:
    taipei = ZoneInfo("Asia/Taipei")
    assert monthly_plan.candidate_periods(datetime(2026, 10, 1, tzinfo=taipei)) == [
        "202607",
        "202608",
        "202609",
    ]
    assert monthly_plan.candidate_periods(datetime(2027, 1, 1, tzinfo=taipei)) == [
        "202610",
        "202611",
        "202612",
    ]


def test_candidate_limit_and_interval_are_validated() -> None:
    taipei = ZoneInfo("Asia/Taipei")
    with pytest.raises(ValueError, match="1 to 3"):
        monthly_plan.candidate_periods(datetime(2026, 10, 1, tzinfo=taipei), 4)
    with pytest.raises(ValueError, match="first day"):
        monthly_plan.candidate_periods(datetime(2026, 10, 2, tzinfo=taipei))


def test_published_month_requires_matching_replay_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(monthly_plan, "bigquery_client", lambda: object())
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: object())
    monkeypatch.setattr(monthly_plan, "current_published", lambda client, period: "published-1")
    monkeypatch.setattr(monthly_plan, "source_available", lambda *args: True)
    interval_end = datetime(2026, 10, 1, tzinfo=ZoneInfo("Asia/Taipei"))

    skipped = monthly_plan.plan(
        interval_end=interval_end, dag_run_id="manual-1", manual_period="202412"
    )
    assert skipped["selected"] == []
    assert skipped["checks"][0]["status"] == "already_published"

    replay = monthly_plan.plan(
        interval_end=interval_end,
        dag_run_id="manual-2",
        manual_period="202412",
        replay_run_id="published-1",
    )
    assert replay["selected"][0]["run_id"] == "published-1"


def test_empty_source_is_not_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(monthly_plan, "bigquery_client", lambda: object())
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: object())
    monkeypatch.setattr(monthly_plan, "current_published", lambda client, period: None)
    monkeypatch.setattr(monthly_plan, "source_available", lambda *args: False)
    result = monthly_plan.plan(
        interval_end=datetime(2026, 10, 1, tzinfo=ZoneInfo("Asia/Taipei")),
        dag_run_id="scheduled-1",
    )
    assert len(result["checks"]) == 3
    assert {check["status"] for check in result["checks"]} == {"not_available"}
    assert result["selected"] == []


def test_missing_pair_with_empty_api_response_is_not_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EmptyS3:
        def head_object(self, **kwargs: object) -> None:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")

    class EmptyClient:
        def __init__(self, **kwargs: object) -> None:
            pass

        def fetch(self, query: object) -> object:
            return type("Response", (), {"count": 0, "data": []})()

    monkeypatch.setattr(monthly_plan, "ComtradeClient", EmptyClient)
    assert not monthly_plan.source_available(EmptyS3(), object(), "202608", "world_total", 1)


def test_incomplete_s3_pair_is_an_error() -> None:
    class HalfS3:
        def head_object(self, *, Key: str, **kwargs: object) -> object:
            if Key.endswith("data.ndjson"):
                return {}
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")

    with pytest.raises(ValueError, match="incomplete S3 source pair"):
        monthly_plan.source_available(HalfS3(), object(), "202608", "world_total", 1)
