"""Run an entire bounded batch under one writer lock, then export and build once."""

import argparse
import json
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.monthly_steps import execute, validate_period  # noqa: E402
from scripts.monthly_steps import parser as step_parser  # noqa: E402
from scripts.pipeline_exit import RetryablePipelineError, exit_for_error  # noqa: E402
from trade_analytics.export.queries import SnapshotReader  # noqa: E402
from trade_analytics.export.service import (  # noqa: E402
    publish_snapshot,
    validate_build,
    verify_snapshot,
)
from trade_analytics.export.website import build_website  # noqa: E402
from trade_analytics.warehouse.read_settings import Settings, next_month  # noqa: E402
from trade_analytics.warehouse.writer_lock import writer_lock  # noqa: E402


def ready_items(plan: dict[str, Any]) -> list[dict[str, Any]]:
    items = plan.get("selected", plan.get("items"))
    if not isinstance(items, list) or len(items) > 3:
        raise ValueError("plan must contain at most three selected/items entries")
    seen = set()
    ready = []
    for item in items:
        if item.get("status", "ready") != "ready":
            if item.get("status") not in ("unused", "not_available"):
                raise ValueError("unrecognized plan status")
            continue
        validate_period(item["period"])
        if item["period"] in seen or not item.get("run_id"):
            raise ValueError("duplicate period or missing run ID")
        if set(item.get("revisions", {})) != {"partner_detail", "world_total"} or any(
            type(value) is not int or value < 1 for value in item["revisions"].values()
        ):
            raise ValueError("both source revisions must be positive integers")
        seen.add(item["period"])
        ready.append(item)
    return sorted(ready, key=lambda item: item["period"])


def run_batch(
    plan: dict[str, Any],
    dbt_executable: Path,
    output: Path,
    *,
    recovery_probe: dict[str, str] | None = None,
) -> dict[str, Any]:
    items = ready_items(plan)
    if not items:
        return {"status": "not_available", "processed_months": [], "exported": False}
    settings = Settings.from_env()
    with writer_lock(ROOT / "data/pipeline.lock"):
        for item in items:
            for step in ("ingest", "load", "build"):
                for kind in ("partner_detail", "world_total") if step != "build" else (None,):
                    command = [step, "--period", item["period"], "--project", settings.project]
                    if kind:
                        command.extend(["--kind", kind, "--revision", str(item["revisions"][kind])])
                    if step == "ingest":
                        command.extend(["--run-id", item["run_id"]])
                    if step == "build":
                        command.extend(["--dbt-executable", str(dbt_executable)])
                    result = execute(step_parser().parse_args(command))
                    print(
                        json.dumps(
                            {
                                "event": "batch_step",
                                "period": item["period"],
                                "step": step,
                                "kind": kind,
                                "status": result["status"],
                            }
                        ),
                        flush=True,
                    )
                    if step == "load" and recovery_probe == {
                        "period": item["period"],
                        "kind": kind,
                    }:
                        raise RetryablePipelineError("intentional post-commit acknowledgment loss")
        snapshot_root = output / "frontend"
        last_month = date(int(items[-1]["period"][:4]), int(items[-1]["period"][4:]), 1)
        end = max(settings.after_last_month, next_month(last_month))
        if (snapshot_root / "current.json").exists():
            previous = verify_snapshot(snapshot_root)
            old = json.loads(
                (snapshot_root / previous["snapshot_id"] / "manifest.json").read_bytes()
            )
            end = max(end, date.fromisoformat(old["end_exclusive"]))
        settings = replace(settings, after_last_month=end)
        build = validate_build(ROOT / "dbt/target", settings)
        reader = SnapshotReader(settings)
        raw = reader.read(settings.first_month, settings.after_last_month)
        snapshot = publish_snapshot(
            raw,
            snapshot_root,
            settings.first_month,
            settings.after_last_month,
            build=build,
            jobs=reader.jobs,
        )
        website = build_website(snapshot_root, ROOT / "frontend", output / "website")
        return {
            "status": "success",
            "processed_months": [item["period"] for item in items],
            "exported": True,
            "snapshot_id": snapshot["snapshot_id"],
            "website": website,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, help="JSON plan from monthly_plan/backfill_plan")
    parser.add_argument("--dbt-executable", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--recovery-probe", type=json.loads)
    args = parser.parse_args()
    try:
        result = run_batch(
            json.loads(args.plan),
            args.dbt_executable,
            args.output_dir,
            recovery_probe=args.recovery_probe,
        )
        print(json.dumps(result, sort_keys=True))
    except Exception as error:
        raise SystemExit(exit_for_error(error)) from error


if __name__ == "__main__":
    main()
