# Day 15：月度排程、有限補期與 CloudWatch／SNS 告警

| 項目 | 內容 |
|---|---|
| 對應計畫 | [20 天實作規格](trade-analytics-spec.md)的 Day 15；銜接 Day 16 的 M4 復原驗收 |
| 前置成果 | [Day 14](day-14-learning-plan.md)已建立本機 Airflow monthly DAG，並以已發布月份驗證安全重跑；目前 DAG 暫停，每次 run 只處理一個可用月份 |
| 預計投入 | 約 7～9 小時；雲端告警等待、訂閱確認與權限排障另記 |
| 核心目標 | 讓月度流程在服務運行時依排程處理最多 3 個候選月份，明確區分未就緒與失敗，並使真實 Lambda 失敗能經 CloudWatch／SNS 通知及追查 |
| 今日交付物 | 更新的 monthly DAG／選月與重試政策、結構化 Lambda 日誌、Terraform 告警資源、操作手冊、測試與真實告警證據 |
| 目前狀態 | DAG、Lambda 日誌與 Terraform 告警已實作部署，隔離 Errors／Duration 告警已驗證；SNS email 訂閱與實際收件仍待完成，詳見[執行紀錄](day15-run-record.md) |

MVP 範圍維持美國月度進口、`8542／H6`。本機 Airflow 只有在 Docker Compose 運行時才會排程；啟用前先確認 AWS／GCP 身分、SNS 收件端及雲端費用設定。Day 15 處理月度運轉與監控；獨立 backfill DAG、三個月 smoke test 與故障復原屬 Day 16。

實作後唯讀檢查發現三期窗口之前仍有 202501～202605 共 17 個未發布月份，因此正式 DAG 維持暫停。以下核取方塊保留為學習與完整驗收清單；實際完成與未完成項目以[執行紀錄](day15-run-record.md)為準。

## 1. 盤點排程現況與決定補期策略

**預計時間：35～45 分鐘。**

- [ ] 核對 `trade_monthly_pipeline` 的台北時間每月 1 日排程、`catchup=False`、`max_active_runs=1`、單 slot `trade_pipeline` Pool，以及目前暫停狀態。
- [ ] 檢查 `scripts/monthly_plan.py`：排程 run 最多查 3 個完整月份，按舊到新排序；`already_published`、`not_available` 與 `ready` 的判定及 `checked_at` 可追查。
- [ ] 改善目前「選到多個 ready，實際只執行第一個」的缺口：設計單次 run 內依序處理最多 3 個可用且未發布月份，逐月完成來源、raw、dbt、品質與發布；前一月失敗時停止後續寫入，保留尚未處理清單。不得讓多個月份同時重建共用 candidate Dataset。
- [ ] 對超出 3 個候選月的積欠或本機停機期間漏跑，提供可見的偵測與人工處置說明；不要因 `catchup=False` 或三期上限而靜默宣稱全部補齊。較早月份交由 Day 16 的參數化 backfill 處理。

排程邊界以 `data_interval_end` 推導上一個完整月份；例如 2026-10-01 執行時檢查 `202607`～`202609`。手動 run 必須明確指定 `conf.period`。每個月份使用可追查的 `run_id`；同一失敗嘗試的 task retry 沿用原 ID，新一次品質嘗試才建立新 ID。

## 2. 實作未就緒、限流與有限重試

**預計時間：75～95 分鐘。**

- [ ] `not_available` 記錄月份、兩種來源檢查結果與時間，略過該月份；下一次排程或人工 run 再檢查。HTTP／解析錯誤、S3 半套來源及認證錯誤不可寫成缺資料。
- [ ] 對暫時性 `429`、`5xx`、timeout 使用有限退避；確認既有 `ComtradeClient` 最多 4 次 HTTP 嘗試，Airflow task 最多額外重試 3 次，並核算單一來源最壞情況最多 16 次 HTTP 請求及可能的總等待時間。若 availability 與 ingest 都查 API，另計其請求量。
- [ ] 依錯誤分類決定 task 是否重試：資料契約、認證、checksum／`StorageConflictError`、品質 FAIL 不盲目重試；重試耗盡後保留原例外與任務失敗狀態。
- [ ] API 請求間隔由 client 控制；Airflow Pool 控制同時寫入與 pipeline 併發。核對 Lambda timeout、API 退避與 Airflow `execution_timeout` 的關係，避免外層逾時早於可預期的內層完成時間。
- [ ] 對已發布月份與同批次重跑驗證冪等：不新增 raw grain、不改寫無需更新的正式版本或 `published_at`；品質 FAIL 不進 publish。

## 3. 建立可查的 Lambda 與 Airflow 失敗事件

**預計時間：60～75 分鐘。**

- [ ] Lambda 每次 invocation 開始輸出單行 JSON `event=ingestion_started`，帶 `run_id`、`aws_request_id` 與可用的月份、類型、revision；未提供 `run_id` 時產生識別碼。
- [ ] 終止失敗只記一筆 JSON `event=ingestion_failed`，帶具體 `error_type`、互斥的 `error_category`、`period`、`query_type`、`revision` 及去除敏感資料的訊息，然後重新拋出，讓原生 Lambda Errors 指標計數。
- [ ] 先判斷 `ResponseTruncatedError`，再判斷其父類 `ComtradeResponseError`；`StorageConflictError` 獨立分類。其他錯誤仍由原生 Errors 告警涵蓋。
- [ ] Airflow 失敗紀錄包含 DAG、task、period、`run_id`、錯誤類別與 task log 位置；日誌與 XCom 不保存 credential、原始 NDJSON 或完整 manifest。
- [ ] 用固定例外與格式測試確認 JSON 可供 CloudWatch filter 解析、每次失敗只落入一個自訂分類，且例外仍向上拋出。

## 4. 以 Terraform 建立 Metric Filters、Alarms 與 SNS

**預計時間：90～120 分鐘。**

- [ ] 在現有 `infrastructure/aws/application` 擴充三個 JSON Metric Filters：`ComtradeResponseError`、`ResponseTruncatedError`、`StorageConflictError`；使用專案／環境專屬 namespace、無 `run_id` 維度，匹配事件時發布 1，適用時 default value 設 0。
- [ ] 建立 Lambda Errors 與 Duration 原生 Alarm，以及三個自訂錯誤 Alarm。Errors／自訂分類以 60 秒內 Sum ≥ 1 告警；Duration 以 Maximum > 150000 ms 告警，並與 Lambda 180 秒 timeout 共同檢查。
- [ ] 所有 Alarm 設 `treat_missing_data=notBreaching`，進入 ALARM 時發送 SNS。建立 topic、限制來源的 policy 與部署參數化 email subscription；個人收件地址不提交 Git，並完成訂閱確認。
- [ ] 執行 `terraform fmt -check`、`terraform validate`、檢視 plan 後才 apply；保存資源名稱、plan／apply 摘要及訂閱狀態。告警費用與停用／清理方式寫入操作手冊。

Duration 是 invocation 結束後才送出的耗時指標；硬逾時可能無法輸出自訂失敗事件，需從 Errors 及開始事件追查。SNS 的原生 Alarm 訊息不會自帶 `run_id`，操作手冊應從告警時間與函數找到 CloudWatch 日誌，再串接 Airflow、S3 與 BigQuery。持續處於 ALARM 的 Alarm 不保證每次失敗都重發通知。

## 5. 驗證排程、告警鏈與復原界限

**預計時間：90～120 分鐘，加上雲端等待。**

先在隔離 fixture 驗證月份與失敗分支，再於隔離測試函數／prefix 驗證 CloudWatch。故障注入不得修改正式來源資料。啟用正式 monthly DAG 前，先檢視選月、授權及未發布月份可能造成的寫入；保存啟用與執行結果。

| 情境 | 驗收證據 |
|---|---|
| 多個可用月份與三期邊界 | 單次 run 最多處理 3 個月，按舊到新串行；超出範圍的積欠可見並有處置方式 |
| 缺資料與 HTTP／S3 錯誤 | `not_available` 有檢查時間且可再查；錯誤呈現失敗，不冒充 skip |
| 暫時性錯誤與永久錯誤 | `429`／`5xx`／timeout 有有限退避與上限；認證、契約、checksum conflict、品質 FAIL 不盲目重試 |
| 三類自訂錯誤 | CloudWatch log 的 JSON 各命中正確 filter，互斥分類與 metric／Alarm 狀態可查 |
| 原生 Errors 與 Duration | 真實 Lambda 失敗觸發 Errors；隔離環境驗證超過 150 秒的耗時 Alarm，不以手動變更 Alarm state 代替 |
| SNS 與追查 | 至少一次真實 handler 失敗觸發 Alarm，收件端實際收到通知；由通知時間找到 `run_id`、request ID 與日誌 |
| 重跑及發布保護 | 同批次重跑沒有重複 raw grain；失敗月份不發布，既有正式版本不變 |

若真實 Comtrade 沒有空來源或特定錯誤，負面分支可用明確標記的隔離 fixture；不得把 fixture 寫成真實雲端結果。真實告警驗收至少保留 invocation ID、Alarm history、SNS 接收時間、對應 `run_id` 與查找步驟。

## 6. 交付紀錄與學習檢查

**預計時間：25～35 分鐘。**

| 交付物 | 最少內容 |
|---|---|
| Monthly DAG 與測試 | 多月順序、三期上限、未就緒狀態、有限重試、冪等與失敗停損 |
| Lambda 日誌與 Terraform | JSON 事件、三個 filters、五個 Alarms、SNS topic／subscription 與必要變數 |
| 操作手冊與執行紀錄 | 啟停、訂閱確認、告警定位、漏跑補期、告警費用與清理；區分 fixture 與真實雲端證據 |
| [學習日誌](learning-log.md) | 實際日期與本人投入時間、重試與補期決策、驗收結果及未解問題 |

完成後用自己的話回答：

1. 為什麼 `catchup=False` 加上三期上限，可能留下更早的漏跑月份？
2. `not_available`、HTTP 失敗、品質 FAIL 各如何影響後續月份與發布？
3. HTTP client 重試與 Airflow task 重試疊加後，最多可能送出多少次請求？
4. Pool、API 請求間隔、Lambda timeout 與 Duration Alarm 各控制什麼？
5. 為什麼 SNS 通知必須再透過 CloudWatch 日誌查 `run_id`？

- [ ] 月度 run 能順序處理最多 3 個候選月份，未就緒與積欠狀態可查。
- [ ] 重試上限、錯誤分類、失敗停損及安全重跑有測試證據。
- [ ] Terraform 告警資源與 email subscription 已確認；三類 filters、Errors、Duration 均有驗證。
- [ ] 至少一次真實 handler 失敗經 Alarm 送達 SNS，能以 `run_id` 找回日誌。
- [ ] README／操作手冊、執行紀錄與學習日誌完成，再更新[總規格](trade-analytics-spec.md)的 Day 15 勾選。

Day 16 再建立獨立 backfill DAG，完成三個月 smoke test 與故障中斷後的復原驗收。
