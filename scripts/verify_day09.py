"""Read-only Day 9 verification against the isolated build; never modifies raw."""

import json
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from pathlib import Path

from google.cloud import bigquery

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence/day09"
PROJECT = "trade-analytics-508604"
DATASET = "trade_analytics_day09_dev"


def main():
    client = bigquery.Client(project=PROJECT, location="asia-northeast1")
    report = {"verified_at": datetime.now(UTC).isoformat(), "queries": []}

    def query(name, sql):
        job = client.query(sql, job_config=bigquery.QueryJobConfig(maximum_bytes_billed=10**9))
        rows = [dict(row) for row in job.result()]
        report["queries"].append({"name": name, "job_id": job.job_id, "sql": sql, "rows": rows})
        return rows

    def table(name):
        return f"`{PROJECT}.{DATASET}.{name}`"

    facts = query("facts", f"select * from {table('fct_monthly_semiconductor_imports')}")
    worlds = query("worlds", f"select * from {table('stg_un_comtrade__world_totals')}")
    candidates = query(
        "candidates", f"select * from {table('mart_us_semiconductor_supply_chain_candidate')}"
    )
    hh = query("concentration", f"select * from {table('int_market_concentration_hhi')}")
    assert facts and worlds and hh, "Real source data must not be empty"

    def key(row):
        return tuple(row[k] for k in ("period_start_date", "cmd_code", "hs_version"))

    fact_map = {(key(r), r["partner_code"]): r for r in facts}
    candidate_map = {(key(r), r["partner_code"]): r for r in candidates}
    world_map = {key(r): r["primary_value"] for r in worlds}
    assert len(fact_map) == len(facts) == len(candidates) == len(candidate_map)
    assert fact_map.keys() == candidate_map.keys()

    def near(actual, expected, tolerance=Decimal("0.000000001")):
        if expected is None:
            assert actual is None, (actual, expected)
        else:
            assert actual is not None and abs(Decimal(str(actual)) - expected) <= tolerance, (
                actual,
                expected,
            )

    def ratio(value, denominator):
        if value is None or denominator is None or denominator <= 0:
            return None
        return value / denominator

    with localcontext() as ctx:
        ctx.prec = 38
        for k, f in fact_map.items():
            c = candidate_map[k]
            assert all(c[column] == value for column, value in f.items()), k
            near(c["market_share"], ratio(f["primary_value"], world_map.get(key(f))))
            near(c["unit_value_usd_per_kg"], ratio(f["primary_value"], f["net_weight"]))
            current = f["period_start_date"]
            for metric, year, month in (
                ("mom", current.year - (current.month == 1), (current.month - 2) % 12 + 1),
                ("yoy", current.year - 1, current.month),
            ):
                prior_key = (
                    (current.replace(year=year, month=month), *key(f)[1:]),
                    f["partner_code"],
                )
                prior = fact_map.get(prior_key, {}).get("primary_value")
                change = ratio(f["primary_value"], prior)
                near(c[metric], None if change is None else change - 1)

        for h in hh:
            countries = [f for f in facts if key(f) == key(h) and f["partner_type"] == "country"]
            assert countries and all(f["primary_value"] is not None for f in countries)
            total = sum(f["primary_value"] for f in countries)
            denominator = world_map[key(h)]
            coverage = total / denominator
            # SQL rounds NUMERIC market_share to 9 places before squaring.
            # Independently use full precision and bound the accumulated rounding difference.
            raw = sum((f["primary_value"] / denominator * 100) ** 2 for f in countries)
            near(h["country_value"], total)
            near(h["country_coverage"], coverage)
            near(h["hhi_raw"], raw, Decimal("0.00002"))
            expected_status = (
                "ok" if abs(1 - coverage) <= Decimal("0.005") else "insufficient_coverage"
            )
            assert h["hhi_status"] == expected_status
            near(h["hhi"], raw if expected_status == "ok" else None, Decimal("0.00002"))

    report["result"] = "passed"
    report["fact_rows"] = len(facts)
    report["candidate_rows"] = len(candidates)
    report["independent_decimal_check"] = "passed"
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "verification.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(f"PASS: {len(facts)} real rows; lineage, growth, share, weight and HHI verified")


if __name__ == "__main__":
    main()
