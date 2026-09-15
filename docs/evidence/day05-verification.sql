-- Run after both transfers complete. Check NUMERIC precision before interpreting sums.
WITH loaded AS (
  SELECT 'partner_detail' AS query_type, period, cmdCode,
         classificationCode, partnerCode, primaryValue
  FROM `trade-analytics-508604.trade_landing.day05_partner_detail_202301_r1`
  UNION ALL
  SELECT 'world_total', period, cmdCode,
         classificationCode, partnerCode, primaryValue
  FROM `trade-analytics-508604.trade_landing.day05_world_total_202301_r1`
)
SELECT
  query_type,
  COUNT(*) AS row_count,
  COUNTIF(primaryValue IS NULL
          OR SAFE_CAST(primaryValue AS NUMERIC) IS NULL) AS invalid_amounts,
  COUNTIF(period IS NULL OR period != '202301'
          OR cmdCode IS NULL OR cmdCode != '8542'
          OR classificationCode IS NULL
          OR classificationCode != 'H6') AS invalid_identity,
  COUNTIF(partnerCode IS NULL) AS missing_partner,
  COUNTIF(partnerCode = 0) AS world_rows,
  SUM(CAST(primaryValue AS NUMERIC)) AS primary_value_sum
FROM loaded
GROUP BY query_type;
