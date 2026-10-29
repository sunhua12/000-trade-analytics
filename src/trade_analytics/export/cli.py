"""Verify or stage an existing JSON v2 snapshot without cloud access."""

import argparse
import json
from pathlib import Path

from trade_analytics.export.v2 import verify_v2 as verify_snapshot
from trade_analytics.export.website import stage_snapshot
from trade_analytics.warehouse.writer_lock import writer_lock


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, default=Path("data/frontend-v2"))
    parser.add_argument("--stage-data", type=Path, help="destination, usually frontend/public/data")
    args = parser.parse_args()
    with writer_lock(args.snapshot_root.parent / "publish.lock"):
        result = (
            stage_snapshot(args.snapshot_root, args.stage_data)
            if args.stage_data
            else verify_snapshot(args.snapshot_root)
        )
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
