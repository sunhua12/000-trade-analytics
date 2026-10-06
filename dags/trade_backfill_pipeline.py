"""Manual, bounded three-month backfill using the production single-month steps."""

import json
from datetime import timedelta

from airflow.sdk import dag, task
from airflow.sdk.exceptions import AirflowFailException
from trade_pipeline.common import PYTHON, ROOT, TRANSIENT_RETRY, run_command, wire_months


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
        **TRANSIENT_RETRY,
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

    plan = preflight()
    wire_months(plan, select_month, recovery_probe=True)


trade_backfill_pipeline()
