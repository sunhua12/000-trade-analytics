"""Download and verify the 48 immutable Day 11 S3 source objects locally."""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from trade_analytics.warehouse.backfill import BUCKET, KINDS, source_key
from trade_analytics.warehouse.gate import verify

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    sources = 0
    for year in (2023, 2024):
        for month in range(1, 13):
            period = f"{year}{month:02d}"
            for kind in KINDS:
                directory = (
                    ROOT / "data/day11-sources" / f"period={period}/query_type={kind}/revision=1"
                )
                directory.mkdir(parents=True, exist_ok=True)
                prefix = source_key(period, kind)
                for name in ("data.ndjson", "manifest.json"):
                    remote = f"s3://{BUCKET}/{prefix}/{name}"
                    local = directory / name
                    if not local.exists():
                        subprocess.run(
                            ["aws", "s3", "cp", remote, str(local), "--no-progress"], check=True
                        )
                checked = verify(
                    (directory / "data.ndjson").read_bytes(),
                    (directory / "manifest.json").read_bytes(),
                    f"s3://{BUCKET}/{prefix}/data.ndjson",
                )
                if (
                    checked["manifest"]["period"] != period
                    or checked["manifest"]["query_type"] != kind
                ):
                    raise ValueError(f"source identity mismatch: {period}/{kind}")
                sources += 1
    print(json.dumps({"periods": 24, "sources": sources, "status": "verified"}))


if __name__ == "__main__":
    main()
