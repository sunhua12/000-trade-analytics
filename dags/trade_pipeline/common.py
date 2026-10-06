"""Shared command execution and serial month tasks for the trade pipelines."""

import json
import subprocess
from datetime import timedelta

from airflow.sdk import task
from airflow.sdk.exceptions import AirflowFailException

PYTHON = "/opt/trade-venv/bin/python"
DBT = "/opt/trade-venv/bin/dbt"
ROOT = "/opt/trade-analytics"
TRANSIENT_RETRY = {
    "retries": 3,
    "retry_delay": timedelta(minutes=2),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=15),
}


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


@task(pool="trade_pipeline", execution_timeout=timedelta(hours=1))
def pipeline_step(
    spec: dict, step: str, kind: str | None = None, recovery_probe: bool = False, **context
) -> dict:
    if spec.get("status", "ready") != "ready":
        return {"step": step, "period": spec.get("period"), "status": spec["status"]}
    command = [PYTHON, f"{ROOT}/scripts/monthly_steps.py", step, "--period", spec["period"]]
    if kind:
        command.extend(["--kind", kind, "--revision", str(spec["revisions"][kind])])
    if step == "ingest":
        command.extend(["--run-id", spec["run_id"]])
    if step == "build":
        command.extend(["--dbt-executable", DBT])
    print(
        json.dumps({"step": step, "kind": kind, "period": spec["period"], "run_id": spec["run_id"]})
    )
    result = run_command(command)
    if recovery_probe:
        probe = (context["dag_run"].conf or {}).get("recovery_probe")
        if (
            step == "load"
            and probe == {"period": spec["period"], "kind": kind}
            and context["ti"].try_number == 1
        ):
            raise RuntimeError("intentional post-commit load acknowledgment loss; retry same task")
    return result


def wire_months(plan, select_month, *, recovery_probe: bool = False) -> None:
    """Keep task IDs stable and process at most three months in old-to-new order."""
    previous_build = None
    for index in range(3):
        suffix = "" if index == 0 else f"_{index + 1}"
        spec = select_month.override(task_id=f"select_month{suffix}")(plan, index)
        if previous_build is not None:
            previous_build >> spec
        loads = []
        for label, kind in (("detail", "partner_detail"), ("world", "world_total")):
            ingest = pipeline_step.override(task_id=f"ingest_{label}{suffix}", **TRANSIENT_RETRY)(
                spec, "ingest", kind, recovery_probe=recovery_probe
            )
            load = pipeline_step.override(task_id=f"load_{label}{suffix}", **TRANSIENT_RETRY)(
                spec, "load", kind, recovery_probe=recovery_probe
            )
            ingest >> load
            loads.append(load)
        build = pipeline_step.override(task_id=f"build{suffix}")(spec, "build")
        for load in loads:
            load >> build
        previous_build = build
