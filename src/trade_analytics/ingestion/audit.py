"""Count accepted country detail from complete source extracts, never raw copies."""

import csv
import json
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from trade_analytics.ingestion.manifest import checksum
from trade_analytics.ingestion.multi_market import MARKETS, PRODUCTS


def audit_sources(
    root: Path,
    reference_path: Path,
    *,
    start: str = "201601",
    end_exclusive: str = "999901",
) -> dict[str, Any]:
    with reference_path.open() as handle:
        reference = {row["partner_code"]: row for row in csv.DictReader(handle)}
    extracts: dict[
        tuple[str, int, str, str], tuple[tuple[int, datetime, str, str], Path, dict[str, Any]]
    ] = {}
    for path in sorted(root.glob("v3/**/data.ndjson")):
        manifest = json.loads(path.with_name("manifest.json").read_bytes())
        reporter = manifest["request_parameters"]["reporterCode"]
        if (
            manifest["query_type"] != "partner_detail"
            or manifest["cmd_code"] not in PRODUCTS
            or reporter not in MARKETS
            or not start <= manifest["period"] < end_exclusive
        ):
            continue
        key = (manifest["period"], reporter, manifest["cmd_code"], "M")
        rank = (
            manifest["revision"],
            datetime.fromisoformat(manifest["ingested_at"].replace("Z", "+00:00")),
            manifest["hs_version"],
            str(path),
        )
        if key not in extracts or rank > extracts[key][0]:
            extracts[key] = (rank, path, manifest)
    accepted: dict[tuple[str, int, int, str, str], tuple[Decimal, str]] = {}
    excluded: Counter[str] = Counter()
    for _, path, manifest in extracts.values():
        data = path.read_bytes()
        if checksum(data) != manifest["checksum"]:
            raise ValueError("checksum mismatch")
        for line in data.splitlines():
            row = json.loads(line)
            partner = reference.get(str(row["partnerCode"]), {})
            if (
                partner.get("partner_type") != "country"
                or partner.get("classification_status") != "verified"
            ):
                excluded[str(row["partnerCode"])] += 1
                continue
            if row.get("isOriginalClassification") is not True or row["flowCode"] != "M":
                raise ValueError("expected original-classification import detail")
            amount = Decimal(row["primaryValue"])
            if not amount.is_finite() or amount < 0:
                raise ValueError("invalid amount")
            key_row = (
                row["period"],
                row["reporterCode"],
                row["partnerCode"],
                row["cmdCode"],
                row["flowCode"],
            )
            if key_row in accepted:
                raise ValueError("duplicate accepted detail grain")
            accepted[key_row] = (amount, row["classificationCode"])
    markets = Counter(str(key[1]) for key in accepted)
    versions = Counter(version for _, version in accepted.values())
    return {
        "valid_detail_count": len(accepted),
        "positive_amount_count": sum(amount > 0 for amount, _ in accepted.values()),
        "target_count": 100000,
        "row_target_passed": len(accepted) >= 100000,
        "market_counts": dict(sorted(markets.items())),
        "hs_version_counts": dict(versions),
        "excluded_partner_counts": dict(excluded),
        "accepted_extracts": len(extracts),
    }
