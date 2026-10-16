"""Real Airflow import and serial-writer checks; never execute pipeline tasks."""

import sys

from airflow.models import DagBag
from airflow.sdk.definitions.timetables.simple import NullTimetable


def check(folder: str) -> None:
    bag = DagBag(dag_folder=folder, known_pools={"default_pool", "trade_pipeline"})
    if bag.import_errors:
        raise SystemExit(str(bag.import_errors))
    assert set(bag.dags) == {"trade_monthly_pipeline", "trade_backfill_pipeline"}
    for name, first in (
        ("trade_monthly_pipeline", "check_availability"),
        ("trade_backfill_pipeline", "preflight"),
    ):
        dag = bag.dags[name]
        assert dag.max_active_runs == 1
        assert dag.max_active_tasks == 1
        assert first in dag.task_ids
        assert len(dag.tasks) == 2
        batch = dag.get_task("process_batch")
        assert batch.upstream_task_ids == {first}
        assert batch.pool == "trade_pipeline"
        assert batch.trigger_rule == "all_success"
        assert batch.retries == 3
        print(f"{name}: imported two tasks; whole-batch pool boundary verified")
    assert isinstance(bag.dags["trade_backfill_pipeline"].timetable, NullTimetable)


if __name__ == "__main__":
    check(sys.argv[1] if len(sys.argv) > 1 else "dags")
