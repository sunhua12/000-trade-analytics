"""Four durable ETL stages, visible separately in Airflow."""

import hashlib
from datetime import timedelta

import pendulum
from airflow.sdk import dag, task
from airflow.timetables.interval import CronDataIntervalTimetable
from trade_pipeline.common import (
    PYTHON,
    ROOT,
    TRANSIENT_RETRY,
    multi_market_schedule_enabled,
    run_command,
)


@dag(
    dag_id="trade_multi_market_pipeline",
    description="Extract → load → dbt quality gate → website artifact",
    schedule=(
        CronDataIntervalTimetable("0 4 15 * *", timezone="Asia/Taipei")
        if multi_market_schedule_enabled()
        else None
    ),
    start_date=pendulum.datetime(2026, 10, 1, tz="Asia/Taipei"),
    is_paused_upon_creation=False,
    catchup=False,
    max_active_runs=1,
    max_active_tasks=1,
    tags=["trade", "multi-market"],
)
def trade_multi_market_pipeline():
    def execute(stage, upstream, context):
        anchor = context.get("data_interval_end") or context.get("logical_date")
        if anchor is None:
            anchor = context["dag_run"].run_after
        end = (
            pendulum.instance(anchor)
            .in_timezone("Asia/Taipei")
            .start_of("month")
            .subtract(months=1)
        )
        run_id = hashlib.sha256(context["run_id"].encode()).hexdigest()
        command = [
            PYTHON,
            f"{ROOT}/scripts/multi_market_pipeline.py",
            "--start",
            end.subtract(months=2).format("YYYYMM"),
            "--end",
            end.format("YYYYMM"),
            "--max-requests",
            "100",
            "--refresh",
            "--run-id",
            run_id,
            "--stage",
            stage,
        ]
        if upstream:
            command.extend(["--upstream", upstream])
        return run_command(command)["artifact_uri"]

    @task(
        pool="trade_pipeline",
        trigger_rule="all_success",
        execution_timeout=timedelta(hours=6),
        **TRANSIENT_RETRY,
    )
    def extract(**context):
        return execute("extract", None, context)

    @task(
        pool="trade_pipeline",
        trigger_rule="all_success",
        execution_timeout=timedelta(hours=2),
        **TRANSIENT_RETRY,
    )
    def load(upstream, **context):
        return execute("load", upstream, context)

    @task(
        pool="trade_pipeline",
        trigger_rule="all_success",
        execution_timeout=timedelta(hours=2),
        **TRANSIENT_RETRY,
    )
    def transform(upstream, **context):
        return execute("transform", upstream, context)

    @task(
        pool="trade_pipeline",
        trigger_rule="all_success",
        execution_timeout=timedelta(hours=2),
        **TRANSIENT_RETRY,
    )
    def publish(upstream, **context):
        return execute("publish", upstream, context)

    publish(transform(load(extract())))


trade_multi_market_pipeline()
