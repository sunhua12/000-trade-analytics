"""Monthly trade pipeline: up to three safe months in serial order."""

import json
import subprocess
from datetime import timedelta

import pendulum
from airflow.sdk import dag, task
from airflow.sdk.exceptions import AirflowFailException, AirflowSkipException
from airflow.timetables.interval import CronDataIntervalTimetable

PYTHON = "/opt/trade-venv/bin/python"
DBT = "/opt/trade-venv/bin/dbt"
ROOT = "/opt/trade-analytics"


def run_command(command: list[str]) -> dict:
    process = subprocess.run(command, capture_output=True, text=True, check=False)
    if process.stdout:
        print(process.stdout)
    if process.stderr:
        print(process.stderr)
    if process.returncode:
        if process.returncode == 75:
            raise RuntimeError("transient command failure; task may retry")
        raise AirflowFailException(f"permanent command failure: exit code {process.returncode}")
    try:
        return json.loads(process.stdout.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as error:
        raise RuntimeError("command did not return JSON metadata") from error


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
        retries=3,
        retry_delay=timedelta(minutes=2),
        retry_exponential_backoff=True,
        max_retry_delay=timedelta(minutes=15),
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
                {"checks": plan["checks"], "older_unpublished": plan["older_unpublished"]},
                sort_keys=True,
            )
        )
        if index >= len(plan["selected"]):
            raise AirflowSkipException("no more available unpublished months in this run")
        return plan["selected"][index]

    @task(pool="trade_pipeline", execution_timeout=timedelta(hours=1))
    def monthly_step(spec: dict, step: str, kind: str | None = None) -> dict:
        command = [
            PYTHON,
            f"{ROOT}/scripts/monthly_steps.py",
            step,
            "--period",
            spec["period"],
        ]
        if kind:
            command.extend(["--kind", kind, "--revision", str(spec["revisions"][kind])])
        if step in ("ingest", "audit", "gate", "publish"):
            command.extend(["--run-id", spec["run_id"]])
        if step == "build":
            command.extend(["--dbt-executable", DBT])
        print(
            json.dumps(
                {"step": step, "kind": kind, "period": spec["period"], "run_id": spec["run_id"]}
            )
        )
        return run_command(command)

    plan = check_availability()
    previous_publish = None
    transient_retry = {
        "retries": 3,
        "retry_delay": timedelta(minutes=2),
        "retry_exponential_backoff": True,
        "max_retry_delay": timedelta(minutes=15),
    }
    for index in range(3):
        suffix = "" if index == 0 else f"_{index + 1}"
        spec = select_month.override(task_id=f"select_month{suffix}")(plan, index)
        if previous_publish is not None:
            previous_publish >> spec
        detail = monthly_step.override(task_id=f"ingest_detail{suffix}", **transient_retry)(
            spec, "ingest", "partner_detail"
        )
        world = monthly_step.override(task_id=f"ingest_world{suffix}", **transient_retry)(
            spec, "ingest", "world_total"
        )
        detail_load = monthly_step.override(task_id=f"load_detail{suffix}", **transient_retry)(
            spec, "load", "partner_detail"
        )
        world_load = monthly_step.override(task_id=f"load_world{suffix}", **transient_retry)(
            spec, "load", "world_total"
        )
        attest = monthly_step.override(task_id=f"attest{suffix}")(spec, "attest")
        build = monthly_step.override(task_id=f"build{suffix}")(spec, "build")
        audit = monthly_step.override(task_id=f"audit{suffix}")(spec, "audit")
        gate = monthly_step.override(task_id=f"gate{suffix}")(spec, "gate")
        publish = monthly_step.override(task_id=f"publish{suffix}")(spec, "publish")

        detail >> detail_load
        world >> world_load
        [detail_load, world_load] >> attest >> build >> audit >> gate >> publish
        previous_publish = publish


trade_monthly_pipeline()
