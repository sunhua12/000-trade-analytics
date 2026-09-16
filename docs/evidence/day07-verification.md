# Day 7 驗證摘要

本紀錄依使用者實際執行的 Console／Terminal 回報及已保存的 dbt JSON 整理。助理本次僅讀取本機證據與保存文件，未重新執行雲端查詢。

## dbt 執行證據

時間採 JSON metadata 的 UTC；不以終端機時間推算學習工時。

| 證據 | 產生時間（UTC） | Invocation ID | 結果 |
|---|---|---|---|
| [dev-build-run-results.json](day07/dev-build-run-results.json) | 2026-09-16T14:25:18.288140Z | `603485ad-4881-4b61-9337-07857fce72bc` | success=3、pass=10 |
| [dev-final-build-run-results.json](day07/dev-final-build-run-results.json) | 2026-09-16T14:31:52.462993Z | `586cf080-5c8d-4e59-abc7-a527accaf066` | success=3、pass=10 |
| [fixture-baseline-run-results.json](day07/fixture-baseline-run-results.json) | 2026-09-16T14:20:20.753069Z | `b6928ded-ef03-4fc1-8953-9e8cc2d22112` | success=3、pass=10 |
| [fixture-duplicate-run-results.json](day07/fixture-duplicate-run-results.json) | 2026-09-16T14:22:36.282721Z | `fbd1d9b0-a419-44a9-8a3f-e0fb7239ab50` | fail=1 |
| [fixture-restored-run-results.json](day07/fixture-restored-run-results.json) | 2026-09-16T14:23:55.475514Z | `0105c375-ad8a-4f59-9ab1-bf0ba6bee9d8` | success=3、pass=10 |

## 人工查核結果

- 型別：兩張 staging 共 30 個欄位符合規格，重量／數量為 NUMERIC，revision 為 INT64。
- 202301：明細 67 筆，World 1 筆；金額各為 2,799,575,181。
- 月份維度：24 列，2023-01-01 至 2024-12-01，2024 年 2 月月底為 2024-02-29。
- 使用者提供的抽查附件共有 32 列：31 列重量 NULL，另有 partner 490，金額 630,972,428、重量 317867.708；來源追蹤欄位有值。
- 清理後 LEFT JOIN 保留 24 個月；除 202301 外，其餘 23 個月交易欄位皆為 NULL。
- 查詢保存於 [day07-verification.sql](day07-verification.sql)；自動保真與 grain 檢查沿用 ../../dbt/tests/ 的 SQL。

## 反例及資料清理

- 隔離 fixture：正常 build 通過，注入一筆重複明細後 grain 測試回傳一組違規（fail），恢復後全部通過。
- 真實 raw 曾有 202302／partner 999／金額 888888；source_file 為 s3://.../test-isolation.ndjson、checksum 為 dummy-hash、run_id 為 day06-isolation-test。
- 使用者依修正後 SQL，先在交易外建立永久備份表，再在交易內備份及精確刪除，並以 ASSERT 限制各影響一筆。備份目的表為 trade_raw_fixture.day06_isolation_backup。
- 清理後缺月查詢及最終 dev build 通過。備份表內容與清理 job ID 未由助理獨立查核，本文保留為使用者操作回報。
- 曾提供交易內永久 CREATE TABLE 的錯誤範例，BigQuery 拒絕執行；後續已修正為交易外建表。

## 限制與追溯

- 真實保真／非空驗收限於 202301；其他月份未回填，不將缺月補零。
- 反例僅實測重複 grain，未宣稱非法金額、日期等反例也已實測。
- docs generate 產生 catalog.json，同時出現 table_owner 欄位 RuntimeWarning。
- 人工 Console 查詢的 job IDs 尚未保存；run-results 內已有的 adapter_response job 資訊以原檔為準。
- Day 6 延後項目與 M1 狀態不因本次 dbt 驗收而視為完成。
