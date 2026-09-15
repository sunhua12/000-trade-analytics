-- Run in asia-northeast1; creates empty raw tables only.
CREATE TABLE IF NOT EXISTS
  `trade-analytics-508604.trade_raw.un_comtrade_partner_detail` (
    period STRING,
    reporter_code STRING,
    partner_code STRING,
    flow_code STRING,
    cmd_code STRING,
    hs_version STRING,
    period_start_date DATE,
    primary_value NUMERIC,
    net_weight NUMERIC,
    quantity NUMERIC,
    ingested_at TIMESTAMP,
    source_file STRING,
    checksum STRING,
    run_id STRING,
    revision INT64
  )
PARTITION BY DATE_TRUNC(period_start_date, MONTH)
CLUSTER BY partner_code, cmd_code
OPTIONS (require_partition_filter = TRUE, partition_expiration_days = NULL);

CREATE TABLE IF NOT EXISTS
  `trade-analytics-508604.trade_raw.un_comtrade_world_total` (
    period STRING,
    reporter_code STRING,
    partner_code STRING,
    flow_code STRING,
    cmd_code STRING,
    hs_version STRING,
    period_start_date DATE,
    primary_value NUMERIC,
    net_weight NUMERIC,
    quantity NUMERIC,
    ingested_at TIMESTAMP,
    source_file STRING,
    checksum STRING,
    run_id STRING,
    revision INT64
  )
PARTITION BY DATE_TRUNC(period_start_date, MONTH)
CLUSTER BY partner_code, cmd_code
OPTIONS (require_partition_filter = TRUE, partition_expiration_days = NULL);

-- Also fix existing tables: CREATE IF NOT EXISTS does not update their options.
ALTER TABLE `trade-analytics-508604.trade_raw.un_comtrade_partner_detail`
SET OPTIONS (partition_expiration_days = NULL);

ALTER TABLE `trade-analytics-508604.trade_raw.un_comtrade_world_total`
SET OPTIONS (partition_expiration_days = NULL);
