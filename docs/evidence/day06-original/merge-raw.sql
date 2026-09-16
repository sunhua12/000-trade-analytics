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

  -- 2. 高精度無損數值轉換
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
-- 步驟 2：交易內執行修訂清理、Raw MERGE 與 Audit 紀錄 (Step 4)
-- =============================================================================
BEGIN TRANSACTION;

-- 2.1 範圍限定刪除（處理官方新版修訂刪除的資料列，明確命中分區過濾）
DELETE FROM `trade_raw.un_comtrade_partner_detail`
WHERE period_start_date = DATE '2023-01-01'
  AND cmd_code = '8542'
  AND hs_version = 'H6'
  AND partner_code NOT IN (
    SELECT partner_code
    FROM tmp_normalized_partner_detail
    WHERE period_start_date = DATE '2023-01-01'
  );

-- 2.2 執行標準的 UPSERT MERGE
MERGE INTO `trade_raw.un_comtrade_partner_detail` T
USING (
  SELECT * FROM tmp_normalized_partner_detail
  WHERE period_start_date = DATE '2023-01-01'
) S
ON T.period_start_date = S.period_start_date
  AND T.partner_code = S.partner_code
  AND T.cmd_code = S.cmd_code
  AND T.hs_version = S.hs_version
  AND T.period_start_date = DATE '2023-01-01'

-- 分支 1：已存在則更新數值與血緣
WHEN MATCHED THEN
  UPDATE SET
    reporter_code = S.reporter_code,
    flow_code     = S.flow_code,
    primary_value = S.primary_value,
    net_weight    = S.net_weight,
    quantity      = S.quantity,
    ingested_at   = S.ingested_at,
    source_file   = S.source_file,
    checksum      = S.checksum,
    run_id        = S.run_id,
    revision      = S.revision

-- 分支 2：不存在則插入新列
WHEN NOT MATCHED THEN
  INSERT (
    period, period_start_date, reporter_code, partner_code,
    cmd_code, flow_code, hs_version,
    primary_value, net_weight, quantity,
    ingested_at, source_file, checksum, run_id, revision
  )
  VALUES (
    S.period, S.period_start_date, S.reporter_code, S.partner_code,
    S.cmd_code, S.flow_code, S.hs_version,
    S.primary_value, S.net_weight, S.quantity,
    S.ingested_at, S.source_file, S.checksum, S.run_id, S.revision
  );

-- 2.3 交易內寫入 success 稽核事件
INSERT INTO `trade_raw.audit_ingestion_runs` (
  event_id, run_id, attempt_id,
  period, query_type, cmd_code, hs_version, revision,
  source_file, manifest_file, checksum,
  actual_row_count, actual_primary_value_sum,
  status, event_at
)
VALUES (
  GENERATE_UUID(), 'day06-partner-202301', 'attempt-2',
  '202301', 'partner_detail', '8542', 'H6', 1,
  's3://trade-analytics-prod-816079797958-ap-northeast-1-an/un_comtrade/v2/hs_version=H6/cmd_code=8542/period=202301/query_type=partner_detail/revision=1/data.ndjson',
  's3://trade-analytics-prod-816079797958-ap-northeast-1-an/un_comtrade/v2/hs_version=H6/cmd_code=8542/period=202301/query_type=partner_detail/revision=1/manifest.json',
  'e3b0c442...', -- 請替換為真實 Checksum
  67, 2799575181,
  'success', CURRENT_TIMESTAMP()
);

-- 2.4 正式提交
COMMIT TRANSACTION;