"""Monthly trade pipeline: up to three safe months in serial order."""

import json
from datetime import timedelta

import pendulum
from airflow.sdk import dag, task
from airflow.sdk.exceptions import AirflowSkipException
from airflow.timetables.interval import CronDataIntervalTimetable
from trade_pipeline.common import PYTHON, ROOT, TRANSIENT_RETRY, run_command, wire_months


@dag(
    dag_id="trade_monthly_pipeline",
    description="Check and process up to three completed months in serial order",
    schedule=CronDataIntervalTimetable("0 0 1 * *", timezone="Asia/Taipei"),
    start_date=pendulum.datetime(2026, 9, 1, tz="Asia/Taipei"),
    catchup=False,
    max_active_runs=1,
    max_active_tasks=1,
    tags=["trade", "monthly"],
)
def trade_monthly_pipeline():
    @task(
        task_id="check_availability",
        execution_timeout=timedelta(minutes=15),
        **TRANSIENT_RETRY,
    )
    def check_availability(**context) -> dict:
        dag_run = context["dag_run"]
        conf = dag_run.conf or {}
        if dag_run.run_type == "manual" and not conf.get("period"):
            raise ValueError("manual runs require conf.period in YYYYMM format")
        command = [
            PYTHON,
            f"{ROOT}/scripts/monthly_plan.py",
            "--interval-end",
            context["data_interval_end"].isoformat(),
            "--dag-run-id",
            dag_run.run_id,
        ]
        for key, option in (("period", "--period"), ("replay_run_id", "--replay-run-id")):
            if conf.get(key):
                command.extend([option, str(conf[key])])
        if conf.get("revisions"):
            command.extend(["--revisions", json.dumps(conf["revisions"])])
        print(
            json.dumps(
                {
                    "logical_date": str(dag_run.logical_date),
                    "data_interval_start": str(context["data_interval_start"]),
                    "data_interval_end": str(context["data_interval_end"]),
                    "dag_run_id": dag_run.run_id,
                }
            )
        )
        return run_command(command)

    @task(task_id="select_month")
    def select_month(plan: dict, index: int) -> dict:
        print(
            json.dumps(
                {"checks": plan["checks"]},
                sort_keys=True,
            )
        )
        if index >= len(plan["selected"]):
            raise AirflowSkipException("no more available months in this run")
        return plan["selected"][index]

    plan = check_availability()
    wire_months(plan, select_month)


trade_monthly_pipeline()
