"""Run the Streamlit UI against published data and save compact evidence."""

import json
from datetime import UTC, date, datetime
from importlib import import_module
from pathlib import Path
from typing import Any


def metrics(app: Any) -> dict[str, str]:
    return {item.label: item.value for item in app.metric}


def assert_clean(app: Any) -> None:
    if app.exception or app.error:
        raise AssertionError(
            f"Streamlit UI failed: {[item.message for item in app.exception]} "
            f"{[item.value for item in app.error]}"
        )


def main() -> None:
    app_test = import_module("streamlit.testing.v1").AppTest
    app = app_test.from_file(Path("dashboard.py").resolve(), default_timeout=120).run()
    assert_clean(app)
    default = metrics(app)
    if default["已發布月份"] != "24" or default["最新成功發布月份"] != "2024-12":
        raise AssertionError(f"Unexpected default metrics: {default}")

    app.selectbox[0].set_value(date(2024, 1, 1)).run()
    assert_clean(app)
    app.multiselect[0].set_value(["458"]).run()
    assert_clean(app)
    app.slider[0].set_value(5).run()
    assert_clean(app)
    filtered = metrics(app)
    if filtered["已發布月份"] != "12" or app.multiselect[0].value != ["458"]:
        raise AssertionError(f"Filters did not apply: {filtered}")
    table_rows = [len(table.value) for table in app.dataframe]
    if table_rows != [1, 12]:
        raise AssertionError(f"Unexpected ranking/quality rows: {table_rows}")

    app.selectbox[0].set_value(date(2024, 12, 1))
    app.selectbox[1].set_value(date(2024, 1, 1))
    app.run()
    if app.exception or not any("起始月份不可晚於結束月份" in w.value for w in app.warning):
        raise AssertionError("Reverse date range was not rejected")

    evidence = {
        "verified_at_utc": datetime.now(UTC).isoformat(),
        "default_metrics": default,
        "filtered_metrics": filtered,
        "filtered_partner": "458",
        "filtered_top_n": 5,
        "filtered_ranking_rows": table_rows[0],
        "filtered_quality_rows": table_rows[1],
        "reverse_date_rejected": True,
        "streamlit_exceptions": 0,
    }
    path = Path("docs/evidence/day12-ui-verification.json")
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
