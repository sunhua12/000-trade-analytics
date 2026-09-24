"""Exercise the Day 13 Streamlit display with published BigQuery data."""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from streamlit.testing.v1 import AppTest


def check(app: Any) -> None:
    if app.exception or app.error:
        raise AssertionError(
            f"UI exceptions: {[item.message for item in app.exception]}; "
            f"errors: {[item.value for item in app.error]}"
        )


def main() -> None:
    app = AppTest.from_file(Path("dashboard.py").resolve(), default_timeout=120).run()
    check(app)
    if not any("均不可顯示" in item.value for item in app.info):
        raise AssertionError("Missing HHI unavailability message")
    if not any("資料新鮮度" in item.value for item in app.subheader):
        raise AssertionError("Missing freshness section")
    if len(app.get("plotly_chart")) != 1:
        raise AssertionError("Expected one country map")
    default_tables = [len(table.value) for table in app.dataframe]
    if default_tables != [10, 24, 24, 10, 24]:
        raise AssertionError(f"Unexpected default table scopes: {default_tables}")

    app.selectbox[0].set_value(date(2024, 1, 1)).run()
    check(app)
    app.multiselect[0].set_value(["458"]).run()
    check(app)
    filtered_tables = [len(table.value) for table in app.dataframe]
    if filtered_tables != [1, 12, 12, 1, 12]:
        raise AssertionError(f"Unexpected filtered ranking/YoY/coverage: {filtered_tables}")
    if not any("來源國／地區 458" in item.value for item in app.caption):
        raise AssertionError("Partner YoY scope is not shown")

    evidence = {
        "verified_at_utc": datetime.now(UTC).isoformat(),
        "default_table_rows": default_tables,
        "filtered_table_rows": filtered_tables,
        "partner": "458",
        "filtered_months": "202401-202412",
        "hhi_unavailable_message": True,
        "freshness_section": True,
        "country_map": True,
        "streamlit_exceptions": 0,
    }
    path = Path("docs/evidence/day13-ui-verification.json")
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
