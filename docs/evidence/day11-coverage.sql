-- One row per target month, including months without a source or published data.
WITH months AS (
  SELECT FORMAT_DATE('%Y%m', month) period
  FROM UNNEST(GENERATE_DATE_ARRAY(DATE '2023-01-01', DATE '2024-12-01', INTERVAL 1 MONTH)) month
), detail AS (
  SELECT period, COUNT(*) detail_rows, SUM(primary_value) detail_amount,
    COUNT(DISTINCT checksum) detail_checksums, COUNT(DISTINCT revision) detail_revisions
  FROM `trade-analytics-508604.trade_raw.un_comtrade_partner_detail`
  WHERE period_start_date >= DATE '2023-01-01' AND period_start_date < DATE '2025-01-01'
    AND cmd_code = '8542' AND hs_version = 'H6'
  GROUP BY period
), world AS (
  SELECT period, COUNT(*) world_rows, SUM(primary_value) world_amount,
    COUNT(DISTINCT checksum) world_checksums, COUNT(DISTINCT revision) world_revisions
  FROM `trade-analytics-508604.trade_raw.un_comtrade_world_total`
  WHERE period_start_date >= DATE '2023-01-01' AND period_start_date < DATE '2025-01-01'
    AND cmd_code = '8542' AND hs_version = 'H6'
  GROUP BY period
), quality AS (
  SELECT period, status quality_status, reason_codes, run_id latest_quality_run_id,
    tested_at latest_tested_at
  FROM `trade-analytics-508604.trade_analytics_published.quality_audit_history`
  WHERE cmd_code = '8542' AND hs_version = 'H6'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY period ORDER BY tested_at DESC, run_id DESC) = 1
), attestations AS (
  SELECT JSON_VALUE(attestation_json, '$.period') period,
    COUNTIF(JSON_VALUE(attestation_json, '$.query_type') = 'partner_detail') detail_attestations,
    COUNTIF(JSON_VALUE(attestation_json, '$.query_type') = 'world_total') world_attestations
  FROM `trade-analytics-508604.trade_analytics_published.source_attestations`
  WHERE JSON_VALUE(attestation_json, '$.status') = 'snapshot_verified'
  GROUP BY period
), published AS (
  SELECT period, COUNT(*) published_rows, ANY_VALUE(published_run_id) published_run_id,
    MAX(published_at) published_at
  FROM `trade-analytics-508604.trade_analytics_published.mart_us_semiconductor_supply_chain`
  WHERE period_start_date >= DATE '2023-01-01' AND period_start_date < DATE '2025-01-01'
    AND cmd_code = '8542' AND hs_version = 'H6'
  GROUP BY period
)
SELECT m.period, d.detail_rows, d.detail_amount, d.detail_checksums, d.detail_revisions,
  w.world_rows, w.world_amount, w.world_checksums, w.world_revisions,
  a.detail_attestations, a.world_attestations,
  q.quality_status, q.reason_codes, q.latest_quality_run_id, q.latest_tested_at,
  p.published_rows, p.published_run_id, p.published_at
FROM months m
LEFT JOIN detail d USING (period)
LEFT JOIN world w USING (period)
LEFT JOIN attestations a USING (period)
LEFT JOIN quality q USING (period)
LEFT JOIN published p USING (period)
ORDER BY m.period;
