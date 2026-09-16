-- =============================================================================
-- infrastructure/gcp/merge-raw.sql
-- 目的：帶入真實 Manifest 參數、Gate 自動阻擋異常、交易內範圍 MERGE 與 Audit 存證
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. 宣告真實來源 Metadata 變數 (依據真實 manifest.json)
-- -----------------------------------------------------------------------------
DECLARE v_period STRING DEFAULT '202301';
DECLARE v_cmd_code STRING DEFAULT '8542';
DECLARE v_hs_version STRING DEFAULT 'H6';
DECLARE v_revision INT64 DEFAULT 1;
DECLARE v_query_type STRING DEFAULT 'partner_detail';

-- 真實 S3 路徑與數位指紋
DECLARE v_source_file STRING DEFAULT 's3://trade-analytics-prod-816079797958-ap-northeast-1-an/un_comtrade/v2/hs_version=H6/cmd_code=8542/period=202301/query_type=partner_detail/revision=1/data.ndjson';
DECLARE v_manifest_file STRING DEFAULT 's3://trade-analytics-prod-816079797958-ap-northeast-1-an/un_comtrade/v2/hs_version=H6/cmd_code=8542/period=202301/query_type=partner_detail/revision=1/manifest.json';
DECLARE v_checksum STRING DEFAULT 'sha256:90002d6c1374e9e48fe946e22613a9c0629766e87a1674eab11a7404a461abcf';
DECLARE v_ingested_at TIMESTAMP DEFAULT TIMESTAMP('2026-09-12T12:20:07.713138Z');

-- Manifest 預期驗證指標
DECLARE v_expected_row_count INT64 DEFAULT 67;
DECLARE v_expected_sum STRING DEFAULT '2799575181';
DECLARE v_run_id STRING DEFAULT 'day06-partner-202301';
DECLARE v_attempt_id STRING DEFAULT 'attempt-prod-1';

-- -----------------------------------------------------------------------------
-- 2. 建立正規化暫存表 (Temp Table)
-- -----------------------------------------------------------------------------
CREATE TEMP TABLE tmp_normalized_partner_detail AS
SELECT
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

  -- 高精度無損數值轉換
  SAFE_CAST(primaryValue AS NUMERIC) AS primary_value,
  SAFE_CAST(netWgt AS NUMERIC) AS net_weight,
  SAFE_CAST(qty AS NUMERIC) AS quantity,

  -- 綁定真實變數
  v_ingested_at AS ingested_at,
  v_source_file AS source_file,
  v_checksum AS checksum,
  v_run_id AS run_id,
  v_revision AS revision
FROM `trade-analytics-508604.trade_landing.day05_partner_detail_202301_r1`;

-- -----------------------------------------------------------------------------
-- 3. Manifest Gate 自動阻擋邏輯（驗證未過即拋錯中斷，阻止進入 MERGE）
-- -----------------------------------------------------------------------------
BEGIN
  DECLARE v_actual_rows INT64;
  DECLARE v_actual_sum NUMERIC;
  DECLARE v_violations INT64;

  -- 彙整計算實際指標與違規筆數
  SET (v_actual_rows, v_actual_sum, v_violations) = (
    SELECT AS STRUCT
      COUNT(*),
      SUM(primary_value),
      -- 檢查違規項（任何項大於 0 都算違規）
      COUNTIF(period_start_date IS NULL OR partner_code IS NULL OR cmd_code IS NULL OR hs_version IS NULL) +
      (COUNT(*) - COUNT(DISTINCT CONCAT(period_start_date, '-', partner_code, '-', cmd_code, '-', hs_version))) +
      COUNTIF(
        period != v_period OR reporter_code IS NULL OR reporter_code != '842' OR
        flow_code != 'M' OR cmd_code != v_cmd_code OR hs_version != v_hs_version OR
        partner2_code != '0' OR customs_code != 'C00' OR mot_code != '0'
      ) +
      COUNTIF(partner_code = '0' OR primary_value < 0 OR primary_value IS NULL)
    FROM tmp_normalized_partner_detail
  );

  -- 自動阻擋判斷：若筆數不合、金額不合、或有任何合約違規
  IF v_actual_rows != v_expected_row_count
     OR v_actual_sum != CAST(v_expected_sum AS NUMERIC)
     OR v_violations > 0 THEN

    -- 1. 寫入 failed 稽核紀錄
    INSERT INTO `trade_raw.audit_ingestion_runs` (
      event_id, run_id, attempt_id,
      period, query_type, cmd_code, hs_version, revision,
      source_file, manifest_file, checksum,
      expected_row_count, actual_row_count,
      expected_primary_value_sum, actual_primary_value_sum,
      status, error_stage, error_message, source_ingested_at, event_at
    )
    VALUES (
      GENERATE_UUID(), v_run_id, v_attempt_id,
      v_period, v_query_type, v_cmd_code, v_hs_version, v_revision,
      v_source_file, v_manifest_file, v_checksum,
      v_expected_row_count, v_actual_rows,
      v_expected_sum, v_actual_sum,
      'failed', 'manifest_gate',
      FORMAT('Gate check failed! rows: expected %d vs actual %d; sum: expected %s vs actual %s; violations: %d',
             v_expected_row_count, v_actual_rows, v_expected_sum, CAST(v_actual_sum AS STRING), v_violations),
      v_ingested_at, CURRENT_TIMESTAMP()
    );

    -- 2. 拋出例外，強制中斷整個 Script，阻止進入下方的 MERGE！
    RAISE USING MESSAGE = FORMAT('Manifest Gate Blocked: Expected %d rows and %s sum, but got %d rows and %s sum with %d violations.',
                                v_expected_row_count, v_expected_sum, v_actual_rows, CAST(v_actual_sum AS STRING), v_violations);
  END IF;
END;

-- -----------------------------------------------------------------------------
-- 4. 交易核對與失敗復原 (Transaction with Post-check and Rollback Handling)
-- -----------------------------------------------------------------------------
BEGIN
  -- 關鍵修正：將所有變數宣告置於 BEGIN 區塊最前端
  DECLARE v_post_rows INT64;
  DECLARE v_post_sum NUMERIC;
  DECLARE v_post_duplicate_grain INT64;

  -- 4.1 開啟原子性交易
  BEGIN TRANSACTION;

  -- 執行修訂刪除（帶分區過濾條件）
  DELETE FROM `trade_raw.un_comtrade_partner_detail`
  WHERE period_start_date = DATE '2023-01-01'
    AND cmd_code = v_cmd_code
    AND hs_version = v_hs_version
    AND partner_code NOT IN (
      SELECT partner_code
      FROM tmp_normalized_partner_detail
      WHERE period_start_date = DATE '2023-01-01'
    );

  -- 執行 UPSERT MERGE
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

  -- 4.2 交易內核對驗收 (Post-MERGE Verification)
  SET (v_post_rows, v_post_sum, v_post_duplicate_grain) = (
    SELECT AS STRUCT
      COUNT(*),
      SUM(primary_value),
      COUNT(*) - COUNT(DISTINCT partner_code)
    FROM `trade_raw.un_comtrade_partner_detail`
    WHERE period_start_date = DATE '2023-01-01'
      AND cmd_code = v_cmd_code
      AND hs_version = v_hs_version
  );

  -- 若核對失敗（筆數不對、金額對不上、或出現重複 Grain），主動報錯觸發回滾
  IF v_post_rows != v_expected_row_count
     OR v_post_sum != CAST(v_expected_sum AS NUMERIC)
     OR v_post_duplicate_grain > 0 THEN
    RAISE USING MESSAGE = FORMAT(
      'Post-MERGE check failed: expected %d rows and %s sum, but Raw has %d rows and %s sum (duplicate grain: %d)',
      v_expected_row_count, v_expected_sum, v_post_rows, CAST(v_post_sum AS STRING), v_post_duplicate_grain
    );
  END IF;

  -- 4.3 核對成功：寫入 success 稽核並正式提交
  INSERT INTO `trade_raw.audit_ingestion_runs` (
    event_id, run_id, attempt_id,
    period, query_type, cmd_code, hs_version, revision,
    source_file, manifest_file, checksum,
    expected_row_count, actual_row_count,
    expected_primary_value_sum, actual_primary_value_sum,
    status, source_ingested_at, event_at
  )
  VALUES (
    GENERATE_UUID(), v_run_id, v_attempt_id,
    v_period, v_query_type, v_cmd_code, v_hs_version, v_revision,
    v_source_file, v_manifest_file, v_checksum,
    v_expected_row_count, v_post_rows,
    v_expected_sum, v_post_sum,
    'success', v_ingested_at, CURRENT_TIMESTAMP()
  );

  COMMIT TRANSACTION;

-- 4.4 失敗復原 (Rollback & Failure Logging)
EXCEPTION WHEN ERROR THEN
  ROLLBACK TRANSACTION;

  INSERT INTO `trade_raw.audit_ingestion_runs` (
    event_id, run_id, attempt_id,
    period, query_type, cmd_code, hs_version, revision,
    source_file, manifest_file, checksum,
    status, error_stage, error_message, source_ingested_at, event_at
  )
  VALUES (
    GENERATE_UUID(), v_run_id, v_attempt_id,
    v_period, v_query_type, v_cmd_code, v_hs_version, v_revision,
    v_source_file, v_manifest_file, v_checksum,
    'failed', 'merge_transaction', @@error.message, v_ingested_at, CURRENT_TIMESTAMP()
  );

  RAISE USING MESSAGE = @@error.message;
END;