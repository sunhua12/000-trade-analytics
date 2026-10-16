"""Build a validated website release and optionally stage it for Sites/local preview."""

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trade_analytics.export.website import build_website  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, default=ROOT / "data/frontend")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/website")
    parser.add_argument(
        "--stage-data",
        action="store_true",
        help="copy validated public JSON into frontend/public/data",
    )
    args = parser.parse_args()
    result = build_website(args.snapshot_root, ROOT / "frontend", args.output_dir)
    if args.stage_data:
        destination = ROOT / "frontend/public/data"
        destination.mkdir(parents=True, exist_ok=True)
        for name in ("manifest.json", "monthly.json", "partners.json"):
            shutil.copyfile(Path(result["directory"]) / "data" / name, destination / name)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
