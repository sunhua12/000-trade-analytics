"""Run with: streamlit run dashboard.py"""

from datetime import UTC, date, datetime
from decimal import Decimal
from math import log10
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
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
    rankings = queries.rankings(start, end, partners, top_n)
    result = {
        "rankings": rankings,
        "trend": queries.trend(start, end, partners),
        "world": queries.world_total(start, end),
        "quality": queries.quality(start, end),
        "monthly": queries.monthly_metrics(start, end),
        "partner_metrics": queries.partner_metrics(start, end, partners[0])
        if len(partners) == 1
        else [],
        "scatter": queries.scatter(end, [row["partner_code"] for row in rankings])
        if rankings
        else [],
        "map_values": queries.map_values(start, end, partners),
    }
    result["read_at"] = datetime.now(UTC)
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


def world_yoy(rows: list[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    """Compare World amounts for matching calendar months, never adjacent rows."""
    by_month = {row["month"]: row["world_value"] for row in rows}
    result = []
    for month in month_spine(start, end):
        previous = by_month.get(date(month.year - 1, month.month, 1))
        current = by_month.get(month)
        yoy = (
            Decimal(str(current)) / Decimal(str(previous)) - 1
            if current is not None and previous is not None and previous > 0
            else None
        )
        result.append({"月份": month, "YoY": yoy})
    return result


def display_time(value: Any) -> str:
    if value is None:
        return "未提供"
    if isinstance(value, datetime):
        return (
            value.astimezone(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d %H:%M:%S") + " Asia/Taipei"
        )
    return str(value)


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
    world_billions = (
        f"USD {Decimal(str(world['world_value'])) / Decimal(1_000_000_000):,.2f}B"
        if world["world_value"] is not None
        else "資料不足"
    )
    c.metric("期間 World 金額", world_billions)
    st.caption(
        f"期間 World 精確金額：{money(world['world_value'])}。"
        "World 每月只計一次，不加總夥伴列上的重複值。"
    )

    st.subheader("資料新鮮度")
    latest_attempt = max(
        (
            row.get("latest_attempted_at")
            for row in data["quality"]
            if row.get("latest_attempted_at")
        ),
        default=None,
    )
    st.write(
        f"所選期間最新資料月份：{latest_label}；"
        f"所選期間最近成功發布：{display_time(world['latest_published_at'])}；"
        f"所選期間最新發布嘗試：{display_time(latest_attempt)}；"
        f"畫面資料讀取：{display_time(data['read_at'])}。"
    )
    st.caption(
        "展示期間固定為 2023-01～2024-12。畫面可能使用 1 小時快取；"
        "重新讀取按鈕可取得新的正式版本。最新失敗嘗試不會更新正式資料。"
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
        ranking_chart = pd.DataFrame(
            {
                "來源國／地區": [
                    f"{row['partner_code']} · {row['source_name']}" for row in rankings
                ],
                "進口金額（USD）": [float(row["import_value"]) for row in rankings],
            },
        ).set_index("來源國／地區")
        st.bar_chart(ranking_chart, horizontal=True)
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

    st.subheader("年增率 YoY")
    if len(selected) == 1:
        yoy_rows = [{"月份": row["month"], "YoY": row["yoy"]} for row in data["partner_metrics"]]
        st.caption(f"來源國／地區 {selected[0]} 的本月金額與去年同月比較。")
    else:
        yoy_rows = world_yoy(data["monthly"], start, end)
        st.caption("World 月度金額與去年同月比較；此參考指標不隨 Partner 多選改變。")
    yoy_table = [
        {
            "月份": row["月份"].strftime("%Y-%m"),
            "YoY": f"{Decimal(str(row['YoY'])):.2%}" if row["YoY"] is not None else "無可比較基期",
        }
        for row in yoy_rows
    ]
    if yoy_table:
        st.dataframe(yoy_table, hide_index=True, width="stretch")
        yoy_frame = pd.DataFrame(
            {
                "月份": [row["月份"] for row in yoy_rows],
                "YoY（%）": [
                    float(row["YoY"] * 100) if row["YoY"] is not None else None for row in yoy_rows
                ],
            }
        ).set_index("月份")
        if yoy_frame["YoY（%）"].notna().any():
            st.line_chart(yoy_frame)
    else:
        st.info("此條件沒有可顯示的 YoY 資料。")
    st.caption("缺去年同月或基期不大於 0 時保留空白；百分比不加總或平均。")

    st.subheader("國家覆蓋與 HHI 狀態")
    monthly = [row for row in data["monthly"] if start <= row["month"] <= end]
    if monthly:
        coverage_rows = [
            {
                "月份": row["month"].strftime("%Y-%m"),
                "國家覆蓋率": f"{Decimal(str(row['country_coverage'])):.2%}"
                if row["country_coverage"] is not None
                else "資料不足",
                "HHI": f"{Decimal(str(row['hhi'])):,.2f}"
                if row["hhi_status"] == "ok" and row["hhi"] is not None
                else "資料不足",
                "HHI 狀態": row["hhi_status"] or "未提供",
            }
            for row in monthly
        ]
        st.dataframe(coverage_rows, hide_index=True, width="stretch")
        coverage_frame = pd.DataFrame(
            {
                "月份": [row["month"] for row in monthly],
                "國家覆蓋率（%）": [
                    float(row["country_coverage"] * 100)
                    if row["country_coverage"] is not None
                    else None
                    for row in monthly
                ],
            }
        ).set_index("月份")
        if coverage_frame["國家覆蓋率（%）"].notna().any():
            st.line_chart(coverage_frame)
        if not any(row["hhi_status"] == "ok" and row["hhi"] is not None for row in monthly):
            st.info("所選月份的 HHI 均不可顯示；請查看各月覆蓋率與狀態。")
        st.caption(
            "HHI 以 World 為分母，僅在國家覆蓋差距不超過 0.5% 且狀態為 ok 時顯示。"
            "品質 PASS 不代表 HHI 可用。"
        )
    else:
        st.info("此期間沒有逐月覆蓋資料。")

    st.subheader("來源國／地區地圖")
    map_rows = data["map_values"]
    mapped = [row for row in map_rows if row["map_iso3"]]
    unmapped = [row for row in map_rows if not row["map_iso3"]]
    if mapped:
        map_frame = pd.DataFrame(
            {
                "ISO3": [row["map_iso3"] for row in mapped],
                "進口金額（USD）": [float(row["import_value"]) for row in mapped],
                "地圖色階": [log10(float(row["import_value"]) + 1) for row in mapped],
            }
        )
        figure = px.choropleth(
            map_frame,
            locations="ISO3",
            locationmode="ISO-3",
            color="地圖色階",
            color_continuous_scale="Oranges",
            projection="natural earth",
            hover_data={"進口金額（USD）": ":,.0f", "地圖色階": False},
        )
        figure.update_geos(
            showocean=True,
            oceancolor="#0E1117",
            showland=True,
            landcolor="#1B2733",
            showcountries=True,
            countrycolor="#637081",
            showcoastlines=True,
            coastlinecolor="#637081",
            bgcolor="#0E1117",
        )
        figure.update_layout(
            margin={"l": 0, "r": 0, "t": 0, "b": 0},
            paper_bgcolor="#0E1117",
            font_color="#F9FAFB",
            coloraxis_colorbar_title="log10(USD+1)",
        )
        st.plotly_chart(figure, width="stretch")
        st.caption(
            f"期間 {start:%Y-%m}～{end:%Y-%m}；地圖僅含已確認國家／地區。"
            f"無地圖碼來源列：{sum(row['source_rows'] for row in unmapped)}；"
            f"未映射金額：{money(sum((row['import_value'] for row in unmapped), Decimal(0)))}。"
            "顏色使用對數尺度，精確金額請看排名表。特殊代碼 490 不畫入地圖。"
        )
    else:
        st.info("此範圍沒有可映射的國家／地區資料。")

    st.subheader("最新月份：進口金額與 YoY")
    scatter = data["scatter"]
    if scatter:
        scatter_frame = pd.DataFrame(
            {
                "來源國／地區": [
                    f"{row['partner_code']} · {row['source_name']}" for row in scatter
                ],
                "進口金額（USD）": [float(row["import_value"]) for row in scatter],
                "YoY（%）": [float(row["yoy"] * 100) for row in scatter],
            }
        )
        st.scatter_chart(scatter_frame, x="進口金額（USD）", y="YoY（%）")
        st.dataframe(scatter_frame, hide_index=True, width="stretch")
        st.caption(
            f"每點為 {end:%Y-%m} 的一個已確認國家／地區；"
            f"僅從所選期間排名前 {top_n} 名中取金額與 YoY 均有效的資料。"
            f"有效點數：{len(scatter)}。"
        )
    else:
        st.info("最新月份沒有可比較的來源國／地區散佈資料。")

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
