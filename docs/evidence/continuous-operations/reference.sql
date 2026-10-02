-- Read-only verification, fixed US imports 8542/H6; at most 1 GB billed per query.
-- name: monthly
SELECT period, COUNT(*) row_count, COUNT(DISTINCT partner_code) distinct_partners,
 COUNT(DISTINCT published_run_id) run_count,
 ANY_VALUE(world_value) world_value, SUM(primary_value) partner_sum,
 ANY_VALUE(published_run_id) published_run_id, MAX(published_at) published_at,
 ANY_VALUE(country_coverage) country_coverage, ANY_VALUE(hhi_status) hhi_status
FROM `trade-analytics-508604.trade_analytics_published.mart_us_semiconductor_supply_chain`
WHERE cmd_code='8542' AND hs_version='H6'
GROUP BY period ORDER BY period;
-- name: raw
WITH inputs AS (
 SELECT 'partner_detail' kind, * FROM `trade-analytics-508604.trade_raw.un_comtrade_partner_detail`
 WHERE period_start_date >= DATE '2023-01-01' AND period_start_date < DATE '2026-08-01'
 UNION ALL
 SELECT 'world_total' kind, * FROM `trade-analytics-508604.trade_raw.un_comtrade_world_total`
 WHERE period_start_date >= DATE '2023-01-01' AND period_start_date < DATE '2026-08-01'
)
SELECT kind, FORMAT_DATE('%Y%m',period_start_date) period,
 COUNT(*) row_count, COUNT(DISTINCT partner_code) distinct_partners,
 COUNT(DISTINCT checksum) checksum_count, COUNT(DISTINCT revision) revision_count,
 SUM(primary_value) amount,
 COUNTIF(reporter_code!='842' OR flow_code!='M') invalid_dimensions
FROM inputs WHERE cmd_code='8542' AND hs_version='H6'
GROUP BY kind, period ORDER BY period, kind;
-- name: quality
SELECT period, latest_run_id, latest_quality_status, reason_codes,
 latest_tested_at, published_run_id, published_at, published_quality_status
FROM `trade-analytics-508604.trade_analytics_published.publication_quality_summary`
WHERE cmd_code='8542' AND hs_version='H6' ORDER BY period;
