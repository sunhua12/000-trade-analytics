-- Real scope: 202301 / 8542 / H6. Month-level metrics must not be summed across partners.
SELECT run_id, status, partner_sum, country_sum, world_total, difference,
       difference_rate, country_coverage, reason_codes, tested_at, audit_json
FROM `trade-analytics-508604.trade_analytics_published.audit_world_reconciliation`
WHERE period='202301' AND cmd_code='8542' AND hs_version='H6';

SELECT partner_code, source_name, primary_value, market_share, mom, yoy,
       CASE WHEN previous_month_value IS NULL THEN 'missing_prior_month'
            WHEN previous_month_value<=0 THEN 'invalid_prior_value' ELSE 'ok' END mom_reason,
       CASE WHEN previous_year_value IS NULL THEN 'missing_prior_year'
            WHEN previous_year_value<=0 THEN 'invalid_prior_value' ELSE 'ok' END yoy_reason,
       unit_value_usd_per_kg,
       CASE WHEN net_weight IS NULL THEN 'missing_weight'
            WHEN net_weight<=0 THEN 'invalid_weight' ELSE 'ok' END unit_value_status,
       quality_status, published_at
FROM `trade-analytics-508604.trade_analytics_published.mart_us_semiconductor_supply_chain`
WHERE period_start_date=DATE '2023-01-01' AND partner_type='country'
ORDER BY primary_value DESC LIMIT 10;

SELECT DISTINCT period, country_coverage, hhi_raw, hhi, hhi_status
FROM `trade-analytics-508604.trade_analytics_published.mart_us_semiconductor_supply_chain`
WHERE period_start_date=DATE '2023-01-01';

SELECT partner_code, source_name, partner_type, reconciliation_role,
       primary_value, map_iso3, checksum, source_file, run_id, revision
FROM `trade-analytics-508604.trade_analytics_published.mart_us_semiconductor_supply_chain`
WHERE period_start_date=DATE '2023-01-01' AND partner_code='490';

SELECT *
FROM `trade-analytics-508604.trade_analytics_published.publication_quality_summary`
WHERE period='202301';
