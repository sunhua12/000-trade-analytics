"""Reproduce reviewed Day 8 seeds offline; unknown codes require explicit review."""

import csv
import hashlib
import html
import json
import re
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "docs/evidence/day08/reference"
PARTNER_URL = "https://comtradeapi.un.org/files/v1/app/reference/partnerAreas.json"
HS_URL = "https://comtradeapi.un.org/files/v1/app/reference/H6.json"
M49_URL = "https://unstats.un.org/unsd/methodology/m49/overview/"
# Reviewed single partner economies, including territories, not a sovereignty list.
REVIEWED = [
    "32",
    "36",
    "40",
    "56",
    "76",
    "100",
    "116",
    "124",
    "144",
    "152",
    "156",
    "170",
    "188",
    "191",
    "196",
    "203",
    "208",
    "233",
    "246",
    "251",
    "258",
    "276",
    "300",
    "332",
    "344",
    "348",
    "360",
    "372",
    "376",
    "380",
    "392",
    "404",
    "410",
    "440",
    "458",
    "470",
    "478",
    "484",
    "504",
    "528",
    "554",
    "562",
    "579",
    "598",
    "608",
    "616",
    "620",
    "642",
    "643",
    "682",
    "699",
    "702",
    "703",
    "704",
    "705",
    "710",
    "724",
    "740",
    "752",
    "757",
    "764",
    "780",
    "784",
    "792",
    "807",
    "826",
    "842",
]


def write_csv(name, rows):
    with (ROOT / "dbt/seeds" / name).open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    metadata_path = REF / "manifest.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text())
    else:
        metadata = []
        for name, url in [
            ("partnerAreas.json", PARTNER_URL),
            ("H6.json", HS_URL),
            ("m49.html", M49_URL),
        ]:
            path = REF / name
            metadata.append(
                dict(
                    file=name,
                    source_url=url,
                    retrieved_at=datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                )
            )
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    for item in metadata:
        assert hashlib.sha256((REF / item["file"]).read_bytes()).hexdigest() == item["sha256"]
    retrieved = {r["file"]: r["retrieved_at"] for r in metadata}
    m49 = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", (REF / "m49.html").read_text(), re.S):
        cells = [
            html.unescape(re.sub("<[^>]+>", "", x)).strip()
            for x in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        ]
        if len(cells) >= 12 and re.fullmatch("[A-Z]{3}", cells[11]):
            m49.setdefault(cells[11], cells[8])
    source = json.loads((REF / "partnerAreas.json").read_text())["results"]
    baseline = json.loads((ROOT / "docs/evidence/day08/partner-baseline.json").read_text())
    codes = {r["partner_code"] for r in baseline} | {"0", "842"}
    assert codes <= set(REVIEWED) | {"0", "490"}, "New code needs review"
    rows = []
    for code in sorted(codes, key=int):
        matches = [r for r in source if str(r["PartnerCode"]) == code]
        assert len(matches) == 1, f"Ambiguous reference: {code}"
        r = matches[0]
        assert r["entryEffectiveDate"][:10] <= "2023-01-01"
        assert not r.get("entryExpiredDate") or r["entryExpiredDate"][:10] >= "2024-12-31"
        iso = r.get("PartnerCodeIsoAlpha3", "")
        ordinary = code in REVIEWED
        if ordinary:
            assert not r["isGroup"] and iso in m49
        kind = "country" if ordinary else ("world" if code == "0" else "special")
        note = (
            "Reviewed single partner economy; includes countries and territories; M49 name: "
            + m49[iso]
            if ordinary
            else (
                "Global total; separate from partner detail"
                if code == "0"
                else "Special code under docs/data-contract.md; "
                "S19 is not a verified map ISO; reconciliation unresolved"
            )
        )
        rows.append(
            dict(
                partner_code=code,
                source_name=r["PartnerDesc"],
                source_note=r.get("partnerNote", ""),
                source_iso_alpha3=iso,
                source_is_group=str(r["isGroup"]).lower(),
                partner_type=kind,
                classification_status="verified",
                map_iso3=iso if ordinary else "",
                reconciliation_role="detail"
                if ordinary
                else ("world" if code == "0" else "unresolved"),
                source_url=PARTNER_URL,
                retrieved_at=retrieved["partnerAreas.json"],
                classification_source_url=PARTNER_URL + (" ; " + M49_URL if ordinary else ""),
                classification_note=note,
                mapping_source_url=M49_URL if ordinary else "",
                mapping_note=(
                    "Comtrade ISO matches UN M49 country/area; "
                    "map geometry coverage must be checked in visualization phase"
                    if ordinary
                    else "No individual country geometry for World"
                    if code == "0"
                    else "No verified mapping for S19; retain NULL"
                ),
            )
        )
    write_csv("country_reference.csv", rows)
    hs = [r for r in json.loads((REF / "H6.json").read_text())["results"] if r["id"] == "8542"]
    assert len(hs) == 1 and hs[0]["aggrlevel"] == 4
    write_csv(
        "hs_code_reference.csv",
        [
            dict(
                hs_version="H6",
                cmd_code="8542",
                hs_description=hs[0]["text"],
                code_level=hs[0]["aggrlevel"],
                parent_code=hs[0]["parent"],
                source_url=HS_URL,
                retrieved_at=retrieved["H6.json"],
            )
        ],
    )
    print(f"Wrote {len(rows)} partner references and 1 HS reference")


if __name__ == "__main__":
    main()
