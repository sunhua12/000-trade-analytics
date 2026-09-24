"""Verify all loaded source snapshots and save Day 10 publication attestations."""

import argparse
import json
import shutil
import sys
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from verify_publication_sources import verify

from trade_analytics.warehouse.publish import Publisher

ROOT = Path(__file__).resolve().parents[1]


def all_periods() -> list[str]:
    return [f"{year}{month:02d}" for year in (2023, 2024) for month in range(1, 13)]


def main() -> None:
    bigquery = import_module("google.cloud.bigquery")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--periods", nargs="+", default=all_periods())
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()
    runner = Publisher(
        bigquery.Client(project="trade-analytics-508604", location="asia-northeast1"),
        "trade-analytics-508604",
        "trade_analytics_day10_dev",
        "trade_raw",
        "trade_analytics_published",
    )
    runner.initialize()
    evidence = ROOT / "docs/evidence/day11/attestation"
    evidence.mkdir(parents=True, exist_ok=True)
    for period in args.periods:
        if period not in all_periods():
            parser.error(f"unsupported period: {period}")
        result_path = evidence / f"{period}.json"
        if args.skip_existing and result_path.exists():
            print(f"{period}: already attested", flush=True)
            continue
        directory = ROOT / "data/day11-attest" / period
        directory.mkdir(parents=True, exist_ok=True)
        for kind in ("partner_detail", "world_total"):
            source = ROOT / "data/day11-sources" / f"period={period}/query_type={kind}/revision=1"
            shutil.copyfile(source / "data.ndjson", directory / f"{kind}.ndjson")
            shutil.copyfile(source / "manifest.json", directory / f"{kind}.manifest.json")
        before = len(runner.jobs)
        try:
            checked = verify(runner, period, directory, download=False)
            item: dict[str, object] = {"period": period, "status": "verified", "sources": checked}
        except Exception as error:
            item = {
                "period": period,
                "status": "failed",
                "error": f"{type(error).__name__}: {error}",
            }
        item["jobs"] = runner.jobs[before:]
        result_path.write_text(json.dumps(item, indent=2, default=str) + "\n")
        print(f"{period}: {item['status']}", flush=True)


if __name__ == "__main__":
    main()
