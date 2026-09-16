# Day 7 dbt 驗收紀錄

## 環境

- Python：3.14.6
- dbt Core：1.12.5
- dbt BigQuery adapter：1.12.1
- GCP Project：trade-analytics-508604
- Location：asia-northeast1
- 真實來源：trade_raw
- 開發輸出：trade_analytics_dev
- 隔離來源：trade_raw_fixture
- 隔離輸出：trade_analytics_fixture

## 模型與測試

- 兩個 staging views 與 dim_months table 建立成功。
- 最終 dev build：PASS=13、WARN=0、ERROR=0。
- 包含 3 個模型與 10 個資料測試。
- 兩張 staging 共 30 個欄位的 metadata 型別符合預期。
- 202301 raw 與 staging 的投影欄位及筆數一致。
- 模型與欄位說明已補齊，parse 通過。
- docs generate 已產生 catalog.json。
- 文件產生時出現 table_owner 欄位警告，未阻止 catalog 產生。

## 真實資料結果

- 202301 明細：67 筆。
- 202301 World：1 筆。
- 明細加總與 World 金額均為 2,799,575,181。
- 特殊夥伴代碼 490 與 NULL 重量均保留。
- dim_months 共 24 列，涵蓋 202301 至 202412。
- 2024 年 2 月月底為 2024-02-29。
- 其餘 23 個月份缺交易資料，LEFT JOIN 結果保留 NULL。

## 隔離反例

- 正常 fixture build：PASS=13。
- 加入一筆重複明細後，grain 測試：FAIL 1。
- 恢復 fixture 後，build：PASS=13。
- 本次反例驗證範圍為重複 grain。

## 發現與處理

- 真實 raw 曾存在 202302 的隔離測試資料。
- run_id：day06-isolation-test。
- 已備份至 trade_raw_fixture.day06_isolation_backup 後精確移除。
- 清理後重新驗證缺月結果與 dev build，全部符合預期。

## 限制

- 真實來源驗收範圍為 202301。
- 其餘 23 個月份尚未回填。
- 日曆完整不代表交易資料完整。


## 證據索引與紀錄來源

本紀錄依使用者實際執行回報與已保存的 dbt JSON 整理；本次文件保存未重新執行雲端查詢。實際學習工時未提供。

- [驗證 SQL](evidence/day07-verification.sql)：型別、月份邊界、缺月及特殊代碼／NULL 抽查。
- [驗證摘要](evidence/day07-verification.md)：各次 invocation、UTC 時間、結果與限制。
- [最終 build 結果](evidence/day07/dev-final-build-run-results.json)。
- [最終模型 manifest](evidence/day07/dev-final-build-manifest.json)。
- [正常 fixture](evidence/day07/fixture-baseline-run-results.json)。
- [重複反例](evidence/day07/fixture-duplicate-run-results.json)。
- [恢復 fixture](evidence/day07/fixture-restored-run-results.json)。
- [清理前 dev build](evidence/day07/dev-build-run-results.json) 與 [manifest](evidence/day07/dev-build-manifest.json) 保留歷史證據。

人工查詢及清理的 Console job IDs 尚未保存；備份表內容未由助理獨立查核。Day 6 的延後項目與 M1 狀態沿用原紀錄，不因 Day 7 測試通過而視為完成。
