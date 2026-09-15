import pytest
from pydantic import ValidationError

from trade_analytics.ingestion.queries import ComtradeQuery, QueryType


def test_partner_detail_parameters_fix_us_monthly_import_scope() -> None:
    query = ComtradeQuery(
        period="202401",
        cmd_code="8542",
        query_type=QueryType.PARTNER_DETAIL,
    )

    assert query.to_params() == {
        "reporterCode": 842,
        "period": "202401",
        "cmdCode": "8542",
        "flowCode": "M",
        "partner2Code": 0,
        "customsCode": "C00",
        "motCode": 0,
    }


def test_world_total_parameters_explicitly_request_world_partner() -> None:
    query = ComtradeQuery(
        period="202401",
        cmd_code="8542",
        query_type=QueryType.WORLD_TOTAL,
    )

    assert query.to_params()["partnerCode"] == 0


@pytest.mark.parametrize("period", ["2024", "202413", "20240101", "abcdef"])
def test_period_must_be_a_valid_year_month(period: str) -> None:
    with pytest.raises(ValidationError):
        ComtradeQuery(period=period, cmd_code="8542", query_type=QueryType.PARTNER_DETAIL)


@pytest.mark.parametrize("cmd_code", ["8", "854", "85421", "ABCDEF"])
def test_cmd_code_must_be_two_four_or_six_digits(cmd_code: str) -> None:
    with pytest.raises(ValidationError):
        ComtradeQuery(period="202401", cmd_code=cmd_code, query_type=QueryType.PARTNER_DETAIL)


@pytest.mark.parametrize("revision", [0, -1, True, 1.5, "2"])
def test_revision_requires_a_positive_integer(revision: object) -> None:
    with pytest.raises(ValidationError):
        ComtradeQuery.model_validate({"query_type": "partner_detail", "revision": revision})


def test_h6_is_an_acceptance_rule_not_an_api_parameter() -> None:
    query = ComtradeQuery(query_type=QueryType.PARTNER_DETAIL, revision=2)
    assert query.expected_hs_version == "H6"
    assert "revision" not in query.to_params()
    assert "expected_hs_version" not in query.to_params()
    with pytest.raises(ValidationError):
        ComtradeQuery.model_validate({"query_type": "partner_detail", "expected_hs_version": "H5"})
