CREATE TABLE IF NOT EXISTS `trade_raw.audit_ingestion_runs` (
  event_id STRING NOT NULL OPTIONS(description="稽核事件唯一 UUID"),
  run_id STRING NOT NULL OPTIONS(description="邏輯執行識別"),
  attempt_id STRING NOT NULL OPTIONS(description="單次嘗試識別，重試時遞增"),
  period STRING NOT NULL OPTIONS(description="期間 YYYYMM，例如 202301"),
  query_type STRING NOT NULL OPTIONS(description="查詢類型：partner_detail 或 world_total"),
  cmd_code STRING NOT NULL OPTIONS(description="商品代碼，例如 8542"),
  hs_version STRING NOT NULL OPTIONS(description="HS 分類版本，例如 H6"),
  revision INT64 NOT NULL OPTIONS(description="來源修訂版號"),
  source_file STRING NOT NULL OPTIONS(description="S3 原始 data.ndjson 完整路徑"),
  manifest_file STRING NOT NULL OPTIONS(description="S3 manifest.json 完整路徑"),
  checksum STRING NOT NULL OPTIONS(description="S3 原始 data.ndjson 的 SHA-256 雜湊"),
  load_job_id STRING OPTIONS(description="BigQuery Load Job ID 或 Transfer Run ID"),
  transfer_run_id STRING OPTIONS(description="Data Transfer Run ID (若使用 Transfer)"),
  merge_job_id STRING OPTIONS(description="BigQuery Raw MERGE Job ID"),
  expected_row_count INT64 OPTIONS(description="Manifest 預期筆數"),
  actual_row_count INT64 OPTIONS(description="實際驗證筆數"),
  expected_primary_value_sum STRING OPTIONS(description="Manifest 原始金額字串"),
  actual_primary_value_sum NUMERIC OPTIONS(description="實際無損加總金額"),
  status STRING NOT NULL OPTIONS(description="狀態：started, loaded, validated, success, already_loaded, stale_revision, conflict, failed"),
  error_stage STRING OPTIONS(description="出錯階段：s3_fetch, landing_load, manifest_gate, raw_merge 等"),
  error_message STRING OPTIONS(description="去除機密資訊後的錯誤摘要"),
  source_ingested_at TIMESTAMP OPTIONS(description="S3 manifest 上的擷取時間"),
  event_at TIMESTAMP NOT NULL OPTIONS(description="本筆稽核事件寫入時間")
)
PARTITION BY DATE(event_at)
CLUSTER BY period, query_type, status
OPTIONS(
  description = "追加式載入稽核表，保留載入、驗證、MERGE 與失敗歷史"
);
-- Existing manual audit remains append-only; new verified success events include these fields.
ALTER TABLE `trade_raw.audit_ingestion_runs`
ADD COLUMN IF NOT EXISTS contract_fingerprint STRING;
ALTER TABLE `trade_raw.audit_ingestion_runs`
ADD COLUMN IF NOT EXISTS snapshot_hash STRING;
