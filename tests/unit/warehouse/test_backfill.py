"""Critical revision decisions must fail closed before raw mutation."""

import pytest

from trade_analytics.warehouse.backfill import canonical, decision, source_key


def test_revision_decisions() -> None:
    current = [{"revision": 2, "checksum": "sha256:a"}]
    assert decision([], 1, "sha256:a") == "load"
    assert decision(current, 3, "sha256:b") == "load"
    assert decision(current, 2, "sha256:a") == "already_loaded"
    assert decision(current, 2, "sha256:b") == "conflict"
    assert decision(current, 1, "sha256:a") == "stale_revision"
    with pytest.raises(ValueError, match="mixes source versions"):
        decision(current + [{"revision": 1, "checksum": "sha256:b"}], 3, "sha256:c")


def test_source_identity_rejects_out_of_range() -> None:
    assert "period=202402/query_type=world_total/revision=1" in source_key("202402", "world_total")
    for period in ("202212", "202501", "202313"):
        with pytest.raises(ValueError):
            source_key(period, "world_total")


def test_snapshot_comparison_keeps_nulls_and_decimal_precision() -> None:
    template = {"primary_value": "1.000000001", "net_weight": None, "quantity": "0.00"}
    assert canonical(template) == canonical(
        {"primary_value": "1.000000001", "net_weight": None, "quantity": "0"}
    )
    assert canonical(template) != canonical(
        {"primary_value": "1.000000002", "net_weight": None, "quantity": "0"}
    )
