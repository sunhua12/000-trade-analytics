import httpx
import pytest

from trade_analytics.ingestion.client import ComtradeClient
from trade_analytics.ingestion.queries import ComtradeQuery, QueryType
from trade_analytics.ingestion.service import IngestionService

pytestmark = pytest.mark.integration


@pytest.fixture
def live_service() -> IngestionService:
    timeout = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0)
    client = httpx.Client()
    service = IngestionService(ComtradeClient(http_client=client, timeout=timeout))
    yield service
    client.close()


def test_live_partner_detail_contract(live_service: IngestionService) -> None:
    query = ComtradeQuery(
        period="202401",
        cmd_code="8542",
        query_type=QueryType.PARTNER_DETAIL,
    )

    dataset = live_service.fetch_dataset(query)

    assert 0 < len(dataset.rows) < ComtradeClient.PREVIEW_RECORD_LIMIT
    assert all(row.period == "202401" for row in dataset.rows)
    assert all(row.reporter_code == 842 for row in dataset.rows)
    assert all(row.flow_code == "M" for row in dataset.rows)
    assert all(row.partner_code != 0 for row in dataset.rows)
    assert all(row.cmd_code == "8542" for row in dataset.rows)


def test_live_world_total_contract(live_service: IngestionService) -> None:
    query = ComtradeQuery(
        period="202401",
        cmd_code="8542",
        query_type=QueryType.WORLD_TOTAL,
    )

    dataset = live_service.fetch_dataset(query)

    assert len(dataset.rows) == 1
    assert dataset.rows[0].partner_code == 0
    assert dataset.rows[0].flow_code == "M"
    assert dataset.rows[0].primary_value is not None
