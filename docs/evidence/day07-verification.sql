-- Day 7：唯讀人工驗證 SQL；在 BigQuery Console 逐段執行。
-- Project：trade-analytics-508604；Location：asia-northeast1。
-- 本檔保存已使用的查核查詢，不包含備份、刪除或 fixture 注入操作。

-- 1. 欄位型別：兩張 staging 共 30 個欄位。
select table_name, column_name, data_type
from `trade-analytics-508604.trade_analytics_dev.INFORMATION_SCHEMA.COLUMNS`
where table_name in (
    'stg_un_comtrade__partner_trades', 'stg_un_comtrade__world_totals'
)
order by table_name, ordinal_position;

-- 2. 月份維度：24 列，起訖 2023-01-01／2024-12-01，閏年月底 2024-02-29。
select
    count(*) as month_count,
    min(month_start_date) as first_month,
    max(month_start_date) as last_month,
    max(if(period = '202402', month_end_date, null)) as feb_2024_end
from `trade-analytics-508604.trade_analytics_dev.dim_months`;

-- 3. 缺月展示：先分別彙總，避免明細與 World 連接時重複加總。
-- 清理後 202301 為 67／1 筆，金額各 2799575181；其他月份維持 NULL。
with partner as (
    select period_start_date, count(*) as partner_rows,
        sum(primary_value) as partner_value
    from `trade-analytics-508604.trade_analytics_dev.stg_un_comtrade__partner_trades`
    where period_start_date >= date '2023-01-01'
      and period_start_date < date '2025-01-01'
    group by 1
), world as (
    select period_start_date, count(*) as world_rows,
        sum(primary_value) as world_value
    from `trade-analytics-508604.trade_analytics_dev.stg_un_comtrade__world_totals`
    where period_start_date >= date '2023-01-01'
      and period_start_date < date '2025-01-01'
    group by 1
)
select m.period, p.partner_rows, p.partner_value, w.world_rows, w.world_value
from `trade-analytics-508604.trade_analytics_dev.dim_months` as m
left join partner as p on m.month_start_date = p.period_start_date
left join world as w on m.month_start_date = w.period_start_date
order by m.period;

-- 4. 特殊代碼、NULL 重量與來源追蹤抽查。
select period, partner_code, primary_value, net_weight, quantity,
    source_file, run_id, revision
from `trade-analytics-508604.trade_analytics_dev.stg_un_comtrade__partner_trades`
where period_start_date >= date '2023-01-01'
  and period_start_date < date '2023-02-01'
  and (partner_code = '490' or net_weight is null)
order by partner_code;

-- 5. 二月 raw 追查；清理前找到 day06-isolation-test，清理後應無資料。
-- 此預期對應本次單月驗收，未來合法載入二月後不再適用。
select period, period_start_date, reporter_code, partner_code, flow_code,
    cmd_code, hs_version, primary_value, ingested_at, source_file,
    checksum, run_id, revision
from `trade-analytics-508604.trade_raw.un_comtrade_partner_detail`
where period_start_date >= date '2023-02-01'
  and period_start_date < date '2023-03-01';

-- Grain、契約、非空與 raw 雙向保真比較，使用 dbt/tests/ 的已驗收測試。
-- assert_partner_grain_unique.sql、assert_world_grain_unique.sql
-- assert_january_2023_exists.sql、assert_staging_contract.sql
-- assert_staging_matches_raw.sql、assert_month_spine_complete.sql
