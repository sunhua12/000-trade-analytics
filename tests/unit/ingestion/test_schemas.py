import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from trade_analytics.ingestion.schemas import ComtradeResponse

FIXTURE = Path("tests/fixtures/comtrade_preview_response.json")


def test_preview_response_maps_camel_case_fields() -> None:
    payload = json.loads(FIXTURE.read_text())

    response = ComtradeResponse.model_validate(payload)

    assert response.count == 3
    assert response.data[0].reporter_code == 842
    assert response.data[0].primary_value == 100.0


def test_nullable_weight_and_descriptions_are_accepted() -> None:
    payload = json.loads(FIXTURE.read_text())
    payload["data"][0]["netWgt"] = None
    payload["data"][0]["partnerDesc"] = None

    response = ComtradeResponse.model_validate(payload)

    assert response.data[0].net_weight is None
    assert response.data[0].partner_description is None


def test_missing_required_trade_key_is_rejected() -> None:
    payload = json.loads(FIXTURE.read_text())
    del payload["data"][0]["partnerCode"]

    with pytest.raises(ValidationError):
        ComtradeResponse.model_validate(payload)


def test_unknown_preview_fields_are_preserved() -> None:
    payload = json.loads(FIXTURE.read_text())
    payload["data"][0]["futureField"] = "future-value"

    response = ComtradeResponse.model_validate(payload)

    assert response.data[0].model_extra == {"futureField": "future-value"}
