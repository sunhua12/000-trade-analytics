# Day 15：月度排程與告警執行紀錄

> 後續更新：2026-10-02 的 [Day 19 驗收](day19-run-record.md)已完成 email 訂閱確認、真實分類／Errors 告警實收、run ID 追查與修正重跑。本頁「未實收」為當時的歷史狀態。

| 項目 | 實測結果 |
|---|---|
| 日期 | 2026-09-30（Asia/Taipei） |
| Airflow | 本機 Airflow 3.3.2；`trade_monthly_pipeline` 保持暫停 |
| AWS | `ap-northeast-1`；Terraform 1.16.2、AWS provider 6.64.0 |
| Lambda 映像 | `sha256:93b903a9eab711734abd1a66615bd6cb34200e948e98945c59d5d977fa955eb6` |
| 雲端範圍 | 三個 Metric Filters、五個 Alarms、SNS topic／policy、Lambda 映像更新；Terraform apply 為新增 10、更新 1、刪除 0 |

## Airflow 與月份

更新後 DAG 無 import error，共 31 個 task；三個月份任務鏈由前一月的 `publish` 接到下一月的 `select_month`。`ingest_detail` 最多額外重試 3 次，`gate` 不重試。Pool 與 `max_active_tasks` 維持單一 writer。

本機測試為 `223 passed、3 skipped`（其中兩個真實 Preview API 整合測試需手動啟用，Streamlit UI 測試因本機虛擬環境未安裝 Streamlit 而略過）。本次修改檔案的 Ruff lint／format、`mypy src` 與 `git diff --check` 通過。全專案 `mypy .` 仍因舊腳本及未安裝 Airflow／Dashboard／BigQuery 可選依賴產生大量錯誤，不列為本日通過項目。

以原 `run_id=day11-202412-final-v1` 執行已發布月份安全重跑，DAG run `manual__2026-09-30T11:16:04.132874+00:00` 於 UTC 11:17:19 成功。唯讀 BigQuery 查核：`202412` 正式表仍為 67 筆，`published_run_id` 與 `published_at=2026-09-24 04:19:50.450+00` 均未改變。本次只證明單月重跑與擴充 DAG 相容；沒有真實多月首次發布。

使用 Airflow worker 對 2026-09-01 資料區間結束時間做唯讀選月：`202606`、`202607` 的明細／World 均可用，`202608` 的兩種來源均為 `not_available`；各月皆有 `checked_at`。三期窗口以前的 `older_unpublished` 有 `202501`～`202605` 共 17 個月份。這些月份未探測 API，須由後續 backfill 處理。為避免跳過歷史積欠後直接發布 2026 年中間月份，正式 DAG 維持暫停。

## Terraform 與告警

在隔離目錄以鎖定版本執行 Terraform `fmt -check`、`validate`，結果通過。套用前 plan 僅新增 10 個監控資源並更新 Lambda image URI；套用後以目前 digest 與本機變數重新 plan，結果 `No changes`。

三個 CloudWatch JSON filter pattern 均以 `aws logs test-metric-filter` 驗證：每個樣本只命中相同 `error_category` 的事件，`Other` 不命中。尚未觀察到正式 Lambda 自然發生的三類錯誤；此項是 filter 語法與隔離樣本驗證。

隔離 Lambda 另外指向不回傳 Comtrade JSON 的測試頁，真實 handler 產生 `error_category=ComtradeResponseError`、`error_type=ComtradeResponseError`，對應 `run_id=day15-isolated-category` 與 request ID `e2a81e19-ddf0-4bb4-9a98-236ede6ec25b`。此測試在解析階段失敗，沒有進入 S3 寫入。

建立隔離 Lambda `trade-analytics-ingestion-monitor-test`，使用同一映像與獨立函數名稱。送入無效 action 後，真實 handler 回傳 `FunctionError=Unhandled`；CloudWatch log 具有無前綴、可解析的 `ingestion_started` 與 `ingestion_failed` JSON，兩者均帶 `run_id=day15-isolated-monitor`、request ID `a6317271-70fa-434d-b50a-7d8cd76b8215`。錯誤分類為 `Other`，符合驗證錯誤不落入三個自訂 filter 的預期。

隔離 Errors metric 在 2026-09-30 15:47 UTC 記錄 Sum 1.0；`trade-analytics-ingestion-IsolatedErrors` 於台北時間 23:49:05 進入 ALARM，Alarm history 於 23:49:06 顯示成功執行 SNS topic 動作。這證明真實 handler 失敗、原生 Errors、Alarm 與 SNS topic 發布鏈；**尚未證明 email 收件者實際收到通知**。

Duration 門檻另以隔離 151 秒 Lambda fixture 驗證。真實 Duration 指標 Maximum 為 `151001.93 ms`；`trade-analytics-ingestion-IsolatedDuration` 於 2026-10-01 00:01:30（台北時間）進入 ALARM，history 顯示 00:01:30 成功執行 SNS topic 動作。兩個隔離 Alarm、兩個隔離 Lambda 與其 CloudWatch log group 均已刪除，正式五個 Alarm 保留。

SNS email endpoint 尚未提供，topic 目前沒有 subscription；即使 Alarm history 顯示 SNS 動作成功，也沒有收件者可收到通知。以無效範例地址執行的只讀 Terraform plan 確認 subscription 分支會新增 1 項資源、沒有其他變更；尚未對範例地址 apply。在實際訂閱並確認前，不得把 Day 15 的收件驗收標為通過。

## 待完成與界限

- 取得 SNS 收件地址後，以敏感 Terraform 變數建立 email subscription，請收件者確認，再用隔離真實失敗驗證實際收件時間。
- 本機 `/private/tmp` 的測試 fixture 與 Terraform 驗證副本不屬於 Git 交付物；雲端隔離資源已清理。
- 新月份首次發布及多個可用月份的真實串行發布尚未執行；目前有 17 個較早未發布月份，需先處理歷史積欠。Day 16 的獨立 backfill DAG 負責三個月 smoke test 與復原驗收。
