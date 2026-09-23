"""Freeze and audit a partition; optionally publish only the accepted frozen batch."""

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from trade_analytics.warehouse.publish import Publisher


def main():
    from google.cloud import bigquery

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", default="trade-analytics-508604")
    p.add_argument("--models", default="trade_analytics_day10_dev")
    p.add_argument("--raw", default="trade_raw")
    p.add_argument("--release", default="trade_analytics_published")
    p.add_argument("--period", required=True)
    p.add_argument("--run-id", default=None)
    p.add_argument("--publish", action="store_true")
    p.add_argument(
        "--evidence", type=Path, default=Path("docs/evidence/day10/publication-jobs.json")
    )
    args = p.parse_args()
    runner = Publisher(
        bigquery.Client(project=args.project, location="asia-northeast1"),
        args.project,
        args.models,
        args.raw,
        args.release,
    )
    try:
        runner.initialize()
        run_id = args.run_id or str(uuid.uuid4())
        audit = runner.audit(run_id, args.period)
        print(json.dumps(audit, default=str, indent=2))
        if args.publish:
            runner.publish(run_id, args.period)
    finally:
        runner.save_evidence(args.evidence)


if __name__ == "__main__":
    main()
