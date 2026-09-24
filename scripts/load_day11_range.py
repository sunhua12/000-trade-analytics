"""Load 2023–2024 source partitions serially, checkpointing each result."""

import argparse
import json
import sys
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from load_day11 import AwsCliS3

from trade_analytics.warehouse.backfill import KINDS, PROJECT, RawLoader


def periods() -> list[str]:
    return [f"{year}{month:02d}" for year in (2023, 2024) for month in range(1, 13)]


def main() -> None:
    bigquery = import_module("google.cloud.bigquery")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--periods", nargs="+", default=periods())
    parser.add_argument("--project", default=PROJECT)
    parser.add_argument(
        "--evidence", type=Path, default=Path("docs/evidence/day11/load-range.json")
    )
    args = parser.parse_args()
    runner = RawLoader(
        bigquery.Client(project=args.project, location="asia-northeast1"),
        AwsCliS3(),
        project=args.project,
    )
    results = []
    for period in args.periods:
        if period not in periods():
            parser.error(f"unsupported period: {period}")
        for kind in KINDS:
            before = len(runner.jobs)
            item: dict[str, object] = {
                "period": period,
                "kind": kind,
                "attempted_at": datetime.now(UTC).isoformat(),
            }
            try:
                item.update(runner.load(period, kind))
            except Exception as error:
                item.update(status="failed", error=f"{type(error).__name__}: {error}")
            item["jobs"] = runner.jobs[before:]
            results.append(item)
            args.evidence.parent.mkdir(parents=True, exist_ok=True)
            args.evidence.write_text(json.dumps(results, indent=2, default=str) + "\n")
            print(f"{period} {kind}: {item['status']}", flush=True)


if __name__ == "__main__":
    main()
