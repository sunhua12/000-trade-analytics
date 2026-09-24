"""Check the dashboard's published/attempt distinction and failure text."""

from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("google.api_core")

import streamlit as st
from google.api_core.exceptions import BadRequest, Forbidden
from streamlit.testing.v1 import AppTest

from dashboard import error_message, quality_table_rows
from trade_analytics.dashboard.queries import PublishedQueries

APP = Path(__file__).resolve().parents[3] / "dashboard.py"


def test_failed_latest_attempt_does_not_hide_published_pass() -> None:
    row = {
        "period": "202301",
        "published_quality_status": "PASS",
        "latest_quality_status": "FAIL",
        "reason_codes": ["missing_world"],
        "latest_publish_status": "not_published",
        "published_at": "earlier-success",
        "latest_tested_at": "later-failure",
    }
    visible = quality_table_rows([row])[0]
    assert visible["已發布品質"] == "PASS"
    assert visible["最新品質嘗試"] == "FAIL"
    assert visible["正式發布時間"] == "earlier-success"


def test_query_failures_have_distinct_messages() -> None:
    assert "權限不足" in error_message(Forbidden("denied"))
    assert "處理量上限" in error_message(BadRequest("maximum bytes billed exceeded"))


def test_empty_dashboard_results_do_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    st.cache_data.clear()
    monkeypatch.setattr(PublishedQueries, "months", lambda self: [date(2023, 1, 1)])
    monkeypatch.setattr(PublishedQueries, "partners", lambda self, start, end: [])
    monkeypatch.setattr(PublishedQueries, "rankings", lambda self, start, end, partners, n: [])
    monkeypatch.setattr(PublishedQueries, "trend", lambda self, start, end, partners: [])
    monkeypatch.setattr(
        PublishedQueries,
        "world_total",
        lambda self, start, end: {
            "published_months": 1,
            "world_value": 100,
            "latest_month": date(2023, 1, 1),
            "latest_published_at": None,
        },
    )
    monkeypatch.setattr(PublishedQueries, "quality", lambda self, start, end: [])
    app = AppTest.from_file(APP, default_timeout=10).run()
    assert not app.exception
    assert not app.error
    assert len(app.info) == 3


def test_query_failure_shows_error_instead_of_stale_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    st.cache_data.clear()

    def fail(self: PublishedQueries) -> list[date]:
        raise Forbidden("denied")

    monkeypatch.setattr(PublishedQueries, "months", fail)
    app = AppTest.from_file(APP, default_timeout=10).run()
    assert not app.exception
    assert "權限不足" in app.error[0].value
    assert not app.metric
