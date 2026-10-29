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
    """A validated monthly semiconductor import query."""

    model_config = ConfigDict(frozen=True)

    period: str = "202401"
    cmd_code: str = "854231"
    query_type: QueryType
    reporter_code: int = Field(default=842, gt=0, strict=True)
    reporter_codes: tuple[int, ...] = ()
    expected_hs_version: Literal["H0", "H1", "H2", "H3", "H4", "H5", "H6"] = "H6"
    revision: int = Field(default=1, gt=0, strict=True)

    @field_validator("reporter_codes")
    @classmethod
    def validate_reporters(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if len(values) > 10 or len(set(values)) != len(values) or any(v <= 0 for v in values):
            raise ValueError("reporter group requires at most ten unique positive codes")
        return values

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
        if value not in {"854231", "854232", "854233", "854239", "854290"}:
            raise ValueError("unsupported IC commodity")
        return value

    def to_params(self) -> dict[str, str | int]:
        """Return Preview API query parameters for this extract."""
        params: dict[str, str | int] = {
            "reporterCode": (
                ",".join(map(str, self.reporter_codes))
                if self.reporter_codes
                else self.reporter_code
            ),
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
