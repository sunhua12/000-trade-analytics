from copy import deepcopy
from decimal import Decimal

import pytest

from scripts.quality_fixture import cases, fixture
from trade_analytics.warehouse.quality import assess, partition


@pytest.mark.parametrize("name,inputs,expected", cases(), ids=[c[0] for c in cases()])
def test_quality_contract(name, inputs, expected):
    result = assess(inputs, partition("202301"))
    assert result["status"] == expected, (name, result)
    if expected == "FAIL":
        assert result["reason_codes"]


def test_coverage_is_independent_from_reconciliation():
    result = assess(fixture(("80",), special="20"), partition("202301"))
    assert result["status"] == "PASS"
    assert result["difference"] == 0
    assert result["country_coverage"] == Decimal(".8")


def test_all_blocking_reasons_survive():
    data = deepcopy(fixture())
    data["loads"] = []
    data["candidate"][0]["reconciliation_role"] = "unresolved"
    data["world"] = []
    reasons = assess(data, partition("202301"))["reason_codes"]
    assert {"unresolved_reconciliation", "world_count", "load_not_verified_partner_detail"} <= set(
        reasons
    )


@pytest.mark.parametrize("period", ["202313", "20231", "2023-01", "000001"])
def test_invalid_partition(period):
    with pytest.raises(ValueError):
        partition(period)


def test_sum_preserving_source_corruption_is_blocked():
    data = fixture()
    data["detail"][0]["primary_value"] = "59"
    data["detail"][1]["primary_value"] = "41"
    result = assess(data, partition("202301"))
    assert result["status"] == "FAIL"
    assert "load_not_verified_partner_detail" in result["reason_codes"]
    assert "candidate_source_mismatch" in result["reason_codes"]


def test_preview_limit_is_not_a_valid_complete_partition():
    data = fixture(tuple("0.2" for _ in range(500)))
    result = assess(data, partition("202301"))
    assert result["status"] == "FAIL"
    assert "possible_truncation" in result["reason_codes"]


def test_missing_required_identity_is_blocked():
    data = fixture()
    data["candidate"][0]["checksum"] = None
    data["candidate"][0]["revision"] = 0
    result = assess(data, partition("202301"))
    assert {"missing_lineage_or_key", "invalid_revision"} <= set(result["reason_codes"])


def test_source_digest_preserves_full_numeric_precision():
    from trade_analytics.warehouse.quality import source_digest

    data = fixture()
    other = deepcopy(data["detail"])
    data["detail"][0]["primary_value"] = "12345678901234567890123456789.123456789"
    other[0]["primary_value"] = "12345678901234567890123456789.123456788"
    assert source_digest(data["detail"]) != source_digest(other)
