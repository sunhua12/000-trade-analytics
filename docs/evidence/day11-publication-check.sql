-- The current published rows must equal their own frozen candidate batches,
-- including partner rows removed by a later source revision.
WITH published AS (
  SELECT * FROM `trade-analytics-508604.trade_analytics_published.mart_us_semiconductor_supply_chain`
  WHERE period_start_date >= DATE '2023-01-01' AND period_start_date < DATE '2025-01-01'
    AND cmd_code = '8542' AND hs_version = 'H6'
), current_batches AS (
  SELECT c.* FROM `trade-analytics-508604.trade_analytics_published.candidate_batches` c
  JOIN (SELECT DISTINCT period, published_run_id FROM published) p
    ON c.period = p.period AND c.candidate_batch_id = p.published_run_id
  WHERE c.period_start_date >= DATE '2023-01-01' AND c.period_start_date < DATE '2025-01-01'
    AND c.cmd_code = '8542' AND c.hs_version = 'H6'
), differences AS (
  (SELECT * EXCEPT(quality_status, published_at, published_run_id) FROM published
   EXCEPT DISTINCT SELECT * FROM current_batches)
  UNION ALL
  (SELECT * FROM current_batches EXCEPT DISTINCT
   SELECT * EXCEPT(quality_status, published_at, published_run_id) FROM published)
)
SELECT (SELECT COUNT(*) FROM differences) difference_rows,
  (SELECT COUNT(*) FROM published) published_rows,
  (SELECT COUNT(*) FROM current_batches) frozen_rows,
  (SELECT COUNT(DISTINCT period) FROM published) published_months,
  (SELECT COUNT(*) - COUNT(DISTINCT CONCAT(period, ':', partner_code)) FROM published)
    duplicate_grain_rows,
  (SELECT COUNTIF(quality_status NOT IN ('PASS', 'WARN')) FROM published) invalid_quality_rows;
