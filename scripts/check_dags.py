"""Import the real DAG and verify dependency and retry contracts without cloud writes."""

import subprocess
import sys
from unittest.mock import patch

import pendulum
from airflow.models import DagBag
from airflow.sdk.definitions.timetables.simple import NullTimetable
from airflow.sdk.exceptions import AirflowFailException


def check(folder: str) -> None:
    sys.path.insert(0, folder)
    bag = DagBag(dag_folder=folder, known_pools={"default_pool", "trade_pipeline"})
    assert not bag.import_errors, bag.import_errors
    assert set(bag.dags) == {"trade_multi_market_pipeline"}
    dag = bag.dags["trade_multi_market_pipeline"]
    assert dag.max_active_runs == 1 and dag.max_active_tasks == 1
    stages = ["extract", "load", "transform", "publish"]
    assert set(dag.task_ids) == set(stages)
    from trade_pipeline.common import multi_market_schedule_enabled, run_command

    assert isinstance(dag.timetable, NullTimetable) != multi_market_schedule_enabled()
    for index, stage in enumerate(stages):
        task = dag.get_task(stage)
        assert task.pool == "trade_pipeline" and task.retries == 3
        assert task.trigger_rule == "all_success"
        assert task.upstream_task_ids == (set() if index == 0 else {stages[index - 1]})
        commands = []
        with patch.dict(
            task.python_callable.__globals__,
            {
                "run_command": lambda command, commands=commands: (
                    commands.append(command) or {"artifact_uri": "s3://fixture/result"}
                )
            },
        ):
            context = {
                "data_interval_end": pendulum.datetime(2026, 10, 15, tz="Asia/Taipei"),
                "run_id": "scheduled-test",
            }
            if stage == "extract":
                result = task.python_callable(**context)
            else:
                result = task.python_callable("s3://fixture/upstream", **context)
        assert result == "s3://fixture/result"
        command = commands[0]
        assert command[command.index("--start") + 1] == "202607"
        assert command[command.index("--end") + 1] == "202609"
        assert command[command.index("--stage") + 1] == stage
    for code, error in ((2, AirflowFailException), (1, AirflowFailException), (75, RuntimeError)):
        with patch(
            "trade_pipeline.common.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=code, stdout="", stderr=""
            ),
        ):
            try:
                run_command(["test-only"])
            except error:
                pass
            else:
                raise AssertionError(f"exit {code} should fail")
    print("four stages: dependency, schedule, CLI range and retry verified")


if __name__ == "__main__":
    check(sys.argv[1] if len(sys.argv) > 1 else "dags")
