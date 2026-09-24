"""Audit each Day 11 partition and publish only PASS/WARN frozen batches."""

import argparse
import json
import sys
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from trade_analytics.warehouse.publish import Publisher

ROOT = Path(__file__).resolve().parents[1]


def all_periods() -> list[str]:
    return [f"{year}{month:02d}" for year in (2023, 2024) for month in range(1, 13)]


def main() -> None:
    bigquery = import_module("google.cloud.bigquery")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--periods", nargs="+", default=all_periods()[1:])
    parser.add_argument("--run-suffix", default="release-v1")
    parser.add_argument("--evidence", type=Path, default=Path("docs/evidence/day11/release.json"))
    args = parser.parse_args()
    runner = Publisher(
        bigquery.Client(project="trade-analytics-508604", location="asia-northeast1"),
        "trade-analytics-508604",
        "trade_analytics_day10_dev",
        "trade_raw",
        "trade_analytics_published",
    )
    runner.initialize()
    results = []
    for period in args.periods:
        if period not in all_periods():
            parser.error(f"unsupported period: {period}")
        run_id = f"day11-{period}-{args.run_suffix}"
        before = len(runner.jobs)
        item: dict[str, object] = {
            "period": period,
            "run_id": run_id,
            "attempted_at": datetime.now(UTC).isoformat(),
        }
        try:
            audit = runner.audit(run_id, period)
            item["quality_status"] = audit["status"]
            item["reason_codes"] = audit["reason_codes"]
            if audit["status"] in ("PASS", "WARN"):
                item["publish_status"] = runner.publish(run_id, period)
            else:
                item["publish_status"] = "blocked_by_quality"
        except Exception as error:
            item.update(publish_status="failed", error=f"{type(error).__name__}: {error}")
        item["jobs"] = runner.jobs[before:]
        results.append(item)
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(results, indent=2, default=str) + "\n")
        print(
            f"{period}: {item.get('quality_status', 'ERROR')} / {item['publish_status']}",
            flush=True,
        )


if __name__ == "__main__":
    main()
