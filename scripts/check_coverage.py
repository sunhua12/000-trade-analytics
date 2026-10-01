"""Enforce component coverage, in addition to pytest's overall threshold."""

import json
import sys
from pathlib import Path


def check(path: str) -> None:
    report = json.loads(Path(path).read_text())
    groups = {
        "ingestion": ("/ingestion/", 90),
        "raw loader": ("/warehouse/backfill.py", 85),
    }
    for name, (fragment, minimum) in groups.items():
        summaries = [
            data["summary"]
            for filename, data in report["files"].items()
            if fragment in "/" + filename
        ]
        total = sum(summary["num_statements"] for summary in summaries)
        covered = sum(summary["covered_lines"] for summary in summaries)
        percentage = 100 * covered / total if total else 0
        print(f"{name}: {percentage:.2f}% (minimum {minimum}%)")
        if percentage < minimum:
            raise SystemExit(f"{name} coverage below required threshold")


if __name__ == "__main__":
    check(sys.argv[1])
