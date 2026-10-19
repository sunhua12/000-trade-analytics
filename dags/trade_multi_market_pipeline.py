"""Monthly multi-market IC refresh using the existing Airflow writer pool."""

import os
from datetime import timedelta

import pendulum
from airflow.sdk import dag, task
from airflow.timetables.interval import CronDataIntervalTimetable
from trade_pipeline.common import (
    DBT,
    PYTHON,
    ROOT,
    TRANSIENT_RETRY,
    multi_market_schedule_enabled,
    run_command,
)

ENABLED = multi_market_schedule_enabled()


@dag(
    dag_id="trade_multi_market_pipeline",
    description="Refresh recent IC imports and revisit delayed historical releases",
    schedule=CronDataIntervalTimetable("0 4 15 * *", timezone="Asia/Taipei") if ENABLED else None,
    start_date=pendulum.datetime(2026, 10, 1, tz="Asia/Taipei"),
    is_paused_upon_creation=False,
    catchup=False,
    max_active_runs=1,
    max_active_tasks=1,
    tags=["trade", "multi-market"],
)
def trade_multi_market_pipeline():
    @task(pool="trade_pipeline", execution_timeout=timedelta(hours=6), **TRANSIENT_RETRY)
    def refresh(**context) -> dict:
        anchor = context.get("data_interval_end") or context.get("logical_date")
        if anchor is None:
            anchor = context["dag_run"].run_after
        end = (
            pendulum.instance(anchor)
            .in_timezone("Asia/Taipei")
            .start_of("month")
            .subtract(months=1)
        )
        start = end.subtract(months=2)
        os.environ["TRADE_DBT_EXECUTABLE"] = DBT
        return run_command(
            [
                PYTHON,
                f"{ROOT}/scripts/multi_market_pipeline.py",
                "--start",
                start.format("YYYYMM"),
                "--end",
                end.format("YYYYMM"),
                "--max-requests",
                "100",
                "--max-sources",
                "2000",
                "--retry-unavailable",
                "--build",
                "--publish",
                "--require-row-target",
                "--state-file",
                f"{ROOT}/data/multi-market/monthly-state.json",
            ]
        )

    refresh()


trade_multi_market_pipeline()
