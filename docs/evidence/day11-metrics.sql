-- Monthly interpretation checks after all 24 months are published.
WITH published AS (
  SELECT period, primary_value, mom, yoy, unit_value_usd_per_kg,
    country_coverage, hhi, hhi_status
  FROM `trade-analytics-508604.trade_analytics_published.mart_us_semiconductor_supply_chain`
  WHERE period_start_date >= DATE '2023-01-01' AND period_start_date < DATE '2025-01-01'
    AND cmd_code = '8542' AND hs_version = 'H6'
), monthly AS (
  SELECT period, COUNT(*) partner_rows, SUM(primary_value) partner_amount,
    COUNTIF(mom IS NOT NULL) mom_rows, COUNTIF(yoy IS NOT NULL) yoy_rows,
    COUNTIF(unit_value_usd_per_kg IS NOT NULL) unit_value_rows,
    MAX(country_coverage) country_coverage, COUNTIF(hhi IS NOT NULL) visible_hhi_rows,
    STRING_AGG(DISTINCT hhi_status, ', ' ORDER BY hhi_status) hhi_status
  FROM published GROUP BY period
), quality AS (
  SELECT period, status, difference_rate, partner_sum, world_total
  FROM `trade-analytics-508604.trade_analytics_published.audit_world_reconciliation`
  WHERE cmd_code = '8542' AND hs_version = 'H6'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY period ORDER BY tested_at DESC, run_id DESC) = 1
)
SELECT m.*, q.status quality_status, q.difference_rate, q.partner_sum, q.world_total
FROM monthly m JOIN quality q USING (period)
ORDER BY period;
