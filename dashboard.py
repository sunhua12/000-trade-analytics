"""Run with: streamlit run dashboard.py"""

from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd
import streamlit as st
from google.api_core.exceptions import BadRequest, Forbidden

from trade_analytics.dashboard.queries import PublishedQueries, Settings, next_month

SETTINGS = Settings.from_env()


@st.cache_data(ttl=SETTINGS.cache_ttl_seconds)
def available_months() -> tuple[list[date], list[dict[str, Any]]]:
    queries = PublishedQueries(SETTINGS)
    return queries.months(), queries.jobs


@st.cache_data(ttl=SETTINGS.cache_ttl_seconds)
def available_partners(start: date, end: date) -> list[dict[str, Any]]:
    return PublishedQueries(SETTINGS).partners(start, end)


@st.cache_data(ttl=SETTINGS.cache_ttl_seconds)
def dashboard_data(
    start: date, end: date, partner_codes: tuple[str, ...], top_n: int
) -> dict[str, Any]:
    queries = PublishedQueries(SETTINGS)
    partners = list(partner_codes)
    result = {
        "rankings": queries.rankings(start, end, partners, top_n),
        "trend": queries.trend(start, end, partners),
        "world": queries.world_total(start, end),
        "quality": queries.quality(start, end),
    }
    result["jobs"] = queries.jobs
    return result


def money(value: Any) -> str:
    if value is None:
        return "資料不足"
    return f"USD {Decimal(str(value)):,.0f}"


def error_message(exc: Exception) -> str:
    if isinstance(exc, Forbidden):
        return "BigQuery 權限不足。請確認 ADC 已登入，且帳號可執行查詢並讀取正式資料集。"
    if isinstance(exc, BadRequest):
        message = str(exc).lower()
        if "maximum bytes billed" in message or "exceeds" in message and "bytes" in message:
            return "查詢超過處理量上限。請縮短日期區間，或檢查分區裁剪設定。"
        return f"BigQuery 查詢無效：{exc}"
    return f"查詢失敗：{exc}"


def month_spine(start: date, end: date) -> list[date]:
    months = []
    month = start
    while month <= end:
        months.append(month)
        month = next_month(month)
    return months


def quality_table_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "月份": row["period"],
            "已發布品質": row["published_quality_status"] or "未發布",
            "最新品質嘗試": row["latest_quality_status"] or "未檢查",
            "品質原因": "、".join(row["reason_codes"] or []),
            "最新發布嘗試": row["latest_publish_status"] or "未嘗試",
            "正式發布時間": row["published_at"],
            "最新品質檢查時間": row["latest_tested_at"],
        }
        for row in rows
    ]


def main() -> None:
    st.set_page_config(page_title="美國半導體進口分析", layout="wide")
    st.title("美國半導體進口分析")
    st.caption("正式發布資料｜美國月度進口｜HS 8542／H6｜金額單位：美元")
    with st.sidebar:
        st.header("篩選條件")
        if st.button("重新讀取已發布資料"):
            available_months.clear()
            available_partners.clear()
            dashboard_data.clear()
            st.rerun()

    try:
        months, option_jobs = available_months()
        if not months:
            st.info("指定的展示範圍尚無已發布月份。")
            return
        with st.sidebar:
            start = st.selectbox(
                "起始月份", months, index=0, format_func=lambda d: d.strftime("%Y-%m")
            )
            end = st.selectbox(
                "結束月份", months, index=len(months) - 1, format_func=lambda d: d.strftime("%Y-%m")
            )
            if start > end:
                st.warning("起始月份不可晚於結束月份。")
                return
            partner_rows = available_partners(start, end)
            labels = {
                row["partner_code"]: f"{row['partner_code']} · {row['source_name'] or '未提供名稱'}"
                for row in partner_rows
            }
            selected = st.multiselect(
                "Partner（未選＝全部已確認國家／地區）",
                list(labels),
                format_func=lambda code: labels[code],
            )
            top_n = st.slider("Top N", min_value=5, max_value=30, value=10, step=1)
            st.caption(f"查詢快取：{SETTINGS.cache_ttl_seconds} 秒；可手動重新讀取。")

        data = dashboard_data(start, end, tuple(sorted(selected)), top_n)
    except Exception as exc:
        st.error(error_message(exc))
        return

    world = data["world"]
    st.write(
        f"期間：{start:%Y-%m}～{end:%Y-%m}；Partner："
        + ("、".join(selected) if selected else "全部已確認國家／地區")
        + f"；排名顯示前 {top_n} 名。"
    )
    latest = world["latest_month"]
    latest_label = latest.strftime("%Y-%m") if latest else "尚未發布"
    a, b, c = st.columns(3)
    a.metric("已發布月份", str(world["published_months"]))
    b.metric("最新成功發布月份", latest_label)
    c.metric("期間 World 金額", money(world["world_value"]))
    st.caption(
        f"正式表最新發布時間：{world['latest_published_at'] or '未提供'}。"
        "World 每月只計一次，不加總夥伴列上的重複值。"
    )

    st.subheader("來源國／地區金額排名")
    rankings = data["rankings"]
    if rankings:
        denominator = world["world_value"]
        ranking_table = []
        for row in rankings:
            share = (
                Decimal(str(row["import_value"])) / Decimal(str(denominator)) * 100
                if denominator and row["import_value"] is not None
                else None
            )
            ranking_table.append(
                {
                    "代碼": row["partner_code"],
                    "來源國／地區": row["source_name"] or "未提供名稱",
                    "期間進口金額": money(row["import_value"]),
                    "占期間 World": f"{share:.2f}%" if share is not None else "資料不足",
                }
            )
        st.dataframe(ranking_table, hide_index=True, width="stretch")
        st.caption(
            "排名僅含已確認的國家／地區；490 等特殊代碼不列入。"
            "占比以期間各月 World 金額合計為分母。"
        )
    else:
        st.info("此篩選條件沒有可排名的來源國／地區資料。")

    st.subheader("月度進口趨勢")
    trend = data["trend"]
    if trend:
        by_month = {row["month"]: row["import_value"] for row in trend}
        frame = pd.DataFrame(
            {
                "月份": month_spine(start, end),
                "進口金額（USD）": [
                    float(by_month[month]) if by_month.get(month) is not None else None
                    for month in month_spine(start, end)
                ],
            }
        ).set_index("月份")
        st.line_chart(frame)
        st.caption(
            "僅加總已確認國家／地區的金額；缺月保留空白，不補成 0。"
            "圖表使用浮點數顯示，精確核對以 BigQuery NUMERIC 為準。"
        )
    else:
        st.info("此篩選條件沒有月度趨勢資料。")

    st.subheader("發布與品質摘要")
    quality = data["quality"]
    if quality:
        st.dataframe(
            quality_table_rows(quality),
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "最新品質嘗試與已發布版本分開顯示。最新嘗試 FAIL 時，正式資料仍可能是前一次成功版本。"
        )
    else:
        st.info("此期間沒有品質摘要。")

    with st.expander("查詢紀錄與限制"):
        for job in option_jobs + data["jobs"]:
            st.write(job)
        st.caption(
            "查詢處理量上限為每次查詢的 bytes 上限，並非費用硬上限。"
            "快取畫面可能晚於最新發布；需要時請按重新讀取。"
        )


if __name__ == "__main__":
    main()
