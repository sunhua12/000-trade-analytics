import json
from pathlib import Path
from typing import Any

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="run tests that call live external services",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-integration"):
        return
    skip_integration = pytest.mark.skip(reason="requires --run-integration")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


@pytest.fixture
def preview_payload() -> dict[str, Any]:
    fixture = Path("tests/fixtures/comtrade_preview_response.json")
    payload = json.loads(fixture.read_text())
    assert isinstance(payload, dict), "Preview fixture must be a JSON object"
    return payload
