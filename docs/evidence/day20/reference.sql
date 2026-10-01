-- Read-only, fixed 8542/H6, original 24-month scope; World once per month.
-- name: monthly
SELECT period, ANY_VALUE(world_value) world_value,
 ANY_VALUE(country_coverage) country_coverage, ANY_VALUE(hhi) hhi,
 ANY_VALUE(hhi_status) hhi_status, COUNT(*) row_count,
 COUNT(DISTINCT partner_code) distinct_partners
FROM `trade-analytics-508604.trade_analytics_published.mart_us_semiconductor_supply_chain`
WHERE period_start_date >= DATE '2023-01-01' AND period_start_date < DATE '2025-01-01'
 AND cmd_code='8542' AND hs_version='H6'
GROUP BY period ORDER BY period;
-- name: ranking
SELECT partner_code, ANY_VALUE(source_name) source_name, SUM(primary_value) amount
FROM `trade-analytics-508604.trade_analytics_published.mart_us_semiconductor_supply_chain`
WHERE period_start_date >= DATE '2024-01-01' AND period_start_date < DATE '2025-01-01'
 AND cmd_code='8542' AND hs_version='H6' AND partner_type='country'
GROUP BY partner_code ORDER BY amount DESC LIMIT 10;
-- name: april
SELECT period, ANY_VALUE(world_value) world_value, COUNT(*) row_count,
 COUNT(DISTINCT partner_code) distinct_partners,
 ANY_VALUE(published_run_id) published_run_id, MAX(published_at) published_at
FROM `trade-analytics-508604.trade_analytics_published.mart_us_semiconductor_supply_chain`
WHERE period_start_date=DATE '2025-04-01' AND cmd_code='8542' AND hs_version='H6'
GROUP BY period;
