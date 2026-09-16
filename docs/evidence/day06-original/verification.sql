-- =============================================================================
-- 檢查資料正確性
-- =============================================================================
SELECT
  COUNT(*) AS total_rows,
  SUM(primary_value) AS total_amount,
  COUNT(DISTINCT partner_code) AS distinct_partners
FROM `trade_raw.un_comtrade_partner_detail`
WHERE period_start_date = DATE '2023-01-01';

-- =============================================================================
-- 情境 1 測試：同檔二次重跑測試
-- =============================================================================

-- 1. 建立 World 正規化暫存表
CREATE TEMP TABLE tmp_normalized_world_total AS
SELECT
  CAST(period AS STRING) AS period,
  PARSE_DATE('%Y%m%d', CONCAT(period, '01')) AS period_start_date,
  CAST(reporterCode AS STRING) AS reporter_code,
  CAST(partnerCode AS STRING) AS partner_code,
  CAST(cmdCode AS STRING) AS cmd_code,
  CAST(flowCode AS STRING) AS flow_code,
  CAST(classificationCode AS STRING) AS hs_version,
  SAFE_CAST(primaryValue AS NUMERIC) AS primary_value,
  SAFE_CAST(netWgt AS NUMERIC) AS net_weight,
  SAFE_CAST(qty AS NUMERIC) AS quantity,
  TIMESTAMP('2026-09-15T07:48:00Z') AS ingested_at,
  's3://trade-analytics-prod-816079797958-ap-northeast-1-an/un_comtrade/v2/hs_version=H6/cmd_code=8542/period=202301/query_type=world_total/revision=1/data.ndjson' AS source_file,
  'e3b0c442...' AS checksum, -- 填入 World 的 Checksum
  'day06-world-202301' AS run_id,
  1 AS revision
FROM `trade-analytics-508604.trade_landing.day05_world_total_202301_r1`;

-- 2. 交易內執行修訂清理、MERGE 與 Audit 紀錄
BEGIN TRANSACTION;

DELETE FROM `trade_raw.un_comtrade_world_total`
WHERE period_start_date = DATE '2023-01-01'
  AND cmd_code = '8542'
  AND hs_version = 'H6';

MERGE INTO `trade_raw.un_comtrade_world_total` T
USING (
  SELECT * FROM tmp_normalized_world_total
  WHERE period_start_date = DATE '2023-01-01'
) S
ON T.period_start_date = S.period_start_date
  AND T.partner_code = S.partner_code
  AND T.cmd_code = S.cmd_code
  AND T.hs_version = S.hs_version
  AND T.period_start_date = DATE '2023-01-01'
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

INSERT INTO `trade_raw.audit_ingestion_runs` (
  event_id, run_id, attempt_id,
  period, query_type, cmd_code, hs_version, revision,
  source_file, manifest_file, checksum,
  actual_row_count, actual_primary_value_sum,
  status, event_at
)
VALUES (
  GENERATE_UUID(), 'day06-world-202301', 'attempt-2',
  '202301', 'world_total', '8542', 'H6', 1,
  's3://trade-analytics-prod-816079797958-ap-northeast-1-an/un_comtrade/v2/hs_version=H6/cmd_code=8542/period=202301/query_type=world_total/revision=1/data.ndjson',
  's3://trade-analytics-prod-816079797958-ap-northeast-1-an/un_comtrade/v2/hs_version=H6/cmd_code=8542/period=202301/query_type=world_total/revision=1/manifest.json',
  'e3b0c442...', -- World Checksum
  1, 2799575181,
  'success', CURRENT_TIMESTAMP()
);

COMMIT TRANSACTION;



-- =============================================================================
-- 情境 2 測試：模擬來源為舊版 (r1)，既有已接受為新版 (r2)
-- =============================================================================
DECLARE current_accepted_revision INT64;
DECLARE incoming_revision INT64 DEFAULT 1; -- 模擬誤跑舊版 r1
DECLARE batch_status STRING;

-- 1. 查詢 audit 表中該批次目前已成功接受的最高版本
SET current_accepted_revision = (
  SELECT COALESCE(MAX(revision), 0)
  FROM `trade_raw.audit_ingestion_runs`
  WHERE period = '202301'
    AND query_type = 'partner_detail'
    AND cmd_code = '8542'
    AND hs_version = 'H6'
    AND status = 'success'
);

-- 2. 假設目前環境已推進到 r2 (刻意模擬)
SET current_accepted_revision = GREATEST(current_accepted_revision, 2);

-- 3. 版本閘門判斷 (Revision Gate)
IF incoming_revision < current_accepted_revision THEN
  SET batch_status = 'stale_revision';

  -- 記錄攔截事件，不執行 MERGE
  INSERT INTO `trade_raw.audit_ingestion_runs` (
    event_id, run_id, attempt_id,
    period, query_type, cmd_code, hs_version, revision,
    source_file, manifest_file, checksum,
    status, error_stage, error_message, event_at
  )
  VALUES (
    GENERATE_UUID(), 'day06-partner-202301-stale-test', 'attempt-stale',
    '202301', 'partner_detail', '8542', 'H6', incoming_revision,
    's3://.../revision=1/data.ndjson', 's3://.../revision=1/manifest.json', 'dummy-checksum',
    'stale_revision', 'revision_gate',
    FORMAT('Rejected stale revision %d; current accepted revision is %d', incoming_revision, current_accepted_revision),
    CURRENT_TIMESTAMP()
  );

  SELECT FORMAT('PASS: 成功攔截舊版本！判定為 %s，Raw 表維持原狀。', batch_status) AS test_result;
ELSE
  SELECT 'FAIL: 舊版未被攔截！' AS test_result;
END IF;


-- =============================================================================
-- 情境 3 測試：注入非法髒資料（重複 Grain 與負數金額）
-- =============================================================================
CREATE TEMP TABLE tmp_dirty_partner_detail AS
-- 1. 只選取體檢關心的 5 個核心欄位
SELECT
  CAST(period AS STRING) AS period,
  CAST(partnerCode AS STRING) AS partner_code,
  CAST(cmdCode AS STRING) AS cmd_code,
  CAST(classificationCode AS STRING) AS hs_version,
  SAFE_CAST(primaryValue AS NUMERIC) AS primary_value
FROM `trade-analytics-508604.trade_landing.day05_partner_detail_202301_r1`

UNION ALL

-- 2. 故意注入一筆重複的夥伴國家 (Grain 重複)，且金額為負數
SELECT
  '202301' AS period,
  '156' AS partner_code,    -- 既有存在的中國代碼，製造重複 Grain
  '8542' AS cmd_code,
  'H6' AS hs_version,
  -99999.0 AS primary_value; -- 負數金額

-- =============================================================================
-- 執行 Gate 體檢，並根據防呆指標做斷言判斷
-- =============================================================================
BEGIN
  DECLARE v_duplicate_grain INT64;
  DECLARE v_invalid_amounts INT64;

  -- 計算異常指標
  SET (v_duplicate_grain, v_invalid_amounts) = (
    SELECT AS STRUCT
      COUNT(*) - COUNT(DISTINCT CONCAT(period, '-', partner_code, '-', cmd_code, '-', hs_version)),
      COUNTIF(primary_value < 0 OR primary_value IS NULL)
    FROM tmp_dirty_partner_detail
  );

  -- 斷言檢查：若有任何問題直接阻擋
  IF v_duplicate_grain > 0 OR v_invalid_amounts > 0 THEN
    -- 記錄失敗事件到 Audit 表
    INSERT INTO `trade_raw.audit_ingestion_runs` (
      event_id, run_id, attempt_id,
      period, query_type, cmd_code, hs_version, revision,
      source_file, manifest_file, checksum,
      status, error_stage, error_message, event_at
    )
    VALUES (
      GENERATE_UUID(), 'day06-gate-failure-test', 'attempt-fail',
      '202301', 'partner_detail', '8542', 'H6', 1,
      's3://.../dirty/data.ndjson', 's3://.../dirty/manifest.json', 'dirty-checksum',
      'failed', 'manifest_gate',
      FORMAT('Gate failed: duplicate_grain=%d, invalid_amounts=%d', v_duplicate_grain, v_invalid_amounts),
      CURRENT_TIMESTAMP()
    );

    SELECT FORMAT('PASS: 成功在 Gate 攔截異常！發現重複粒度 %d 筆、非法金額 %d 筆，MERGE 未被觸發。', v_duplicate_grain, v_invalid_amounts) AS test_result;
  ELSE
    SELECT 'FAIL: 髒資料居然穿透了 Gate！' AS test_result;
  END IF;
END;



-- =============================================================================
-- 情境 4 測試：跨月份隔離驗證
-- =============================================================================

-- 步驟 1：故意在 2023-02-01 分區插入一筆測試隔離資料 (若已存在則不影響)
INSERT INTO `trade_raw.un_comtrade_partner_detail` (
  period, period_start_date, reporter_code, partner_code,
  cmd_code, flow_code, hs_version, primary_value,
  ingested_at, source_file, checksum, run_id, revision
)
VALUES (
  '202302', DATE '2023-02-01', '842', '999',
  '8542', 'M', 'H6', 888888,
  CURRENT_TIMESTAMP(), 's3://.../test-isolation.ndjson', 'dummy-hash', 'day06-isolation-test', 1
);

-- 步驟 2：模擬重跑 2023-01-01 的 DELETE 修訂清理邏輯
DELETE FROM `trade_raw.un_comtrade_partner_detail`
WHERE period_start_date = DATE '2023-01-01'
  AND cmd_code = '8542'
  AND hs_version = 'H6'
  AND partner_code NOT IN (
    -- 假設來源依然是正常的 67 個夥伴
    SELECT CAST(partnerCode AS STRING)
    FROM `trade-analytics-508604.trade_landing.day05_partner_detail_202301_r1`
  );

-- 步驟 3：驗證 2023-02-01 的資料是否依然完好無損
SELECT
  COUNT(*) AS feb_row_count,
  SUM(primary_value) AS feb_total_amount
FROM `trade_raw.un_comtrade_partner_detail`
WHERE period_start_date = DATE '2023-02-01';