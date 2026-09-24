"""Bounded, parameterized reads from the published BigQuery dataset."""

import os
import re
from dataclasses import dataclass
from datetime import date
from importlib import import_module
from typing import Any

FIRST_MONTH = date(2023, 1, 1)
AFTER_LAST_MONTH = date(2025, 1, 1)
CMD_CODE = "8542"
HS_VERSION = "H6"
DATASET = "trade_analytics_published"


@dataclass(frozen=True)
class Settings:
    project: str
    location: str = "asia-northeast1"
    maximum_bytes_billed: int = 1_000_000_000
    cache_ttl_seconds: int = 3600

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]", self.project):
            raise ValueError("TRADE_BQ_PROJECT 不是有效的 GCP 專案 ID")
        if not re.fullmatch(r"[a-z]+-[a-z]+\d", self.location):
            raise ValueError("TRADE_BQ_LOCATION 不是有效的 BigQuery location")
        if self.maximum_bytes_billed <= 0 or self.cache_ttl_seconds <= 0:
            raise ValueError("查詢處理量上限與快取 TTL 必須大於 0")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            project=os.environ.get("TRADE_BQ_PROJECT", "trade-analytics-508604"),
            location=os.environ.get("TRADE_BQ_LOCATION", "asia-northeast1"),
            maximum_bytes_billed=int(os.environ.get("TRADE_BQ_MAX_BYTES_BILLED", "1000000000")),
            cache_ttl_seconds=int(os.environ.get("TRADE_DASHBOARD_CACHE_TTL", "3600")),
        )

    def table(self, name: str) -> str:
        if name not in {"mart_us_semiconductor_supply_chain", "publication_quality_summary"}:
            raise ValueError("不允許查詢此資料表")
        return f"`{self.project}.{DATASET}.{name}`"


def next_month(month: date) -> date:
    return date(month.year + (month.month == 12), month.month % 12 + 1, 1)


def validate_range(start: date, end: date) -> None:
    if start.day != 1 or end.day != 1 or start > end:
        raise ValueError("請選擇有效且依時間排序的月份")
    if start < FIRST_MONTH or end >= AFTER_LAST_MONTH:
        raise ValueError("月份超出已規劃的展示範圍")


class PublishedQueries:
    """One client per Streamlit run; each query has parameters and a cost ceiling."""

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.settings = settings
        bigquery = import_module("google.cloud.bigquery")
        self.bigquery = bigquery
        self.client = client or bigquery.Client(
            project=settings.project, location=settings.location
        )
        self.jobs: list[dict[str, Any]] = []

    def _run(self, sql: str, parameters: list[Any]) -> list[dict[str, Any]]:
        config = self.bigquery.QueryJobConfig(
            query_parameters=parameters,
            maximum_bytes_billed=self.settings.maximum_bytes_billed,
            use_query_cache=True,
        )
        job = self.client.query(sql, job_config=config, location=self.settings.location)
        rows = [dict(row) for row in job.result(timeout=90)]
        self.jobs.append(
            {
                "job_id": job.job_id,
                "bytes_processed": getattr(job, "total_bytes_processed", None),
                "bytes_billed": getattr(job, "total_bytes_billed", None),
            }
        )
        return rows

    def _scope(self, start: date, end: date) -> list[Any]:
        validate_range(start, end)
        scalar = self.bigquery.ScalarQueryParameter
        return [
            scalar("start_date", "DATE", start),
            scalar("end_exclusive", "DATE", next_month(end)),
            scalar("cmd_code", "STRING", CMD_CODE),
            scalar("hs_version", "STRING", HS_VERSION),
        ]

    def months(self) -> list[date]:
        table = self.settings.table("mart_us_semiconductor_supply_chain")
        scalar = self.bigquery.ScalarQueryParameter
        rows = self._run(
            f"""SELECT DISTINCT period_start_date AS month FROM {table}
            WHERE period_start_date >= @start_date AND period_start_date < @end_exclusive
              AND cmd_code=@cmd_code AND hs_version=@hs_version ORDER BY month""",
            [
                scalar("start_date", "DATE", FIRST_MONTH),
                scalar("end_exclusive", "DATE", AFTER_LAST_MONTH),
                scalar("cmd_code", "STRING", CMD_CODE),
                scalar("hs_version", "STRING", HS_VERSION),
            ],
        )
        return [row["month"] for row in rows]

    def partners(self, start: date, end: date) -> list[dict[str, Any]]:
        table = self.settings.table("mart_us_semiconductor_supply_chain")
        return self._run(
            f"""SELECT partner_code, ANY_VALUE(source_name) AS source_name
            FROM {table}
            WHERE period_start_date >= @start_date AND period_start_date < @end_exclusive
              AND cmd_code=@cmd_code AND hs_version=@hs_version AND partner_type='country'
            GROUP BY partner_code ORDER BY partner_code""",
            self._scope(start, end),
        )

    def rankings(
        self, start: date, end: date, partners: list[str], top_n: int
    ) -> list[dict[str, Any]]:
        if not 5 <= top_n <= 30:
            raise ValueError("Top N 必須介於 5 與 30")
        table = self.settings.table("mart_us_semiconductor_supply_chain")
        params = self._scope(start, end) + [
            self.bigquery.ArrayQueryParameter("partners", "STRING", partners),
            self.bigquery.ScalarQueryParameter("all_partners", "BOOL", not partners),
            self.bigquery.ScalarQueryParameter("top_n", "INT64", top_n),
        ]
        return self._run(
            f"""SELECT partner_code, ANY_VALUE(source_name) AS source_name,
                   SUM(primary_value) AS import_value
            FROM {table}
            WHERE period_start_date >= @start_date AND period_start_date < @end_exclusive
              AND cmd_code=@cmd_code AND hs_version=@hs_version AND partner_type='country'
              AND (@all_partners OR partner_code IN UNNEST(@partners))
            GROUP BY partner_code ORDER BY import_value DESC, partner_code LIMIT @top_n""",
            params,
        )

    def trend(self, start: date, end: date, partners: list[str]) -> list[dict[str, Any]]:
        table = self.settings.table("mart_us_semiconductor_supply_chain")
        params = self._scope(start, end) + [
            self.bigquery.ArrayQueryParameter("partners", "STRING", partners),
            self.bigquery.ScalarQueryParameter("all_partners", "BOOL", not partners),
        ]
        return self._run(
            f"""SELECT period_start_date AS month, SUM(primary_value) AS import_value
            FROM {table}
            WHERE period_start_date >= @start_date AND period_start_date < @end_exclusive
              AND cmd_code=@cmd_code AND hs_version=@hs_version AND partner_type='country'
              AND (@all_partners OR partner_code IN UNNEST(@partners))
            GROUP BY month ORDER BY month""",
            params,
        )

    def world_total(self, start: date, end: date) -> dict[str, Any]:
        table = self.settings.table("mart_us_semiconductor_supply_chain")
        rows = self._run(
            f"""WITH monthly AS (
              SELECT period_start_date, MAX(world_value) AS world_value,
                     MAX(published_at) AS published_at
              FROM {table}
              WHERE period_start_date >= @start_date AND period_start_date < @end_exclusive
                AND cmd_code=@cmd_code AND hs_version=@hs_version
              GROUP BY period_start_date
            )
            SELECT COUNT(*) AS published_months, SUM(world_value) AS world_value,
                   MAX(period_start_date) AS latest_month, MAX(published_at) AS latest_published_at
            FROM monthly""",
            self._scope(start, end),
        )
        return rows[0]

    def quality(self, start: date, end: date) -> list[dict[str, Any]]:
        validate_range(start, end)
        table = self.settings.table("publication_quality_summary")
        scalar = self.bigquery.ScalarQueryParameter
        return self._run(
            f"""SELECT period, published_quality_status, published_run_id, published_at,
                   latest_quality_status, latest_run_id, latest_tested_at, reason_codes,
                   latest_publish_status, latest_attempted_at
            FROM {table}
            WHERE period >= @start_period AND period <= @end_period
              AND cmd_code=@cmd_code AND hs_version=@hs_version ORDER BY period""",
            [
                scalar("start_period", "STRING", start.strftime("%Y%m")),
                scalar("end_period", "STRING", end.strftime("%Y%m")),
                scalar("cmd_code", "STRING", CMD_CODE),
                scalar("hs_version", "STRING", HS_VERSION),
            ],
        )
