"""Extend the reviewed reference only when official Comtrade and M49 codes agree."""

import argparse
import csv
import json
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path


class M49Table(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self.row: list[str] = []
        self.cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "tr":
            self.row = []
        elif tag == "td":
            self.cell = []

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self.cell is not None:
            self.row.append("".join(self.cell).strip())
            self.cell = None
        elif tag == "tr" and self.row:
            self.rows.append(self.row)


def refresh(partners: Path, m49: Path, output: Path) -> int:
    parser = M49Table()
    parser.feed(m49.read_text())
    official = {}
    for cells in parser.rows:
        for index in range(1, len(cells) - 2):
            if (
                re.fullmatch(r"\d{3}", cells[index])
                and re.fullmatch(r"[A-Z]{2}", cells[index + 1])
                and re.fullmatch(r"[A-Z]{3}", cells[index + 2])
            ):
                official.setdefault(int(cells[index]), (cells[index - 1], cells[index + 2]))
    if len(official) < 200:
        raise ValueError("official M49 table did not parse completely")
    with output.open() as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames
        existing = {int(row["partner_code"]): row for row in reader}
    count = 0
    retrieved = datetime.now(UTC).isoformat()
    for row in json.loads(partners.read_text())["results"]:
        code = int(row["id"])
        if code in existing or code not in official or row.get("isGroup") is not False:
            continue
        name, iso3 = official[code]
        if row.get("PartnerCodeIsoAlpha3") != iso3:
            continue
        existing[code] = {
            "partner_code": str(code),
            "source_name": row["PartnerDesc"],
            "source_note": row.get("partnerNote", ""),
            "source_iso_alpha3": iso3,
            "source_is_group": "false",
            "partner_type": "country",
            "classification_status": "verified",
            "map_iso3": iso3,
            "reconciliation_role": "detail",
            "source_url": "https://comtradeapi.un.org/files/v1/app/reference/partnerAreas.json",
            "retrieved_at": retrieved,
            "classification_source_url": "https://unstats.un.org/unsd/methodology/m49/overview/",
            "classification_note": f"Comtrade code and ISO3 match M49 country/area: {name}",
            "mapping_source_url": "https://unstats.un.org/unsd/methodology/m49/overview/",
            "mapping_note": "Official code and ISO3 verified; geometry coverage checked separately",
        }
        count += 1
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(existing[code] for code in sorted(existing))
    return count


if __name__ == "__main__":
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--partner-reference", required=True, type=Path)
    args.add_argument("--m49", required=True, type=Path)
    args.add_argument("--output", type=Path, default=Path("dbt/seeds/country_reference.csv"))
    options = args.parse_args()
    print(json.dumps({"added": refresh(options.partner_reference, options.m49, options.output)}))
