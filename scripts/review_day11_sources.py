"""Verify all downloaded source bytes and prepare a review of new partner codes."""

import html
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from trade_analytics.warehouse.backfill import BUCKET, KINDS, source_key
from trade_analytics.warehouse.gate import verify

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/day11-sources"
REFERENCE = ROOT / "docs/evidence/day08/reference"


def m49_names() -> dict[str, str]:
    result: dict[str, str] = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", (REFERENCE / "m49.html").read_text(), re.S):
        cells = [
            html.unescape(re.sub("<[^>]+>", "", value)).strip()
            for value in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        ]
        if len(cells) >= 12 and re.fullmatch("[A-Z]{3}", cells[11]):
            result.setdefault(cells[11], cells[8])
    return result


def main() -> None:
    periods = [f"{year}{month:02d}" for year in (2023, 2024) for month in range(1, 13)]
    # Compare against the fixed Day 8 source snapshot, not the expanded Day 11 seed.
    day08_rows = json.loads((ROOT / "docs/evidence/day08/partner-baseline.json").read_text())
    baseline = {row["partner_code"] for row in day08_rows} | {"0", "842"}
    reference = defaultdict(list)
    for row in json.loads((REFERENCE / "partnerAreas.json").read_text())["results"]:
        reference[str(row["PartnerCode"])].append(row)
    m49 = m49_names()
    inventory = []
    months_by_code: dict[str, list[str]] = defaultdict(list)
    for period in periods:
        for kind in KINDS:
            local = SOURCE / f"period={period}/query_type={kind}/revision=1"
            uri = f"s3://{BUCKET}/{source_key(period, kind)}/data.ndjson"
            checked = verify(
                (local / "data.ndjson").read_bytes(),
                (local / "manifest.json").read_bytes(),
                uri,
            )
            manifest = checked["manifest"]
            inventory.append(
                {
                    "period": period,
                    "kind": kind,
                    "revision": manifest["revision"],
                    "row_count": manifest["row_count"],
                    "primary_value_sum": manifest["primary_value_sum"],
                    "checksum": manifest["checksum"],
                    "source_file": uri,
                }
            )
            if kind == "partner_detail":
                for row in checked["expected"]:
                    months_by_code[row["partner_code"]].append(period)
    review = []
    for code in sorted(set(months_by_code) - baseline, key=int):
        matches = reference[code]
        if len(matches) != 1:
            raise ValueError(f"missing or ambiguous Comtrade reference for {code}")
        item = matches[0]
        iso = item.get("PartnerCodeIsoAlpha3", "")
        effective = item["entryEffectiveDate"][:10] <= "2023-01-01" and (
            not item.get("entryExpiredDate") or item["entryExpiredDate"][:10] >= "2024-12-31"
        )
        review.append(
            {
                "partner_code": code,
                "source_name": item["PartnerDesc"],
                "source_is_group": bool(item["isGroup"]),
                "source_iso_alpha3": iso,
                "m49_name": m49.get(iso),
                "effective_full_period": effective,
                "months": sorted(set(months_by_code[code])),
                "suggested_role": "country_detail"
                if not item["isGroup"] and iso in m49 and effective
                else "needs_review",
            }
        )
    evidence = ROOT / "docs/evidence/day11"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "source-inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
    (evidence / "partner-review.json").write_text(json.dumps(review, indent=2) + "\n")
    print(
        json.dumps(
            {
                "months": len(periods),
                "sources": len(inventory),
                "distinct_partner_codes": len(months_by_code),
                "new_codes": len(review),
                "needs_review": [
                    row["partner_code"] for row in review if row["suggested_role"] == "needs_review"
                ],
            }
        )
    )


if __name__ == "__main__":
    main()
