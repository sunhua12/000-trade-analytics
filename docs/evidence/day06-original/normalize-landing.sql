-- =============================================================================
-- 步驟 1：建立正規化暫存表 (Temp Table)
-- =============================================================================
CREATE TEMP TABLE tmp_normalized_partner_detail AS
SELECT
  -- 1. 分區與維度轉換
  CAST(period AS STRING) AS period,
  PARSE_DATE('%Y%m%d', CONCAT(period, '01')) AS period_start_date,
  CAST(reporterCode AS STRING) AS reporter_code,
  CAST(partnerCode AS STRING) AS partner_code,
  CAST(partner2Code AS STRING) AS partner2_code,
  CAST(cmdCode AS STRING) AS cmd_code,
  CAST(flowCode AS STRING) AS flow_code,
  CAST(customsCode AS STRING) AS customs_code,
  CAST(motCode AS STRING) AS mot_code,
  CAST(classificationCode AS STRING) AS hs_version,

  -- 2. 高精度無損數值轉換（若解析失敗為 NULL，Gate 會直接抓到）
  SAFE_CAST(primaryValue AS NUMERIC) AS primary_value,
  SAFE_CAST(netWgt AS NUMERIC) AS net_weight,
  SAFE_CAST(qty AS NUMERIC) AS quantity,

  -- 3. 補充 Metadata 與血緣資訊
  TIMESTAMP('2026-09-15T07:48:00Z') AS ingested_at,
  's3://trade-analytics-prod-816079797958-ap-northeast-1-an/un_comtrade/v2/hs_version=H6/cmd_code=8542/period=202301/query_type=partner_detail/revision=1/data.ndjson' AS source_file,
  'e3b0c442...' AS checksum,
  'day06-partner-202301' AS run_id,
  1 AS revision
FROM `trade-analytics-508604.trade_landing.day05_partner_detail_202301_r1`;

-- =============================================================================
-- 步驟 2：緊接著執行 Manifest Gate 體檢查詢
-- =============================================================================
SELECT
  -- 關卡 1 & 2：筆數與加總金額核對（對照 S3 Manifest）
  COUNT(*) AS actual_row_count,
  SUM(primary_value) AS actual_primary_value_sum,

  -- 關卡 3：主鍵粒度（Grain）檢查（不能為 NULL 且不能有重複）
  COUNTIF(period_start_date IS NULL OR partner_code IS NULL OR cmd_code IS NULL OR hs_version IS NULL) AS null_grain_count,
  COUNT(*) - COUNT(DISTINCT CONCAT(period_start_date, '-', partner_code, '-', cmd_code, '-', hs_version)) AS duplicate_grain_count,

  -- 關卡 4：契約固定維度檢查（違反者應為 0）
  COUNTIF(
    period != '202301' OR
    reporter_code != '842' OR
    flow_code != 'M' OR
    cmd_code != '8542' OR
    hs_version != 'H6' OR
    partner2_code != '0' OR
    customs_code != 'C00' OR
    mot_code != '0'
  ) AS invalid_contract_dimension_count,

  -- 關卡 5：明細表隔離（不可包含 partnerCode = 0，金額不可小於 0 且不可為 NULL）
  COUNTIF(partner_code = '0' OR primary_value < 0 OR primary_value IS NULL) AS invalid_detail_count

FROM tmp_normalized_partner_detail;



-- 證明驗證通過後留下的稽核存證
INSERT INTO `trade_raw.audit_ingestion_runs` (
  event_id, run_id, attempt_id,
  period, query_type, cmd_code, hs_version, revision,
  source_file, manifest_file, checksum,
  actual_row_count, actual_primary_value_sum,
  status, event_at
)
VALUES (
  GENERATE_UUID(), 'day06-partner-202301', 'attempt-1',
  '202301', 'partner_detail', '8542', 'H6', 1,
  's3://trade-analytics-prod-816079797958-ap-northeast-1-an/un_comtrade/v2/hs_version=H6/cmd_code=8542/period=202301/query_type=partner_detail/revision=1/data.ndjson',
  's3://trade-analytics-prod-816079797958-ap-northeast-1-an/un_comtrade/v2/hs_version=H6/cmd_code=8542/period=202301/query_type=partner_detail/revision=1/manifest.json',
  'e3b0c442...', -- 請替換為你明細實際的 Checksum
  67, 2799575181,
  'validated', CURRENT_TIMESTAMP()
);