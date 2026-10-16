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


@task(pool="trade_pipeline", execution_timeout=timedelta(hours=6), **TRANSIENT_RETRY)
def process_batch(plan: dict, recovery_probe: bool = False, **context) -> dict:
    """Hold the single-slot pool for all writes, tests, export and website build."""
    command = [
        PYTHON,
        f"{ROOT}/scripts/run_batch.py",
        "--plan",
        json.dumps(plan),
        "--dbt-executable",
        DBT,
        "--output-dir",
        f"{ROOT}/data",
    ]
    if recovery_probe and context["ti"].try_number == 1:
        probe = (context["dag_run"].conf or {}).get("recovery_probe")
        if probe:
            command.extend(["--recovery-probe", json.dumps(probe)])
    return run_command(command)
