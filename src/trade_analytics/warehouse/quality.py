"""Pure, fail-closed quality rules shared by production and fixture verification."""

import hashlib
import json
from collections import Counter
from datetime import datetime
from decimal import Decimal, localcontext
from typing import Any

RULE_VERSION = "reconciliation-v1"
PASS_MAX = Decimal("0.005")
WARN_MAX = Decimal("0.02")
HHI_GAP = Decimal("0.005")
SOURCE_COLUMNS = (
    "period",
    "period_start_date",
    "reporter_code",
    "partner_code",
    "flow_code",
    "cmd_code",
    "hs_version",
    "primary_value",
    "net_weight",
    "quantity",
    "ingested_at",
    "source_file",
    "checksum",
    "run_id",
    "revision",
)


def partition(period: str, commodity: str = "8542", version: str = "H6") -> dict[str, str]:
    if len(period) != 6 or not period.isdigit():
        raise ValueError("period must be YYYYMM")
    day = datetime.strptime(period, "%Y%m").strftime("%Y-%m-01")
    if commodity != "8542" or version != "H6":
        raise ValueError("MVP supports 8542/H6 only")
    return {
        "period": period,
        "period_start_date": day,
        "cmd_code": commodity,
        "hs_version": version,
    }


def number(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except ArithmeticError:
        return None


def source_digest(rows: list[dict[str, Any]]) -> str:
    """Fingerprint normalized source rows, not only their count and sum."""
    numeric_columns = {"primary_value", "net_weight", "quantity", "revision"}
    normalized = []
    for row in rows:
        item = {}
        for key in SOURCE_COLUMNS:
            value = row.get(key)
            if key in numeric_columns and value is not None:
                with localcontext() as ctx:
                    ctx.prec = 60
                    value = format(Decimal(str(value)).normalize(), "f")
            item[key] = value
        normalized.append(json.dumps(item, sort_keys=True, default=str))
    return hashlib.sha256("\n".join(sorted(normalized)).encode()).hexdigest()


def assess(inputs: dict[str, Any], scope: dict[str, str]) -> dict[str, Any]:
    """Never infer source acceptance merely from a balanced total."""
    with localcontext() as ctx:
        ctx.prec = 60
        return _assess(inputs, scope)


def _assess(inputs: dict[str, Any], scope: dict[str, str]) -> dict[str, Any]:
    rows = inputs.get("candidate", [])
    detail = inputs.get("detail", [])
    world = inputs.get("world", [])
    loads = inputs.get("loads", [])
    reasons: set[str] = set()
    if not rows or not detail:
        reasons.add("missing_detail")
    if len(world) != 1:
        reasons.add("world_count")
    for label, group in (("candidate", rows), ("detail", detail), ("world", world)):
        keys = [
            tuple(r.get(k) for k in ("period_start_date", "partner_code", "cmd_code", "hs_version"))
            for r in group
        ]
        if len(set(keys)) != len(keys):
            reasons.add("duplicate_" + label)
        for r in group:
            if (
                any(r.get(k) != v for k, v in scope.items())
                or r.get("reporter_code") != "842"
                or r.get("flow_code") != "M"
            ):
                reasons.add("fixed_dimensions")
            if any(
                r.get(k) in (None, "")
                for k in SOURCE_COLUMNS
                if k not in ("net_weight", "quantity")
            ):
                reasons.add("missing_lineage_or_key")
            revision = number(r.get("revision"))
            if revision is None or revision <= 0 or revision != revision.to_integral_value():
                reasons.add("invalid_revision")
            value = number(r.get("primary_value"))
            if value is None or value < 0:
                reasons.add("invalid_amount")
            if (label == "world") != (r.get("partner_code") == "0"):
                reasons.add("world_detail_separation")

    def source_key(r: dict[str, Any]) -> tuple[str, ...]:
        return tuple(str(r.get(k)) for k in SOURCE_COLUMNS)

    if Counter(map(source_key, rows)) != Counter(map(source_key, detail)):
        reasons.add("candidate_source_mismatch")
    if len(detail) >= 500:
        reasons.add("possible_truncation")
    if any(
        r.get("classification_status") != "verified"
        or r.get("partner_type") not in ("country", "special", "aggregate")
        for r in rows
    ):
        reasons.add("unreviewed_classification")
    if any(r.get("reconciliation_role") not in ("detail", "overlap") for r in rows):
        reasons.add("unresolved_reconciliation")
    if any(
        not all(
            r.get(k) is True
            for k in ("country_mapping_found", "hs_mapping_found", "month_mapping_found")
        )
        for r in rows
    ):
        reasons.add("missing_dimension")
    # Verify a fresh byte-to-raw attestation, including identity and manifest totals.
    accepted = []
    for kind, group in (("partner_detail", detail), ("world_total", world)):
        identities = {
            tuple(str(r.get(k)) for k in ("run_id", "revision", "checksum", "source_file"))
            for r in group
        }
        load_total = sum((number(r.get("primary_value")) or Decimal(0) for r in group), Decimal(0))
        matches = [
            a
            for a in loads
            if a.get("query_type") == kind
            and a.get("status") == "snapshot_verified"
            and all(a.get(k) == scope[k] for k in ("period", "cmd_code", "hs_version"))
            and tuple(str(a.get(k)) for k in ("run_id", "revision", "checksum", "source_file"))
            in identities
            and a.get("expected_row_count") == len(group) == a.get("actual_row_count")
            and number(a.get("expected_primary_value_sum"))
            == load_total
            == number(a.get("actual_primary_value_sum"))
            and a.get("source_verification_job_id")
            and a.get("snapshot_hash") == source_digest(group)
            and a.get("manifest_file")
        ]
        if len(identities) != 1 or not matches:
            reasons.add("load_not_verified_" + kind)
        else:
            accepted.append(max(matches, key=lambda a: str(a.get("event_at", ""))))
    eligible = [r for r in rows if r.get("reconciliation_role") == "detail"]
    countries = [r for r in rows if r.get("partner_type") == "country"]
    overlaps = [r for r in rows if r.get("reconciliation_role") == "overlap"]

    def total(group: list[dict[str, Any]]) -> Decimal | None:
        values = [number(r.get("primary_value")) for r in group]
        return (
            sum((v for v in values if v is not None), Decimal(0))
            if values and None not in values
            else None
        )

    partner_sum, country_sum = total(eligible), total(countries)
    world_total = number(world[0].get("primary_value")) if len(world) == 1 else None
    if world_total is None or world_total <= 0:
        reasons.add("invalid_world")
        world_total = None
    difference = (
        partner_sum - world_total if partner_sum is not None and world_total is not None else None
    )
    rate = abs(difference) / world_total if difference is not None and world_total else None
    coverage = country_sum / world_total if country_sum is not None and world_total else None
    if rate is None:
        reasons.add("unavailable_reconciliation")
    elif rate > WARN_MAX:
        reasons.add("reconciliation_exceeds_tolerance")

    # Verify metrics on the exact frozen batch, including HHI suppression.
    def near(actual: Any, expected: Decimal | None, tolerance: str = "0.000000002") -> bool:
        got = number(actual)
        return (
            got is None
            and expected is None
            or got is not None
            and expected is not None
            and abs(got - expected) <= Decimal(tolerance)
        )

    hhi = (
        sum(
            (
                ((number(r.get("primary_value")) or Decimal(0)) / world_total * 100) ** 2
                for r in countries
            ),
            Decimal(0),
        )
        if world_total
        else None
    )
    hhi_ok = coverage is not None and abs(1 - coverage) <= HHI_GAP and bool(countries)
    for r in rows:
        value, weight = number(r.get("primary_value")), number(r.get("net_weight"))
        share = value / world_total if value is not None and world_total else None
        unit = value / weight if value is not None and weight is not None and weight > 0 else None
        checks = [
            near(r.get("market_share"), share),
            near(r.get("world_value"), world_total),
            near(r.get("unit_value_usd_per_kg"), unit),
            near(r.get("country_coverage"), coverage),
            near(r.get("hhi"), hhi if hhi_ok else None, "0.00002"),
        ]
        for metric, prior in (("mom", "previous_month_value"), ("yoy", "previous_year_value")):
            base = number(r.get(prior))
            checks.append(
                near(
                    r.get(metric),
                    value / base - 1
                    if value is not None and base is not None and base > 0
                    else None,
                )
            )
        if not all(checks) or (r.get("hhi_status") == "ok") != hhi_ok:
            reasons.add("candidate_metric_contract")
    status = "FAIL" if reasons else "WARN" if rate is not None and rate > PASS_MAX else "PASS"
    if status == "WARN":
        reasons.add("reconciliation_warning")
    return {
        **scope,
        "status": status,
        "reason_codes": sorted(reasons),
        "rule_version": RULE_VERSION,
        "pass_max": str(PASS_MAX),
        "warn_max": str(WARN_MAX),
        "hhi_max_coverage_gap": str(HHI_GAP),
        "detail_row_count": len(detail),
        "candidate_row_count": len(rows),
        "world_row_count": len(world),
        "partner_sum": partner_sum,
        "country_sum": country_sum,
        "world_total": world_total,
        "difference": difference,
        "difference_rate": rate,
        "country_coverage": coverage,
        "unresolved_count": sum(
            r.get("reconciliation_role") not in ("detail", "overlap") for r in rows
        ),
        "excluded_overlap_count": len(overlaps),
        "excluded_overlap_sum": total(overlaps),
        "accepted_load_events": accepted,
    }
