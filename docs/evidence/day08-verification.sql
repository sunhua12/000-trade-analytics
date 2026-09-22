-- BigQuery Standard SQL. Read-only checks for the configured dev Dataset.
-- Truth source uses the staging date window [2023-01-01, 2025-01-01).
SELECT 'staging' AS layer, COUNT(*) AS row_count, SUM(primary_value) AS amount,
       COUNTIF(net_weight IS NULL) AS null_weights
FROM `trade-analytics-508604.trade_analytics_dev.stg_un_comtrade__partner_trades`
UNION ALL
SELECT 'fact', COUNT(*), SUM(primary_value), COUNTIF(net_weight IS NULL)
FROM `trade-analytics-508604.trade_analytics_dev.fct_monthly_semiconductor_imports`;

-- Must return zero rows.
SELECT period_start_date, partner_code, cmd_code, hs_version, COUNT(*) AS row_count
FROM `trade-analytics-508604.trade_analytics_dev.fct_monthly_semiconductor_imports`
GROUP BY 1, 2, 3, 4 HAVING COUNT(*) != 1;

-- All 15 source columns, including every lineage field, compared both ways.
WITH s AS (
    SELECT period, period_start_date, reporter_code, partner_code, flow_code,
           cmd_code, hs_version, primary_value, net_weight, quantity,
           ingested_at, source_file, checksum, run_id, revision
    FROM `trade-analytics-508604.trade_analytics_dev.stg_un_comtrade__partner_trades`
), f AS (
    SELECT period, period_start_date, reporter_code, partner_code, flow_code,
           cmd_code, hs_version, primary_value, net_weight, quantity,
           ingested_at, source_file, checksum, run_id, revision
    FROM `trade-analytics-508604.trade_analytics_dev.fct_monthly_semiconductor_imports`
), missing AS (SELECT * FROM s EXCEPT DISTINCT SELECT * FROM f),
extra AS (SELECT * FROM f EXCEPT DISTINCT SELECT * FROM s)
SELECT 'missing_or_changed' AS issue, COUNT(*) AS failure_count FROM missing
UNION ALL SELECT 'extra_or_changed', COUNT(*) FROM extra;

SELECT * FROM `trade-analytics-508604.trade_analytics_dev.audit_partner_mapping_issues`
ORDER BY partner_code, issue_type;

SELECT partner_code, primary_value, net_weight, partner_type, classification_status,
       map_iso3, reconciliation_role, country_mapping_found,
       hs_mapping_found, month_mapping_found
FROM `trade-analytics-508604.trade_analytics_dev.fct_monthly_semiconductor_imports`
WHERE partner_code IN ('0', '490') OR NOT country_mapping_found
    OR NOT hs_mapping_found OR NOT month_mapping_found;

SELECT table_name, column_name, data_type
FROM `trade-analytics-508604.trade_analytics_dev.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name IN ('fct_monthly_semiconductor_imports', 'country_reference',
                     'hs_code_reference', 'dim_countries', 'dim_hs_codes')
ORDER BY table_name, ordinal_position;

SELECT COUNT(*) AS row_count, SUM(primary_value) AS amount
FROM `trade-analytics-508604.trade_raw.un_comtrade_world_total`
WHERE period_start_date >= DATE '2023-01-01' AND period_start_date < DATE '2025-01-01';
