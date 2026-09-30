# Day 14：Airflow monthly DAG 執行紀錄

| 項目 | 實測結果 |
|---|---|
| 日期 | 2026-09-30（Asia/Taipei） |
| 執行環境 | 本機 Docker Compose；Airflow 3.3.2、Python 3.11、dbt Core 1.12.5、dbt BigQuery 1.12.1 |
| 身分 | worker 使用本機 AWS `hua` profile 與 GCP ADC；`dbt debug --target day11` 連線成功 |
| DAG | `trade_monthly_pipeline`；目前保持暫停 |
| 範圍 | 美國進口、`8542`、`H6`；以已發布的 `202412` 驗證完整安全重跑 |

## 排程與結構

Airflow DAG import error 清單為空。DAG 有 11 個 task：`check_availability`、`select_month`、兩個 ingest、兩個 load、`attest`、`build`、`audit`、`gate`、`publish`。實際處理 task 共用 1 slot 的 `trade_pipeline` Pool；`max_active_runs=1`、`max_active_tasks=1`。`publish` 依賴 `gate` 成功。

排程採 `CronDataIntervalTimetable`，台北時間每月 1 日執行。Airflow 顯示下一個資料區間為 2026-09-01 至 2026-10-01（Asia/Taipei），由 2026-10-01 觸發。單元測試驗證 2026-10-01 的候選為 `202607`、`202608`、`202609`；2027-01-01 為 `202610`、`202611`、`202612`。每次最多檢查 3 個完整月份，一次 DAG run 只處理最早的一個可用月份。

## 真實雲端重跑

1. 對 `202412` 進行唯讀可用性檢查：BigQuery 正式表已存在 run ID `day11-202412-final-v1`；兩種來源的 S3 data／manifest 配對均存在，revision 均為 1。
2. `ingest --period 202412 --kind partner_detail --run-id day11-202412-final-v1` 回報 `already_exists`，直接核對 S3 來源，不重複呼叫 Lambda。
3. 未提供 `replay_run_id` 的 `airflow dags test`：DAG run `manual__2026-09-30T09:52:21.998921+00:00` 成功；`select_month` 因 `already_published` 略過，下游沒有執行。
4. 提供原 run ID 的完整重跑：DAG run `manual__2026-09-30T09:53:37.039700+00:00`，UTC 09:53:36 開始、09:55:00 結束，11 個 task 均為 success。兩類 ingest 使用既有來源，raw 載入維持冪等；dbt build／test 88 項成功，品質 audit 為 PASS，gate 成功，publish 回報 `already_published`。
5. 重跑後唯讀查核 BigQuery 正式表：`202412` 仍有 67 筆，`published_run_id` 仍為 `day11-202412-final-v1`，`published_at` 仍為 `2026-09-24 04:19:50.450+00`。最新 publication attempt 於 `2026-09-30 09:54:54.560+00` 記為 `already_published`。

可從 Airflow UI 的 Grid 與各 task log 追查該 DAG run；dbt／BigQuery job 明細保留在 `build` task log 和 BigQuery job history。此紀錄只列已核對的 run／結果，不以推測值代填 job ID。

## 隔離測試與界限

本機測試涵蓋月份邊界、三期上限、已發布與指定 replay ID、空來源 `not_available`、S3 配對不完整、來源身分不符、raw 載入錯誤與品質 FAIL gate。這些負面分支屬隔離測試，不是本次真實雲端故障。

Day 14 驗證的是已發布月份的完整安全重跑；沒有對新月份首次發布，也沒有在真實 Comtrade 空來源情境驗證 `not_available`。目前 DAG 暫停。Day 15 應補上未就緒來源的再次檢查、積欠月份逐次處理、重試與告警；Day 16 再驗證獨立 backfill 與故障復原。
