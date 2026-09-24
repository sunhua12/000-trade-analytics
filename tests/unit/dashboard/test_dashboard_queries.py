"""Verify the dashboard keeps source, scope and cost boundaries."""

from datetime import date
from types import SimpleNamespace

import pytest

from trade_analytics.dashboard import queries


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
    reader = queries.PublishedQueries(queries.Settings("trade-analytics-508604"), setup_bigquery)
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
    assert config.maximum_bytes_billed == 1_000_000_000
    assert location == "asia-northeast1"


def test_world_denominator_is_counted_once_per_month(setup_bigquery: FakeClient) -> None:
    setup_bigquery.rows = [{"published_months": 2, "world_value": 200}]
    reader = queries.PublishedQueries(queries.Settings("trade-analytics-508604"), setup_bigquery)
    result = reader.world_total(date(2023, 1, 1), date(2023, 2, 1))
    sql = setup_bigquery.calls[0][0]
    assert result["world_value"] == 200
    assert "MAX(world_value)" in sql
    assert "SUM(world_value)" in sql
    assert "GROUP BY period_start_date" in sql


def test_empty_partner_selection_explicitly_means_all(setup_bigquery: FakeClient) -> None:
    reader = queries.PublishedQueries(queries.Settings("trade-analytics-508604"), setup_bigquery)
    reader.rankings(date(2023, 1, 1), date(2023, 2, 1), [], 10)
    config = setup_bigquery.calls[0][1]
    params = {param[0]: param[2] for param in config.query_parameters}
    assert params["all_partners"] is True
    assert "@all_partners OR" in setup_bigquery.calls[0][0]


def test_quality_preserves_published_and_latest_attempt(setup_bigquery: FakeClient) -> None:
    reader = queries.PublishedQueries(queries.Settings("trade-analytics-508604"), setup_bigquery)
    reader.quality(date(2023, 1, 1), date(2023, 2, 1))
    sql, config, _ = setup_bigquery.calls[0]
    assert "published_quality_status" in sql
    assert "latest_quality_status" in sql
    assert "published_at" in sql
    assert "latest_tested_at" in sql
    assert config.query_parameters[0][2] == "202301"
    assert config.query_parameters[1][2] == "202302"


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (date(2024, 2, 1), date(2024, 1, 1)),
        (date(2023, 1, 2), date(2023, 2, 1)),
        (date(2022, 12, 1), date(2023, 1, 1)),
    ],
)
def test_invalid_dates_never_query(setup_bigquery: FakeClient, start: date, end: date) -> None:
    reader = queries.PublishedQueries(queries.Settings("trade-analytics-508604"), setup_bigquery)
    with pytest.raises(ValueError):
        reader.trend(start, end, [])
    assert setup_bigquery.calls == []


def test_invalid_top_n_never_queries(setup_bigquery: FakeClient) -> None:
    reader = queries.PublishedQueries(queries.Settings("trade-analytics-508604"), setup_bigquery)
    with pytest.raises(ValueError):
        reader.rankings(date(2023, 1, 1), date(2023, 2, 1), [], 31)
    assert setup_bigquery.calls == []


def test_only_published_tables_are_allowed() -> None:
    settings = queries.Settings("trade-analytics-508604")
    with pytest.raises(ValueError):
        settings.table("candidate_batches")
    with pytest.raises(ValueError):
        queries.Settings("malicious.project`")
