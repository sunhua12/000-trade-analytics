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
        assert len(dag.tasks) == 19
        for index in range(3):
            suffix = "" if index == 0 else f"_{index + 1}"
            build = dag.get_task(f"build{suffix}")
            assert {f"load_detail{suffix}", f"load_world{suffix}"} <= build.upstream_task_ids
            assert build.trigger_rule == "all_success"
            assert build.retries == 0
            assert not any(
                dag_step + suffix in dag.task_ids
                for dag_step in ("audit", "gate", "publish", "attest")
            )
            for step in ("ingest_detail", "ingest_world", "load_detail", "load_world", "build"):
                assert dag.get_task(step + suffix).pool == "trade_pipeline"
            for kind in ("detail", "world"):
                ingest = dag.get_task(f"ingest_{kind}{suffix}")
                load = dag.get_task(f"load_{kind}{suffix}")
                assert ingest.task_id in load.upstream_task_ids
                assert ingest.retries == load.retries == 3
            if index:
                prior = "build" if index == 1 else "build_2"
                assert prior in dag.get_task("select_month" + suffix).upstream_task_ids
        print(f"{name}: imported {len(dag.tasks)} tasks; serial dependencies verified")
    assert isinstance(bag.dags["trade_backfill_pipeline"].timetable, NullTimetable)


if __name__ == "__main__":
    check(sys.argv[1] if len(sys.argv) > 1 else "dags")
