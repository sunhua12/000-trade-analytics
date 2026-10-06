"""Verify source bytes before any warehouse mutation; never round money."""

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any


def numeric(value: object, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"-?\d+(?:\.\d+)?", value):
        raise ValueError("NUMERIC requires a canonical decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("invalid decimal") from error
    with localcontext() as context:
        context.prec = max(80, len(value) + 10)
        if abs(number) > Decimal("99999999999999999999999999999.999999999"):
            raise ValueError("NUMERIC overflow")
        if number != number.quantize(Decimal("0.000000001")):
            raise ValueError("NUMERIC precision loss")
    return format(number, "f")


def verify(data: bytes, manifest_bytes: bytes, source_uri: str) -> dict[str, Any]:
    """Return immutable-source metadata and normalized expected rows."""
    manifest = json.loads(manifest_bytes)
    digest = "sha256:" + hashlib.sha256(data).hexdigest()
    if manifest["checksum"] != digest:
        raise ValueError("checksum mismatch")
    if manifest["schema_version"] != "2.0.0" or manifest["hs_version"] != "H6":
        raise ValueError("unsupported schema or classification")
    period, kind, commodity = (manifest[k] for k in ("period", "query_type", "cmd_code"))
    if kind not in ("partner_detail", "world_total"):
        raise ValueError("invalid query type")
    datetime.strptime(period, "%Y%m")
    revision = manifest["revision"]
    if type(revision) is not int or revision < 1:
        raise ValueError("invalid revision")
    suffix = (
        f"/v2/hs_version=H6/cmd_code={commodity}/period={period}/"
        f"query_type={kind}/revision={revision}/data.ndjson"
    )
    if not source_uri.startswith("s3://") or not source_uri.endswith(suffix):
        raise ValueError("source path identity mismatch")
    timestamp = datetime.fromisoformat(manifest["ingested_at"].replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("source timestamp must include timezone")
    fixed = {
        "period": period,
        "reporterCode": 842,
        "flowCode": "M",
        "cmdCode": commodity,
        "partner2Code": 0,
        "customsCode": "C00",
        "motCode": 0,
    }
    if any(manifest["request_parameters"].get(k) != v for k, v in fixed.items()):
        raise ValueError("manifest request identity mismatch")
    if kind == "world_total" and manifest["request_parameters"].get("partnerCode") != 0:
        raise ValueError("World request must select partner 0")
    rows = [json.loads(line) for line in data.splitlines() if line.strip()]
    if len(rows) != manifest["row_count"]:
        raise ValueError("row count mismatch")
    expected = []
    seen = set()
    for row in rows:
        if any(
            row.get(k) != v
            for k, v in {**fixed, "freqCode": "M", "classificationCode": "H6"}.items()
        ):
            raise ValueError("row identity mismatch")
        partner = row.get("partnerCode")
        if type(partner) is not int or partner < 0:
            raise ValueError("invalid partner")
        if (kind == "world_total") != (partner == 0):
            raise ValueError("World/detail separation failed")
        if partner in seen:
            raise ValueError("duplicate grain")
        seen.add(partner)
        amount = numeric(row.get("primaryValue"))
        assert amount is not None
        if Decimal(amount) < 0 or (kind == "world_total" and Decimal(amount) <= 0):
            raise ValueError("invalid amount")
        expected.append(
            {
                "period": period,
                "period_start_date": f"{period[:4]}-{period[4:]}-01",
                "reporter_code": "842",
                "partner_code": str(partner),
                "cmd_code": commodity,
                "flow_code": "M",
                "hs_version": "H6",
                "primary_value": amount,
                "net_weight": numeric(row.get("netWgt"), nullable=True),
                "quantity": numeric(row.get("qty"), nullable=True),
            }
        )
    if kind == "world_total" and len(rows) != 1:
        raise ValueError("World must contain exactly one row")
    with localcontext() as context:
        context.prec = 80
        total = sum((Decimal(r["primary_value"]) for r in expected), Decimal(0))
    if total != Decimal(manifest["primary_value_sum"]):
        raise ValueError("amount sum mismatch")
    numeric(manifest["primary_value_sum"])
    fingerprint = hashlib.sha256(
        json.dumps(
            {k: v for k, v in manifest.items() if k != "checksum"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return {
        "manifest": manifest,
        "source_file": source_uri,
        "manifest_file": source_uri.removesuffix("data.ndjson") + "manifest.json",
        "contract_fingerprint": fingerprint,
        "expected": expected,
    }
