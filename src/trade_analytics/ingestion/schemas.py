"""Pydantic models for UN Comtrade Preview API responses."""

from pydantic import BaseModel, ConfigDict, Field


class TradeRecord(BaseModel):
    """One trade record returned by the Preview API."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    type_code: str | None = Field(default=None, alias="typeCode")
    frequency_code: str | None = Field(default=None, alias="freqCode")
    reference_period_id: int | None = Field(default=None, alias="refPeriodId")
    reference_year: int | None = Field(default=None, alias="refYear")
    reference_month: int | None = Field(default=None, alias="refMonth")
    period: str
    reporter_code: int = Field(alias="reporterCode")
    reporter_iso: str | None = Field(default=None, alias="reporterISO")
    reporter_description: str | None = Field(default=None, alias="reporterDesc")
    flow_code: str = Field(alias="flowCode")
    flow_description: str | None = Field(default=None, alias="flowDesc")
    partner_code: int = Field(alias="partnerCode")
    partner_iso: str | None = Field(default=None, alias="partnerISO")
    partner_description: str | None = Field(default=None, alias="partnerDesc")
    partner_2_code: int = Field(alias="partner2Code")
    partner_2_iso: str | None = Field(default=None, alias="partner2ISO")
    partner_2_description: str | None = Field(default=None, alias="partner2Desc")
    classification_code: str = Field(alias="classificationCode")
    classification_search_code: str | None = Field(default=None, alias="classificationSearchCode")
    is_original_classification: bool | None = Field(default=None, alias="isOriginalClassification")
    cmd_code: str = Field(alias="cmdCode")
    cmd_description: str | None = Field(default=None, alias="cmdDesc")
    aggregate_level: int | None = Field(default=None, alias="aggrLevel")
    is_leaf: bool | None = Field(default=None, alias="isLeaf")
    customs_code: str = Field(alias="customsCode")
    customs_description: str | None = Field(default=None, alias="customsDesc")
    mode_of_supply_code: str | None = Field(default=None, alias="mosCode")
    mot_code: int = Field(alias="motCode")
    mot_description: str | None = Field(default=None, alias="motDesc")
    quantity_unit_code: int | None = Field(default=None, alias="qtyUnitCode")
    quantity_unit_abbreviation: str | None = Field(default=None, alias="qtyUnitAbbr")
    quantity: float | None = Field(default=None, alias="qty")
    is_quantity_estimated: bool | None = Field(default=None, alias="isQtyEstimated")
    alternate_quantity_unit_code: int | None = Field(default=None, alias="altQtyUnitCode")
    alternate_quantity_unit_abbreviation: str | None = Field(default=None, alias="altQtyUnitAbbr")
    alternate_quantity: float | None = Field(default=None, alias="altQty")
    is_alternate_quantity_estimated: bool | None = Field(default=None, alias="isAltQtyEstimated")
    net_weight: float | None = Field(default=None, alias="netWgt")
    is_net_weight_estimated: bool | None = Field(default=None, alias="isNetWgtEstimated")
    gross_weight: float | None = Field(default=None, alias="grossWgt")
    is_gross_weight_estimated: bool | None = Field(default=None, alias="isGrossWgtEstimated")
    cif_value: float | None = Field(default=None, alias="cifvalue")
    fob_value: float | None = Field(default=None, alias="fobvalue")
    primary_value: float | None = Field(default=None, alias="primaryValue")
    legacy_estimation_flag: int | None = Field(default=None, alias="legacyEstimationFlag")
    is_reported: bool | None = Field(default=None, alias="isReported")
    is_aggregate: bool | None = Field(default=None, alias="isAggregate")


class ComtradeResponse(BaseModel):
    """Top-level Preview API response envelope."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    elapsed_time: str | None = Field(default=None, alias="elapsedTime")
    count: int
    data: list[TradeRecord]
    error: str = ""
