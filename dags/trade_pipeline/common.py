"""Command execution and retry policy shared by the four ETL stages."""

import json
import os
import subprocess
from datetime import timedelta

from airflow.sdk.exceptions import AirflowFailException

PYTHON = "/opt/trade-venv/bin/python"
ROOT = "/opt/trade-analytics"
TRANSIENT_RETRY = {
    "retries": 3,
    "retry_delay": timedelta(minutes=2),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=15),
}


def multi_market_schedule_enabled() -> bool:
    return os.environ.get("TRADE_MULTI_MARKET_SCHEDULE_ENABLED", "false").strip().lower() == "true"


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
