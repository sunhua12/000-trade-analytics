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


def null_struct(fields: str) -> str:
    strings = {
        "cmd_code",
        "hs_version",
        "reporter_code",
        "partner_code",
        "source_name",
        "map_iso3",
        "hhi_status",
        "market_share_status",
    }
    types = {
        "month": "DATE",
        "country_count": "INT64",
        "has_world": "BOOL",
        "has_countries": "BOOL",
    }
    columns = []
    for field in map(str.strip, fields.split(",")):
        kind = "STRING" if field in strings else types.get(field, "NUMERIC")
        columns.append(f"{field} {kind}")
    return "CAST(NULL AS STRUCT<" + ", ".join(columns) + ">)"


class SnapshotReader:
    def __init__(
        self, settings: Settings, client: Any | None = None, *, multi_market: bool = False
    ) -> None:
        self.settings = settings
        self.multi_market = multi_market
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
        monthly_fields, partner_fields = MONTHLY_FIELDS, PARTNER_FIELDS
        monthly_table, partner_table = "mart_dashboard_monthly", "mart_dashboard_partners"
        if self.multi_market:
            scope = "month >= @start_date AND month < @end_exclusive"
            monthly_fields += ", reporter_code"
            partner_fields += ", reporter_code"
            monthly_table, partner_table = (
                "mart_multi_market_ic_monthly",
                "mart_multi_market_ic_partners",
            )
        prefix = f"{self.settings.project}.{self.settings.dataset}"
        sql = f"""SELECT
          ARRAY(SELECT AS STRUCT {monthly_fields}
            FROM `{prefix}.{monthly_table}`
            WHERE {scope} ORDER BY month) AS monthly,
          ARRAY(SELECT AS STRUCT {partner_fields}
            FROM `{prefix}.{partner_table}`
            WHERE {scope} ORDER BY month, partner_code) AS partners"""
        if self.multi_market:
            # Keep one statement snapshot while allowing result pagination by row.
            sql = f"""WITH documents AS (
              SELECT 'monthly' AS kind, STRUCT({monthly_fields}) AS monthly,
                {null_struct(partner_fields)} AS partners
              FROM `{prefix}.{monthly_table}` WHERE {scope}
              UNION ALL
              SELECT 'partners' AS kind, {null_struct(monthly_fields)} AS monthly,
                STRUCT({partner_fields}) AS partners
              FROM `{prefix}.{partner_table}` WHERE {scope}
            ) SELECT * FROM documents
            ORDER BY COALESCE(monthly.month,partners.month), kind,
              COALESCE(monthly.reporter_code,partners.reporter_code),
              COALESCE(monthly.cmd_code,partners.cmd_code), partners.partner_code"""
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
        if self.multi_market:
            raw: dict[str, list[dict[str, Any]]] = {"monthly": [], "partners": []}
            for row in job.result(timeout=180):
                kind = row["kind"]
                if kind not in raw or row[kind] is None:
                    raise ValueError("invalid streamed snapshot row")
                raw[kind].append(dict(row[kind]))
        else:
            rows = list(job.result(timeout=180))
            if len(rows) != 1:
                raise ValueError("snapshot query must return one envelope")
            raw = {key: [dict(row) for row in rows[0][key]] for key in ("monthly", "partners")}
        self.jobs.append(
            {
                "job_id": job.job_id,
                "bytes_processed": job.total_bytes_processed,
                "bytes_billed": job.total_bytes_billed,
            }
        )
        return raw
