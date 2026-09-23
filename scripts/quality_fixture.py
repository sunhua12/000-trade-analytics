"""Synthetic inputs only; shared by offline and isolated warehouse acceptance tests."""

from copy import deepcopy
from decimal import Decimal

from trade_analytics.warehouse.quality import SOURCE_COLUMNS, partition, source_digest


def fixture(amounts=("60", "40"), *, world="100", special=None, overlap=None, period="202301"):
    scope = partition(period)
    rows = []
    entries = [(str(i + 1), value, "country", "detail") for i, value in enumerate(amounts)]
    if special is not None:
        entries.append(("490", special, "special", "detail"))
    if overlap is not None:
        entries.append(("999", overlap, "aggregate", "overlap"))
    for code, amount, kind, role in entries:
        rows.append(
            {
                **scope,
                "reporter_code": "842",
                "flow_code": "M",
                "partner_code": code,
                "primary_value": amount,
                "net_weight": None,
                "quantity": None,
                "run_id": "fixture-detail",
                "revision": 1,
                "checksum": "fixture-detail-sha",
                "source_file": "s3://fixture/detail/data.ndjson",
                "ingested_at": "2026-01-01T00:00:00Z",
                "partner_type": kind,
                "reconciliation_role": role,
                "classification_status": "verified",
                "country_mapping_found": True,
                "hs_mapping_found": True,
                "month_mapping_found": True,
                "map_iso3": None,
                "source_name": "Fixture",
                "hs_description": "Fixture semiconductor",
                "previous_month_value": None,
                "previous_year_value": None,
                "mom": None,
                "yoy": None,
                "unit_value_usd_per_kg": None,
            }
        )
    worlds = (
        [
            {
                **scope,
                "reporter_code": "842",
                "flow_code": "M",
                "partner_code": "0",
                "primary_value": world,
                "net_weight": None,
                "quantity": None,
                "run_id": "fixture-world",
                "revision": 1,
                "checksum": "fixture-world-sha",
                "source_file": "s3://fixture/world/data.ndjson",
                "ingested_at": "2026-01-01T00:00:00Z",
            }
        ]
        if world is not None
        else []
    )
    result = {"candidate": rows, "world": worlds}
    refresh(result)
    return result


def refresh(inputs):
    rows = inputs["candidate"]
    world = (
        Decimal(str(inputs["world"][0]["primary_value"]))
        if len(inputs["world"]) == 1
        else Decimal(0)
    )
    countries = [r for r in rows if r["partner_type"] == "country"]
    country_sum = sum(
        (Decimal(str(r["primary_value"])) for r in countries if r["primary_value"] is not None),
        Decimal(0),
    )
    coverage = country_sum / world if world > 0 else None
    raw_hhi = (
        sum(
            (Decimal(str(r["primary_value"])) / world * 100) ** 2
            for r in countries
            if r["primary_value"] is not None
        )
        if world > 0
        else None
    )
    available = coverage is not None and abs(1 - coverage) <= Decimal(".005") and bool(countries)
    for r in rows:
        value = None if r["primary_value"] is None else Decimal(str(r["primary_value"]))
        r.update(
            world_value=str(world) if world > 0 else None,
            market_share=str(value / world) if value is not None and world > 0 else None,
            market_share_status="ok" if world > 0 else "invalid_world",
            country_value=str(country_sum),
            country_count=len(countries),
            country_coverage=None if coverage is None else str(coverage),
            hhi_raw=None if raw_hhi is None else str(raw_hhi),
            hhi=str(raw_hhi) if available else None,
            hhi_status="ok" if available else "insufficient_coverage",
        )
    inputs["detail"] = [{k: r[k] for k in SOURCE_COLUMNS} for r in rows]
    inputs["loads"] = []
    for kind, group in (("partner_detail", inputs["detail"]), ("world_total", inputs["world"])):
        if not group:
            continue
        first = group[0]
        total = sum(
            (Decimal(str(r["primary_value"])) for r in group if r["primary_value"] is not None),
            Decimal(0),
        )
        inputs["loads"].append(
            {
                **{
                    k: first[k]
                    for k in (
                        "period",
                        "cmd_code",
                        "hs_version",
                        "run_id",
                        "revision",
                        "checksum",
                        "source_file",
                    )
                },
                "query_type": kind,
                "status": "snapshot_verified",
                "expected_row_count": len(group),
                "actual_row_count": len(group),
                "expected_primary_value_sum": str(total),
                "actual_primary_value_sum": str(total),
                "manifest_file": first["source_file"].replace("data.ndjson", "manifest.json"),
                "source_verification_job_id": "synthetic-fixture",
                "snapshot_hash": source_digest(group),
            }
        )


def cases():
    result = []
    for value, status in [
        ("100", "PASS"),
        ("99.5", "PASS"),
        ("100.5", "PASS"),
        ("99.49", "WARN"),
        ("98", "WARN"),
        ("102", "WARN"),
        ("97.99", "FAIL"),
        ("102.01", "FAIL"),
    ]:
        result.append(("boundary_" + value, fixture((value,)), status))
    for value in (None, "0", "-1"):
        result.append(("world_" + str(value), fixture(world=value), "FAIL"))
    result.append(("special_coverage", fixture(("80",), special="20"), "PASS"))
    result.append(("overlap", fixture(overlap="100"), "PASS"))
    for name in (
        "duplicate",
        "null_amount",
        "negative",
        "unresolved",
        "classification",
        "wrong_version",
        "missing_dimension",
        "missing_load",
        "tampered_share",
        "world_duplicate",
        "empty",
        "source_mismatch",
        "stale_attestation",
    ):
        inputs = deepcopy(fixture())
        if name == "duplicate":
            inputs["candidate"].append(deepcopy(inputs["candidate"][0]))
            refresh(inputs)
        if name == "null_amount":
            inputs["candidate"][0]["primary_value"] = None
            refresh(inputs)
        if name == "negative":
            inputs["candidate"][0]["primary_value"] = "-60"
            refresh(inputs)
        if name == "unresolved":
            inputs["candidate"][0]["reconciliation_role"] = "unresolved"
        if name == "classification":
            inputs["candidate"][0]["classification_status"] = "needs_review"
        if name == "wrong_version":
            inputs["candidate"][0]["hs_version"] = "H5"
        if name == "missing_dimension":
            inputs["candidate"][0]["hs_mapping_found"] = False
        if name == "missing_load":
            inputs["loads"] = []
        if name == "tampered_share":
            inputs["candidate"][0]["market_share"] = "0.7"
        if name == "world_duplicate":
            inputs["world"] *= 2
            refresh(inputs)
        if name == "empty":
            inputs = {"candidate": [], "world": [], "detail": [], "loads": []}
        if name == "source_mismatch":
            inputs["detail"][0]["primary_value"] = "59"
        if name == "stale_attestation":
            inputs["loads"][0]["snapshot_hash"] = "stale"
        result.append((name, inputs, "FAIL"))
    return result
