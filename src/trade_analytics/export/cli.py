"""Export a successfully built dbt presentation layer to versioned local JSON."""

import argparse
import json
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

from trade_analytics.export.queries import SnapshotReader
from trade_analytics.export.service import publish_snapshot, validate_build, verify_snapshot
from trade_analytics.warehouse.read_settings import Settings
from trade_analytics.warehouse.writer_lock import writer_lock


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--multi-market", action="store_true")
    parser.add_argument("--require-row-target", action="store_true")
    parser.add_argument("--start-month", type=date.fromisoformat)
    parser.add_argument("--end-exclusive", type=date.fromisoformat)
    parser.add_argument("--project")
    parser.add_argument("--dataset")
    parser.add_argument("--dbt-artifacts", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("data/frontend"))
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="verify current local snapshot without cloud access",
    )
    args = parser.parse_args()
    if not args.verify_only and args.dbt_artifacts is None:
        parser.error("--dbt-artifacts is required for export")
    try:
        if args.verify_only:
            print(json.dumps(verify_snapshot(args.output_dir), sort_keys=True))
            return 0
        settings = Settings.from_env()
        settings = replace(
            settings,
            project=args.project or settings.project,
            dataset=args.dataset or settings.dataset,
            first_month=args.start_month or settings.first_month,
            after_last_month=args.end_exclusive or settings.after_last_month,
        )
        with writer_lock(args.output_dir.parent / "pipeline.lock"):
            build = validate_build(args.dbt_artifacts, settings, multi_market=args.multi_market)
            reader = SnapshotReader(settings, multi_market=args.multi_market)
            raw = reader.read(settings.first_month, settings.after_last_month)
            if args.multi_market and args.require_row_target:
                from trade_analytics.ingestion.audit import audit_sources

                workspace = Path(__file__).resolve().parents[3]
                source_root = workspace / "data/multi-market"
                if source_root.exists():
                    source_audit = audit_sources(
                        source_root,
                        workspace / "dbt/seeds/country_reference.csv",
                        start=settings.first_month.strftime("%Y%m"),
                        end_exclusive=settings.after_last_month.strftime("%Y%m"),
                    )
                    if source_audit["valid_detail_count"] != len(raw["partners"]):
                        raise ValueError(
                            "warehouse detail count differs from accepted source extracts"
                        )
                    from trade_analytics.export.service import json_bytes

                    (source_root / "acceptance.json").write_bytes(json_bytes(source_audit))
            result = publish_snapshot(
                raw,
                args.output_dir,
                settings.first_month,
                settings.after_last_month,
                build=build,
                jobs=reader.jobs,
                multi_market=args.multi_market,
                require_row_target=args.require_row_target,
            )
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        # Cloud exceptions can contain SQL and internal identifiers; keep stderr bounded.
        message = (
            str(error)
            if isinstance(error, (ValueError, FileNotFoundError))
            else "export failed; inspect cloud logs or credentials"
        )
        print(
            json.dumps(
                {"status": "failed", "error_type": type(error).__name__, "message": message}
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
