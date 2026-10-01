#!/usr/bin/env bash
set -euo pipefail
python -m ruff format --check src tests scripts dags ingest.py dashboard.py
python -m ruff check src tests scripts dags ingest.py dashboard.py
# The project's strict type contract applies to the reusable application package.
# Historical verification scripts and Airflow decorators are linted and tested separately.
python -m mypy -p trade_analytics
python -m pytest tests/unit -q --cov=trade_analytics --cov-report=json --cov-fail-under=80
python scripts/check_coverage.py coverage.json
