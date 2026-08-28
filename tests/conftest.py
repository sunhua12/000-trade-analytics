import json
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def preview_payload() -> dict[str, Any]:
    fixture = Path("tests/fixtures/comtrade_preview_response.json")
    return json.loads(fixture.read_text())
