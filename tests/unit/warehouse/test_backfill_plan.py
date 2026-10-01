"""Backfill preflight must reject unsafe ranges before cloud writes."""

from datetime import datetime

import pytest

from scripts import backfill_plan


def test_cross_year_range_and_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        backfill_plan,
        "datetime",
        type("Clock", (), {"now": staticmethod(lambda tz: datetime(2026, 10, 1, tzinfo=tz))}),
    )
    assert backfill_plan.periods_between("202412", "202502") == [
        "202412",
        "202501",
        "202502",
    ]
    for start, end in (("202412", "202503"), ("202503", "202501"), ("202609", "202610")):
        with pytest.raises(ValueError):
            backfill_plan.periods_between(start, end)


def test_invalid_config_fails_before_cloud_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        backfill_plan, "bigquery_client", lambda: pytest.fail("cloud client must not be used")
    )
    invalid = [
        {},
        {"start_period": "202501", "end_period": "202503", "extra": True},
        {"start_period": "202501", "end_period": "202503", "revisions": {"world_total": 1}},
        {
            "start_period": "202501",
            "end_period": "202503",
            "revisions": {"world_total": True, "partner_detail": 1},
        },
        {
            "start_period": "202501",
            "end_period": "202503",
            "replay_run_ids": {"202504": "other"},
        },
        {
            "start_period": "202501",
            "end_period": "202503",
            "recovery_probe": {"period": "202504", "kind": "partner_detail"},
        },
    ]
    for conf in invalid:
        with pytest.raises(ValueError):
            backfill_plan.plan(conf, "manual__test")


def test_preflight_skips_published_and_keeps_stable_run_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(backfill_plan, "bigquery_client", lambda: object())
    monkeypatch.setattr(backfill_plan.boto3, "client", lambda *args, **kwargs: object())
    monkeypatch.setattr(backfill_plan.httpx, "Client", lambda **kwargs: _ContextClient())
    monkeypatch.setattr(
        backfill_plan,
        "current_published",
        lambda client, period: "original" if period == "202502" else None,
    )
    checked: list[tuple[str, str]] = []

    def available(s3: object, http: object, period: str, kind: str, revision: int) -> bool:
        checked.append((period, kind))
        return True

    monkeypatch.setattr(backfill_plan, "source_available", available)
    conf = {"start_period": "202501", "end_period": "202503"}
    first = backfill_plan.plan(conf, "manual__same")
    second = backfill_plan.plan(conf, "manual__same")
    assert first == second
    assert [item["status"] for item in first["items"]] == [
        "ready",
        "already_published",
        "ready",
    ]
    assert all(period != "202502" for period, kind in checked)
    assert first["items"][0]["run_id"] != first["items"][2]["run_id"]


def test_unavailable_source_stops_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backfill_plan, "bigquery_client", lambda: object())
    monkeypatch.setattr(backfill_plan.boto3, "client", lambda *args, **kwargs: object())
    monkeypatch.setattr(backfill_plan.httpx, "Client", lambda **kwargs: _ContextClient())
    monkeypatch.setattr(backfill_plan, "current_published", lambda client, period: None)
    monkeypatch.setattr(
        backfill_plan,
        "source_available",
        lambda s3, http, period, kind, revision: kind == "partner_detail",
    )
    with pytest.raises(ValueError, match="source not available"):
        backfill_plan.plan({"start_period": "202501", "end_period": "202503"}, "manual__test")


def test_replay_requires_exact_published_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backfill_plan, "bigquery_client", lambda: object())
    monkeypatch.setattr(backfill_plan.boto3, "client", lambda *args, **kwargs: object())
    monkeypatch.setattr(backfill_plan.httpx, "Client", lambda **kwargs: _ContextClient())
    monkeypatch.setattr(backfill_plan, "current_published", lambda client, period: "original")
    monkeypatch.setattr(backfill_plan, "source_available", lambda *args: True)
    conf = {
        "start_period": "202501",
        "end_period": "202501",
        "replay_run_ids": {"202501": "wrong"},
    }
    with pytest.raises(ValueError, match="does not match"):
        backfill_plan.plan(conf, "manual__test")
    conf["replay_run_ids"]["202501"] = "original"
    assert backfill_plan.plan(conf, "manual__test")["items"][0]["run_id"] == "original"
    conf["recovery_probe"] = {"period": "202501", "kind": "partner_detail"}
    with pytest.raises(ValueError, match="requires an unpublished month"):
        backfill_plan.plan(conf, "manual__test")


class _ContextClient:
    def __enter__(self) -> "_ContextClient":
        return self

    def __exit__(self, *args: object) -> None:
        return None
