"""Validated query definitions for the UN Comtrade Preview API."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class QueryType(StrEnum):
    """Supported logical UN Comtrade extracts."""

    PARTNER_DETAIL = "partner_detail"
    WORLD_TOTAL = "world_total"


class ComtradeQuery(BaseModel):
    """A validated monthly U.S. semiconductor import query."""

    model_config = ConfigDict(frozen=True)

    period: str = "202401"
    cmd_code: str = "8542"
    query_type: QueryType
    expected_hs_version: Literal["H6"] = "H6"
    revision: int = Field(default=1, gt=0, strict=True)

    @field_validator("period")
    @classmethod
    def validate_period(cls, value: str) -> str:
        try:
            parsed = datetime.strptime(value, "%Y%m")
        except ValueError as error:
            raise ValueError("period must be a valid YYYYMM value") from error
        if parsed.strftime("%Y%m") != value:
            raise ValueError("period must use YYYYMM")
        return value

    @field_validator("cmd_code")
    @classmethod
    def validate_cmd_code(cls, value: str) -> str:
        if not value.isdigit() or len(value) not in {2, 4, 6}:
            raise ValueError("cmd_code must contain 2, 4, or 6 digits")
        return value

    def to_params(self) -> dict[str, str | int]:
        """Return Preview API query parameters for this extract."""
        params: dict[str, str | int] = {
            "reporterCode": 842,
            "period": self.period,
            "cmdCode": self.cmd_code,
            "flowCode": "M",
            "partner2Code": 0,
            "customsCode": "C00",
            "motCode": 0,
        }
        if self.query_type is QueryType.WORLD_TOTAL:
            params["partnerCode"] = 0
        return params
