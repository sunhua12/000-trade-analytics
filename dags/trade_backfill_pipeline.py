"""Manual, bounded three-month backfill using the production single-month steps."""

import json
import subprocess
from datetime import timedelta

from airflow.sdk import dag, task
from airflow.sdk.exceptions import AirflowFailException

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
    dag_id="trade_backfill_pipeline",
    description="Manually backfill up to three explicit months in serial order",
    schedule=None,
    max_active_runs=1,
    max_active_tasks=1,
    tags=["trade", "backfill"],
)
def trade_backfill_pipeline():
    @task(
        task_id="preflight",
        execution_timeout=timedelta(minutes=20),
        retries=3,
        retry_delay=timedelta(minutes=2),
        retry_exponential_backoff=True,
        max_retry_delay=timedelta(minutes=15),
    )
    def preflight(**context) -> dict:
        dag_run = context["dag_run"]
        if dag_run.run_type != "manual":
            raise AirflowFailException("backfill requires a manual DAG run")
        return run_command(
            [
                PYTHON,
                f"{ROOT}/scripts/backfill_plan.py",
                "--conf",
                json.dumps(dag_run.conf or {}),
                "--dag-run-id",
                dag_run.run_id,
            ]
        )

    @task(task_id="select_month")
    def select_month(plan: dict, index: int) -> dict:
        if index >= len(plan["items"]):
            return {"status": "unused"}
        return plan["items"][index]

    @task(pool="trade_pipeline", execution_timeout=timedelta(hours=1))
    def backfill_step(spec: dict, step: str, kind: str | None = None, **context) -> dict:
        if spec["status"] != "ready":
            return {"step": step, "period": spec.get("period"), "status": spec["status"]}
        command = [PYTHON, f"{ROOT}/scripts/monthly_steps.py", step, "--period", spec["period"]]
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
        result = run_command(command)
        probe = (context["dag_run"].conf or {}).get("recovery_probe")
        if (
            step == "load"
            and probe == {"period": spec["period"], "kind": kind}
            and context["ti"].try_number == 1
        ):
            raise RuntimeError("intentional post-commit load acknowledgment loss; retry same task")
        return result

    plan = preflight()
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
        detail = backfill_step.override(task_id=f"ingest_detail{suffix}", **transient_retry)(
            spec, "ingest", "partner_detail"
        )
        world = backfill_step.override(task_id=f"ingest_world{suffix}", **transient_retry)(
            spec, "ingest", "world_total"
        )
        detail_load = backfill_step.override(task_id=f"load_detail{suffix}", **transient_retry)(
            spec, "load", "partner_detail"
        )
        world_load = backfill_step.override(task_id=f"load_world{suffix}", **transient_retry)(
            spec, "load", "world_total"
        )
        attest = backfill_step.override(task_id=f"attest{suffix}")(spec, "attest")
        build = backfill_step.override(task_id=f"build{suffix}")(spec, "build")
        audit = backfill_step.override(task_id=f"audit{suffix}")(spec, "audit")
        gate = backfill_step.override(task_id=f"gate{suffix}")(spec, "gate")
        publish = backfill_step.override(task_id=f"publish{suffix}")(spec, "publish")
        detail >> detail_load
        world >> world_load
        [detail_load, world_load] >> attest >> build >> audit >> gate >> publish
        previous_publish = publish


trade_backfill_pipeline()
