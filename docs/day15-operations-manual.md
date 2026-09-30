# Day 15：月度排程與告警操作手冊

## 啟動與補期

1. 依 [Airflow 指南](day14-airflow-manual.md)啟動 Compose，確認 DAG 無 import error、worker 的 AWS／GCP 身分可用、`trade_pipeline` Pool 為 1 slot。
2. 排程使用台北時間每月 1 日、`catchup=False`。在 UI 解除暫停前先檢視預期月份與雲端寫入範圍；本機關閉時不會執行排程。
3. 排程 run 最多檢查最近 3 個完整月份。`checks` 逐月列出 `already_published`、`not_available` 或 `ready` 與檢查時間；`sources` 分別記錄明細／World 的可用性。選出的月份按舊到新串行處理，任一月失敗會阻止後續月份寫入。
4. `older_unpublished` 列出三期窗口之前尚未發布的月份；這些月份不自動探測來源，應人工核對後交由獨立 backfill 流程處理。`not_available` 會在下一次排程或指定月份的手動 run 再查。
5. 手動 run 以 `conf.period` 指定單月；已發布月份如需安全重跑，同時指定原 `replay_run_id`。同一次 task retry 沿用原 `run_id`。不要以新的 run ID 強制覆蓋已發布版本。

## 重試與失敗分類

`ComtradeClient` 對 `429`、`5xx` 與 transport timeout 最多嘗試 4 次，遵守 `Retry-After` 或有限指數退避。Airflow 的 availability、ingest 與 load task 對標記為暫時性的錯誤最多額外重試 3 次；單一來源的 HTTP 層最壞情況為 16 次請求。availability 與 ingest 若都需查 API，請分別計入。來源檢查與新擷取前另設 1 秒間隔；Pool 控制任務併發，不能取代每秒請求間隔。

認證、資料契約、來源 checksum 衝突及品質 FAIL 直接失敗。每個失敗步驟的 stderr 輸出 `pipeline_step_failed` JSON，包含錯誤類型與 `retryable`；Airflow 的 task log 可用 DAG run、task、period、`run_id` 串接。失敗日誌不輸出 credential 或原始資料。

## Terraform 與 SNS

應用層 Terraform 位於 `infrastructure/aws/application/`，版本固定為 1.16.2／AWS provider 6.64.0。先以現有短期 AWS 身分與受控 remote state 完成 `init`、`fmt -check`、`validate`、`plan`，審閱 plan 後再 `apply`。收件地址用敏感變數 `alarm_email_endpoint` 輸入，不提交 `.tfvars`、state、plan 或電子郵件地址。SNS 建立 email subscription 後，收件者須點擊 AWS 寄出的確認信。

三個 JSON Metric Filters 只匹配 `event=ingestion_failed` 且 `error_category` 分別為 `ComtradeResponseError`、`ResponseTruncatedError`、`StorageConflictError` 的單行 JSON。每類各有 60 秒 Sum ≥ 1 Alarm；另有 Lambda Errors 的 Sum ≥ 1 與 Duration 的 Maximum > 150000 ms Alarm。五個 Alarm 均在 ALARM 時通知 SNS，`treat_missing_data=notBreaching`。無資料不代表成功，也不偵測排程完全沒有啟動。

Lambda 開始時輸出 `ingestion_started`，失敗時輸出一筆 `ingestion_failed` 後重新拋出。CloudWatch 原生告警通知不含 `run_id`：從通知的函數與時間查 CloudWatch log，取得 `aws_request_id`／`run_id`，再查 Airflow task、S3 manifest 及 BigQuery audit。硬逾時可能沒有失敗 JSON，須從 Errors 指標與開始事件查。Duration 是 invocation 結束後的事後告警；同一失敗可能同時觸發原生與分類 Alarm，Alarm 持續 ALARM 時不保證每次失敗都重發。

告警驗證限隔離測試函數及 prefix，不在正式來源注入錯誤。測試後保存 invocation、Alarm history、SNS 實收時間、`run_id` 與復原結果。監控停止時先停用相關 Alarm／subscription，再以 Terraform 計畫確認資源清理範圍；Metric Filters、Alarms 與 SNS 可能產生費用。
