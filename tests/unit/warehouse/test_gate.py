import hashlib
import json
from copy import deepcopy
from typing import Any

import pytest

from trade_analytics.warehouse.gate import numeric, verify

URI = "s3://bucket/un_comtrade/v2/hs_version=H6/cmd_code=8542/period=202301/query_type=partner_detail/revision=1/data.ndjson"


def artifacts() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    row = {
        "period": "202301",
        "reporterCode": 842,
        "flowCode": "M",
        "cmdCode": "8542",
        "partner2Code": 0,
        "customsCode": "C00",
        "motCode": 0,
        "partnerCode": 490,
        "freqCode": "M",
        "classificationCode": "H6",
        "primaryValue": "10.01",
        "netWgt": None,
        "qty": "0",
    }
    m = {
        "schema_version": "2.0.0",
        "hs_version": "H6",
        "period": "202301",
        "query_type": "partner_detail",
        "cmd_code": "8542",
        "revision": 1,
        "row_count": 1,
        "primary_value_sum": "10.01",
        "ingested_at": "2026-09-12T12:00:00Z",
        "request_parameters": {
            k: row[k]
            for k in (
                "period",
                "reporterCode",
                "flowCode",
                "cmdCode",
                "partner2Code",
                "customsCode",
                "motCode",
            )
        },
    }
    return [row], m


def encode(rows: list[dict[str, Any]], m: dict[str, Any]) -> tuple[bytes, bytes]:
    data = ("\n".join(json.dumps(r) for r in rows) + "\n").encode()
    return data, json.dumps(
        {**m, "checksum": "sha256:" + hashlib.sha256(data).hexdigest()}
    ).encode()


@pytest.mark.parametrize(
    "value", ["0.0000000001", "100000000000000000000000000000", "NaN", "Infinity", "bad", 1.2, None]
)
def test_numeric_rejects_rounding_overflow_and_invalid(value: object) -> None:
    with pytest.raises(ValueError):
        numeric(value)


def test_numeric_boundary_and_nullable() -> None:
    assert numeric("99999999999999999999999999999.999999999") is not None
    assert numeric("1.0000000000") == "1.0000000000"
    assert numeric(None, nullable=True) is None


def test_source_bytes_and_490_preserved() -> None:
    data, m = encode(*artifacts())
    result = verify(data, m, URI)
    assert result["expected"][0]["partner_code"] == "490"
    assert result["expected"][0]["net_weight"] is None
    with pytest.raises(ValueError, match="checksum"):
        verify(data + b"\n", m, URI)
    with pytest.raises(ValueError, match="path"):
        verify(data, m, URI.replace("revision=1", "revision=2"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("period", "202302"),
        ("reporterCode", None),
        ("freqCode", None),
        ("netWgt", "bad"),
        ("qty", "0.00000000001"),
        ("primaryValue", "-1"),
        ("partnerCode", 0),
        ("partnerCode", None),
    ],
)
def test_row_gate_rejects_dirty_source(field: str, value: object) -> None:
    rows, m = artifacts()
    rows[0][field] = value
    with pytest.raises(ValueError):
        verify(*encode(rows, m), URI)


def test_duplicate_grain_and_amount_mismatch() -> None:
    rows, m = artifacts()
    rows.append(deepcopy(rows[0]))
    m["row_count"] = 2
    with pytest.raises(ValueError, match="duplicate"):
        verify(*encode(rows, m), URI)
    rows.pop()
    m.update(row_count=1, primary_value_sum="9.99")
    with pytest.raises(ValueError, match="sum"):
        verify(*encode(rows, m), URI)
