"""Read both presentation views in one BigQuery statement snapshot."""

from datetime import date, timedelta
from importlib import import_module
from typing import Any

from trade_analytics.warehouse.read_settings import Settings, validate_range

MONTHLY_FIELDS = (
    "month, cmd_code, hs_version, world_value, previous_year_world_value, world_yoy, "
    "country_value, country_count, country_coverage, hhi, hhi_status, has_world, has_countries"
)
PARTNER_FIELDS = (
    "month, cmd_code, hs_version, partner_code, source_name, map_iso3, import_value, "
    "market_share, market_share_status, previous_month_value, previous_year_value, mom, yoy"
)


class SnapshotReader:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.settings = settings
        self.bigquery = import_module("google.cloud.bigquery")
        self.client = client or self.bigquery.Client(
            project=settings.project, location=settings.location
        )
        self.jobs: list[dict[str, Any]] = []

    def read(self, start: date, end_exclusive: date) -> dict[str, Any]:
        validate_range(
            start,
            (end_exclusive - timedelta(days=1)).replace(day=1),
            self.settings.first_month,
            self.settings.after_last_month,
        )
        if end_exclusive.day != 1 or start >= end_exclusive:
            raise ValueError("export bounds must be ascending month boundaries")
        scope = (
            "month >= @start_date AND month < @end_exclusive "
            "AND cmd_code = @cmd_code AND hs_version = @hs_version"
        )
        prefix = f"{self.settings.project}.{self.settings.dataset}"
        sql = f"""SELECT
          ARRAY(SELECT AS STRUCT {MONTHLY_FIELDS}
            FROM `{prefix}.mart_dashboard_monthly`
            WHERE {scope} ORDER BY month) AS monthly,
          ARRAY(SELECT AS STRUCT {PARTNER_FIELDS}
            FROM `{prefix}.mart_dashboard_partners`
            WHERE {scope} ORDER BY month, partner_code) AS partners"""
        scalar = self.bigquery.ScalarQueryParameter
        config = self.bigquery.QueryJobConfig(
            query_parameters=[
                scalar("start_date", "DATE", start),
                scalar("end_exclusive", "DATE", end_exclusive),
                scalar("cmd_code", "STRING", "8542"),
                scalar("hs_version", "STRING", "H6"),
            ],
            maximum_bytes_billed=self.settings.maximum_bytes_billed,
            use_query_cache=False,
        )
        job = self.client.query(sql, job_config=config, location=self.settings.location)
        rows = list(job.result(timeout=180))
        if len(rows) != 1:
            raise ValueError("snapshot query must return one envelope")
        self.jobs.append(
            {
                "job_id": job.job_id,
                "bytes_processed": job.total_bytes_processed,
                "bytes_billed": job.total_bytes_billed,
            }
        )
        return {key: [dict(row) for row in rows[0][key]] for key in ("monthly", "partners")}
