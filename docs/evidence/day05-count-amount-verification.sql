-- User-provided query job:
-- trade-analytics-508604:asia-northeast1.job_BR1B1pqmsdZptFv-yq_JVs67prOx
SELECT
  'partner_detail' AS query_type,
  COUNT(*) AS row_count,
  SUM(CAST(primaryValue AS NUMERIC)) AS total_value
FROM `trade-analytics-508604.trade_landing.day05_partner_detail_202301_r1`
UNION ALL
SELECT
  'world_total' AS query_type,
  COUNT(*) AS row_count,
  SUM(CAST(primaryValue AS NUMERIC)) AS total_value
FROM `trade-analytics-508604.trade_landing.day05_world_total_202301_r1`;
