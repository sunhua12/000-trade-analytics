"""Core bounded analytics query and Streamlit display examples."""

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import streamlit as st
from google.cloud import bigquery
from streamlit.testing.v1 import AppTest

from trade_analytics.dashboard import queries
from trade_analytics.dashboard.queries import AnalyticsQueries


class FakeBigQuery:
    @staticmethod
    def ScalarQueryParameter(name: str, kind: str, value: object) -> tuple[str, str, object]:
        return (name, kind, value)

    @staticmethod
    def ArrayQueryParameter(name: str, kind: str, value: object) -> tuple[str, str, object]:
        return (name, kind, value)

    @staticmethod
    def QueryJobConfig(**kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(**kwargs)


class FakeClient:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[str, object, str]] = []

    def query(self, sql: str, job_config: object, location: str) -> SimpleNamespace:
        self.calls.append((sql, job_config, location))
        return SimpleNamespace(
            result=lambda timeout: self.rows,
            job_id="test-job",
            total_bytes_processed=100,
            total_bytes_billed=0,
        )


@pytest.fixture
def setup_bigquery(monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    monkeypatch.setattr(queries, "import_module", lambda _: FakeBigQuery)
    return FakeClient()


def test_scope_is_parameterized_and_limits_billed_bytes(setup_bigquery: FakeClient) -> None:
    reader = queries.AnalyticsQueries(queries.Settings("trade-analytics-508604"), setup_bigquery)
    reader.rankings(date(2023, 12, 1), date(2024, 1, 1), ["156"], 10)
    sql, config, location = setup_bigquery.calls[0]
    params = {param[0]: param[2] for param in config.query_parameters}
    assert "period_start_date >= @start_date" in sql
    assert "period_start_date < @end_exclusive" in sql
    assert "partner_type='country'" in sql
    assert "partner_code IN UNNEST(@partners)" in sql
    assert "LIMIT @top_n" in sql
    assert "156" not in sql
    assert params["end_exclusive"] == date(2024, 2, 1)
    assert params["partners"] == ["156"]
    assert params["all_partners"] is False
    assert config.maximum_bytes_billed == 1000000000
    assert location == "asia-northeast1"


pytest.importorskip("streamlit")

pytest.importorskip("google.api_core")

APP = Path(__file__).resolve().parents[2] / "src/trade_analytics/dashboard/app.py"


@pytest.fixture(autouse=True)
def offline_bigquery_client(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Mock()
    client.query.side_effect = AssertionError("UI unit tests must not call BigQuery")
    monkeypatch.setattr(bigquery, "Client", lambda **kwargs: client)


def test_empty_dashboard_results_do_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    st.cache_data.clear()
    monkeypatch.setattr(AnalyticsQueries, "months", lambda self: [date(2023, 1, 1)])
    monkeypatch.setattr(AnalyticsQueries, "partners", lambda self, start, end: [])
    monkeypatch.setattr(AnalyticsQueries, "rankings", lambda self, start, end, partners, n: [])
    monkeypatch.setattr(AnalyticsQueries, "trend", lambda self, start, end, partners: [])
    monkeypatch.setattr(
        AnalyticsQueries,
        "world_total",
        lambda self, start, end: {
            "available_months": 1,
            "world_value": 100,
            "latest_month": date(2023, 1, 1),
        },
    )
    monkeypatch.setattr(AnalyticsQueries, "monthly_metrics", lambda self, start, end: [])
    monkeypatch.setattr(AnalyticsQueries, "scatter", lambda self, month, partners: [])
    monkeypatch.setattr(AnalyticsQueries, "map_values", lambda self, start, end, partners: [])
    app = AppTest.from_file(APP, default_timeout=10).run()
    assert not app.exception
    assert not app.error
    assert any(item.value == "此期間沒有逐月覆蓋資料。" for item in app.info)
    assert "年增率 YoY" not in [item.value for item in app.subheader]
    assert "最新月份：進口金額與 YoY" not in [item.value for item in app.subheader]
