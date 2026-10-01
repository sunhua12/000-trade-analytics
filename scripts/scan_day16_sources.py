"""Read-only Preview API scan for partner codes absent from the reviewed seed."""

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.backfill_plan import periods_between  # noqa: E402
from trade_analytics.ingestion.client import ComtradeClient  # noqa: E402
from trade_analytics.ingestion.queries import ComtradeQuery, QueryType  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("start_period")
    parser.add_argument("end_period")
    args = parser.parse_args()
    known = {
        row["partner_code"]
        for row in csv.DictReader((ROOT / "dbt/seeds/country_reference.csv").open())
    }
    result = []
    with httpx.Client(timeout=httpx.Timeout(30.0)) as http_client:
        api = ComtradeClient(http_client=http_client)
        for period in periods_between(args.start_period, args.end_period):
            time.sleep(1)
            response = api.fetch(
                ComtradeQuery(period=period, cmd_code="8542", query_type=QueryType.PARTNER_DETAIL)
            )
            missing = [
                {
                    "partner_code": str(row.partner_code),
                    "partner_description": row.partner_description,
                }
                for row in response.data
                if str(row.partner_code) not in known
            ]
            result.append({"period": period, "row_count": response.count, "missing": missing})
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
