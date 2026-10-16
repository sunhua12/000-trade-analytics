"""Shared bounded BigQuery read settings for JSON export."""

import os
import re
from dataclasses import dataclass
from datetime import date

FIRST_MONTH = date(2023, 1, 1)
AFTER_LAST_MONTH = date(2025, 1, 1)
CMD_CODE = "8542"
HS_VERSION = "H6"
DATASET = "trade_analytics"


@dataclass(frozen=True)
class Settings:
    project: str
    dataset: str = DATASET
    location: str = "asia-northeast1"
    maximum_bytes_billed: int = 1_000_000_000
    first_month: date = FIRST_MONTH
    after_last_month: date = AFTER_LAST_MONTH

    def __post_init__(self) -> None:
        if (
            self.first_month.day != 1
            or self.after_last_month.day != 1
            or self.first_month >= self.after_last_month
            or (self.after_last_month.year - self.first_month.year) * 12
            + self.after_last_month.month
            - self.first_month.month
            > 60
        ):
            raise ValueError("展示範圍須為完整月份，且最多 60 個月")
        if not re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]", self.project):
            raise ValueError("TRADE_BQ_PROJECT 不是有效的 GCP 專案 ID")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,1023}", self.dataset):
            raise ValueError("TRADE_BQ_DATASET 不是有效的 Dataset ID")
        if not re.fullmatch(r"[a-z]+-[a-z]+\d", self.location):
            raise ValueError("TRADE_BQ_LOCATION 不是有效的 BigQuery location")
        if self.maximum_bytes_billed <= 0:
            raise ValueError("查詢處理量上限必須大於 0")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            project=os.environ.get("TRADE_BQ_PROJECT", "trade-analytics-508604"),
            dataset=os.environ.get("TRADE_BQ_DATASET", DATASET),
            location=os.environ.get("TRADE_BQ_LOCATION", "asia-northeast1"),
            maximum_bytes_billed=int(os.environ.get("TRADE_BQ_MAX_BYTES_BILLED", "1000000000")),
            first_month=date.fromisoformat(
                os.environ.get(
                    "TRADE_EXPORT_FIRST_MONTH",
                    os.environ.get("TRADE_DASHBOARD_FIRST_MONTH", "2023-01-01"),
                )
            ),
            after_last_month=date.fromisoformat(
                os.environ.get(
                    "TRADE_EXPORT_AFTER_LAST_MONTH",
                    os.environ.get("TRADE_DASHBOARD_AFTER_LAST_MONTH", "2025-01-01"),
                )
            ),
        )


def next_month(month: date) -> date:
    return date(month.year + (month.month == 12), month.month % 12 + 1, 1)


def validate_range(
    start: date, end: date, first: date = FIRST_MONTH, after_last: date = AFTER_LAST_MONTH
) -> None:
    if start.day != 1 or end.day != 1 or start > end:
        raise ValueError("請選擇有效且依時間排序的月份")
    if start < first or end >= after_last:
        raise ValueError("月份超出已規劃的展示範圍")
