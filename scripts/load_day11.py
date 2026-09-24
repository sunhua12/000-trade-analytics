"""Load one immutable S3 source into a verified BigQuery raw partition."""

import argparse
import io
import json
import subprocess
import sys
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from trade_analytics.warehouse.backfill import KINDS, PROJECT, RawLoader


class AwsCliS3:
    def get_object(self, *, Bucket: str, Key: str) -> dict[str, io.BytesIO]:
        data = subprocess.check_output(
            ["aws", "s3", "cp", f"s3://{Bucket}/{Key}", "-", "--no-progress"]
        )
        return {"Body": io.BytesIO(data)}


def main() -> None:
    bigquery = import_module("google.cloud.bigquery")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", required=True)
    parser.add_argument("--kind", required=True, choices=KINDS)
    parser.add_argument("--revision", type=int, default=1)
    parser.add_argument("--project", default=PROJECT)
    parser.add_argument("--evidence-dir", type=Path, default=Path("docs/evidence/day11/load"))
    args = parser.parse_args()
    runner = RawLoader(
        bigquery.Client(project=args.project, location="asia-northeast1"),
        AwsCliS3(),
        project=args.project,
    )
    report: dict[str, object] = {
        "period": args.period,
        "kind": args.kind,
        "revision": args.revision,
        "attempted_at": datetime.now(UTC).isoformat(),
    }
    try:
        report.update(runner.load(args.period, args.kind, args.revision))
    except Exception as error:
        report.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        report["jobs"] = runner.jobs
        args.evidence_dir.mkdir(parents=True, exist_ok=True)
        path = args.evidence_dir / f"{args.period}-{args.kind}-r{args.revision}.json"
        path.write_text(json.dumps(report, indent=2, default=str) + "\n")
        print(json.dumps(report, default=str))


if __name__ == "__main__":
    main()
