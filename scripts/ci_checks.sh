#!/usr/bin/env bash
set -euo pipefail
python -m ruff format --check src tests scripts dags
python -m ruff check src tests scripts dags
# The project's strict type contract applies to the reusable application package.
# Scripts, DAG and representative tests are linted separately.
python -m mypy -p trade_analytics
python -m pytest tests/unit -q --cov=trade_analytics --cov-report=json
