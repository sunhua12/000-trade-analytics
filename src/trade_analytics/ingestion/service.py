"""Application service enforcing the UN Comtrade ingestion contract."""

from dataclasses import dataclass
from typing import Protocol

from trade_analytics.ingestion.exceptions import DataContractError, EmptyDataError
from trade_analytics.ingestion.queries import ComtradeQuery, QueryType
from trade_analytics.ingestion.schemas import ComtradeResponse, TradeRecord


class ComtradeFetcher(Protocol):
    """Boundary implemented by an HTTP client that fetches one query."""

    def fetch(self, query: ComtradeQuery) -> ComtradeResponse:
        """Fetch one response for the supplied query."""
        ...


@dataclass(frozen=True)
class IngestionDataset:
    """Validated records ready for deterministic serialization."""

    query: ComtradeQuery
    rows: tuple[TradeRecord, ...]


class IngestionService:
    """Coordinate retrieval, filtering, and data-contract validation."""

    def __init__(self, client: ComtradeFetcher) -> None:
        self._client = client

    def fetch_dataset(self, query: ComtradeQuery) -> IngestionDataset:
        """Fetch and validate the logical dataset requested by query."""
        response = self._client.fetch(query)
        for row in response.data:
            self._validate_core_contract(row, query)

        if query.query_type is QueryType.PARTNER_DETAIL:
            rows = tuple(row for row in response.data if row.partner_code != 0)
            if not rows:
                raise EmptyDataError(
                    f"No partner_detail records remained for period {query.period}"
                )
            self._validate_unique_grain(rows)
            return IngestionDataset(query=query, rows=rows)

        if any(row.partner_code != 0 for row in response.data):
            raise DataContractError("world_total response contained non-world partner records")
        if len(response.data) != 1:
            raise DataContractError("world_total response must contain exactly one World record")
        value = response.data[0].primary_value
        if value is None or value <= 0:
            raise DataContractError("world_total primaryValue must be greater than zero")
        return IngestionDataset(query=query, rows=tuple(response.data))

    @staticmethod
    def _validate_core_contract(row: TradeRecord, query: ComtradeQuery) -> None:
        expected_fields = {
            "classification_code": query.expected_hs_version,
            "frequency_code": "M",
            "partner_2_code": 0,
            "customs_code": "C00",
            "mot_code": 0,
        }
        for field, expected in expected_fields.items():
            if getattr(row, field) != expected:
                raise DataContractError(f"record {field} must equal {expected}")
        value = row.primary_value
        if value is None or not value.is_finite() or value < 0:
            raise DataContractError("primaryValue must be a finite non-negative amount")
        if row.period != query.period:
            raise DataContractError(
                f"record period {row.period} did not match requested period {query.period}"
            )
        if row.reporter_code != 842:
            raise DataContractError(
                f"record reporter {row.reporter_code} was not U.S. reporter 842"
            )
        if row.flow_code != "M":
            raise DataContractError(f"record flow {row.flow_code} was not import flow M")
        if row.cmd_code != query.cmd_code:
            raise DataContractError(
                f"record commodity {row.cmd_code} did not match requested {query.cmd_code}"
            )

    @staticmethod
    def _validate_unique_grain(rows: tuple[TradeRecord, ...]) -> None:
        seen: set[tuple[str, int, str]] = set()
        for row in rows:
            key = (row.period, row.partner_code, row.cmd_code)
            if key in seen:
                raise DataContractError(
                    "duplicate grain detected for "
                    f"period={row.period}, partnerCode={row.partner_code}, cmdCode={row.cmd_code}"
                )
            seen.add(key)
