"""Validated settings for the one supported multi-market pipeline."""

import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from trade_analytics.ingestion.multi_market import MARKETS, periods
from trade_analytics.warehouse.read_settings import Settings, next_month

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class PipelineConfig:
    start: str
    end: str
    root: Path = ROOT / "data/multi-market"
    reporters: tuple[int, ...] = tuple(MARKETS)
    max_requests: int = 100
    refresh: bool = False
    full_refresh: bool = False
    extract_only: bool = False
    sync_only: bool = False
    output: Path = ROOT / "data/frontend-v2"
    frontend_data: Path = ROOT / "frontend/public/data"

    run_id: str = ""
    artifact_prefix: str = "_pipeline"
    raw_prefix: str = "un_comtrade"

    months: list[str] = field(init=False, repr=False)
    api_key: str | None = field(init=False, repr=False)
    dbt_executable: str = field(init=False)
    raw_bucket: str = field(init=False)
    raw_project: str = field(init=False)
    raw_dataset: str = field(init=False)
    settings: Settings = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.run_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", self.run_id):
            raise ValueError("invalid run id")
        object.__setattr__(
            self,
            "dbt_executable",
            os.environ.get("TRADE_DBT_EXECUTABLE", str(ROOT / ".venv-dbt/bin/dbt")),
        )
        for field_name, env_name in (
            ("raw_bucket", "RAW_BUCKET"),
            ("raw_project", "DBT_RAW_PROJECT"),
            ("raw_dataset", "DBT_RAW_DATASET"),
        ):
            object.__setattr__(self, field_name, os.environ.get(env_name, ""))
        object.__setattr__(self, "months", periods(self.start, self.end))
        object.__setattr__(self, "api_key", os.environ.get("COMTRADE_API_KEY"))
        if not self.reporters or len(set(self.reporters)) != len(self.reporters):
            raise ValueError("reporters must be nonempty and unique")
        if any(r not in MARKETS for r in self.reporters):
            raise ValueError("unsupported reporter")
        if type(self.max_requests) is not int or self.max_requests < 1:
            raise ValueError("max_requests must be positive")
        if self.extract_only and self.sync_only:
            raise ValueError("extract-only and sync-only are mutually exclusive")
        if self.sync_only and self.refresh:
            raise ValueError("sync-only cannot refresh extracts")
        settings = Settings(
            project=os.environ.get(
                "TRADE_BQ_PROJECT", os.environ.get("DBT_RAW_PROJECT", "trade-analytics-508604")
            ),
            dataset=os.environ.get("TRADE_BQ_DATASET", "trade_analytics"),
            location=os.environ.get("TRADE_BQ_LOCATION", "asia-northeast1"),
            maximum_bytes_billed=int(os.environ.get("TRADE_BQ_MAX_BYTES_BILLED", "1000000000")),
            first_month=date(2016, 1, 1),
            after_last_month=next_month(date(int(self.end[:4]), int(self.end[4:]), 1)),
        )
        object.__setattr__(self, "settings", settings)
        if not self.extract_only:
            missing = [
                name
                for name, value in (
                    ("RAW_BUCKET", self.raw_bucket),
                    ("DBT_RAW_PROJECT", self.raw_project),
                    ("DBT_RAW_DATASET", self.raw_dataset),
                )
                if not value
            ]
            if missing:
                raise ValueError("missing settings: " + ", ".join(missing))
            if not re.fullmatch(r"[a-z][a-z0-9-]+", self.raw_project):
                raise ValueError("invalid raw project")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.raw_dataset):
                raise ValueError("invalid raw dataset")
