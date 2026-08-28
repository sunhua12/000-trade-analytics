"""Command-line entry point for UN Comtrade Preview ingestion."""

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import httpx
from pydantic import ValidationError

from trade_analytics.ingestion.client import ComtradeClient
from trade_analytics.ingestion.exceptions import ComtradeError
from trade_analytics.ingestion.queries import ComtradeQuery, QueryType
from trade_analytics.ingestion.service import IngestionService
from trade_analytics.ingestion.storage import LocalStorage, StoredIngestion

Runner = Callable[[ComtradeQuery, Path], StoredIngestion]


def run_ingestion(query: ComtradeQuery, output_dir: Path) -> StoredIngestion:
    """Run one query through the live Preview API and local storage."""
    timeout = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0)
    with httpx.Client() as http_client:
        client = ComtradeClient(http_client=http_client, timeout=timeout)
        dataset = IngestionService(client).fetch_dataset(query)
    return LocalStorage(root=output_dir).write(dataset)


def build_parser() -> argparse.ArgumentParser:
    """Build the public command-line parser."""
    parser = argparse.ArgumentParser(description="Fetch UN Comtrade monthly Preview data")
    parser.add_argument("--period", default="202401", help="Monthly period in YYYYMM format")
    parser.add_argument("--cmd-code", default="8542", help="HS commodity code")
    parser.add_argument(
        "--query-type",
        required=True,
        choices=[query_type.value for query_type in QueryType],
        help="Logical extract to fetch",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/preview"),
        help="Local root directory for ingestion artifacts",
    )
    return parser


def main(argv: Sequence[str] | None = None, *, runner: Runner = run_ingestion) -> int:
    """Parse arguments, execute one ingestion, and print concise metadata."""
    arguments = build_parser().parse_args(argv)
    try:
        query = ComtradeQuery(
            period=arguments.period,
            cmd_code=arguments.cmd_code,
            query_type=arguments.query_type,
        )
        stored = runner(query, arguments.output_dir)
    except (ValidationError, ComtradeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    output = {
        "status": "success",
        "period": query.period,
        "query_type": query.query_type.value,
        "row_count": stored.row_count,
        "data_path": str(stored.data_path),
        "manifest_path": str(stored.manifest_path),
        "checksum": stored.checksum,
    }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
