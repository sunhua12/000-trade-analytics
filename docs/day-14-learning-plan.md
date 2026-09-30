# Day 14：Airflow monthly DAG、工作邊界與 logical date

| 項目 | 內容 |
|---|---|
| 對應計畫 | [20 天實作規格](trade-analytics-spec.md)的 Day 14；為 Day 16 的 M4 復原驗收建立 monthly DAG 基礎 |
| 前置成果 | [Day 10](day10-quality-publish-record.md)已建立 candidate／audit／gate／publish；[Day 11](day11-backfill-record.md)已驗證單月來源、raw 載入及 24 個月發布；Day 13 已完成本機 Dashboard |
| 預計投入 | 約 5～7 小時；首次建置容器、雲端執行及權限排障另記 |
| 核心目標 | 以本機 Airflow 編排一個完整月份，明確控制月份、任務相依、失敗停止點及發布資格 |
| 今日交付物 | 固定版本的 Airflow 執行環境、Docker Compose 啟動說明、monthly DAG、可供 DAG 呼叫的單月入口、驗證證據與學習紀錄 |
| 目前狀態 | Day 14 的 Compose、雲端身分、正式 monthly DAG 與已發布月份的完整安全重跑均已驗證；新月份首次發布與自動月度運轉待後續驗收，詳見[執行紀錄](day14-run-record.md) |

今天將既有人工串接的流程轉為可觀察、可重跑的 Airflow 任務。MVP 固定美國進口 `842／M`、商品 `8542`、分類 `H6`。本機 Airflow 只在服務啟動期間運作；不要因 Day 11 已發布 24 個月，就將 DAG 測試算成完成。

## 1. 盤點現有入口並畫出任務邊界

**預計時間：35～45 分鐘。**

- [x] 列出每段目前的單月輸入、輸出與失敗型態：Lambda 擷取、S3 manifest／checksum、`RawLoader`、dbt candidate、`Publisher.audit()` 與 `Publisher.publish()`。
- [x] 確認現有 `scripts/ingest_day11.py`、`scripts/load_day11_range.py`、`scripts/publish_day11_range.py` 主要處理固定歷史範圍；正式 DAG 使用可參數化、明確回傳成功／失敗的 `scripts/monthly_steps.py`。
- [x] 記錄 dbt 目前的固定原始資料日期範圍、profile／target、候選 Dataset 與來源 Dataset；按月 build 會重建 candidate，發布前由來源查驗與品質流程核對本月版本。
- [x] 定義單一 `period × cmd_code × hs_version` 為管線單位；`partner_detail` 與 `world_total` 分開擷取及載入，兩者通過來源與 raw 驗證後才進入 dbt。

預期相依關係：

```text
選定目標月份與確認可用性
  → 擷取 partner_detail／world_total
  → 驗證 manifest、checksum 與兩種來源的身分
  → 載入兩種來源並完成 raw audit
  → dbt candidate build／test
  → 凍結候選批次與品質 audit
  → PASS／WARN gate
  → 發布指定月份；FAIL 保留原正式版本
```

每段任務產出可查的狀態與識別碼；不要讓範圍腳本捕捉錯誤後仍以 exit code 0 結束，使 Airflow 把失敗誤判為成功。

## 2. 建立固定且可啟動的本機 Airflow 環境

**預計時間：60～75 分鐘。**

- [x] 選定 Airflow 3.3.2、Python 3.11、dbt Core 1.12.5 與 BigQuery adapter 1.12.1；Airflow 與專案 virtualenv 隔離。
- [x] 新增 Docker Compose、Airflow 設定與 DAG／程式掛載；容器不內嵌 AWS／GCP 金鑰，以本機唯讀掛載供應身分。
- [x] 建立共用 pipeline Pool，slot 數為 1，並設定 monthly DAG 的 `max_active_runs=1`。
- [x] 在 README 寫明啟動、查看 DAG／任務日誌與停止命令，以及本機服務未執行就不會自動排程的限制。

驗證容器能啟動、DAG 能被載入、沒有 import error；將實際映像版本、啟動命令及結果寫入執行紀錄。版本號只填入實際驗證過的組合。

## 3. 定義 monthly schedule 與月份推導

**預計時間：40～50 分鐘。**

- [x] 使用明確的每月 time-based schedule、時區、`start_date` 與 `catchup` 政策；人工觸發明確給定目標月份。
- [x] 以 Airflow 資料區間邊界計算完整月份，日誌保存 logical date、data interval 與 DAG run ID；月初與跨年月份用單元測試驗證。
- [x] 最多回看 3 個候選月份，區分 `not_available`、已發布及待處理；Day 15 再補強月度運轉與重試政策。
- [x] 對未就緒月份記錄檢查時間與狀態，明確 skip；HTTP／不完整來源配對視為錯誤。

月份測試至少涵蓋一般月初、跨年、手動指定月份、非法月份、三期邊界及相同 DAG run 重試，避免處理進行中的當月。

## 4. 接上既有單月流程，限制 XCom 與併發

**預計時間：90～120 分鐘。**

- [x] 建立 `dags/` 下的 monthly DAG；DAG import 不發出雲端請求或執行 dbt。
- [x] 擷取任務傳入月份、來源種類、revision 與 run ID；驗證來源身分與 S3 data／manifest 配對，兩類來源完成後才進入下游。
- [x] 載入任務使用單月、單種類入口；`already_exists`、`already_loaded` 需驗證版本與 checksum 才安全續跑。
- [x] dbt build／test 固定 target、profile 與執行環境；品質 audit 持久化後才進 gate，FAIL 阻擋 publish。
- [x] 發布沿用 `Publisher` 的凍結批次、品質與交易式替換保護，並核對 publication attempt 結果。
- [x] XCom 只傳小型 metadata；原始 NDJSON、manifest 全文、候選資料列與 credential 不進 XCom。

共用 Pool 控制整段有寫入風險的工作，避免 monthly 與未來 backfill 同時修改共用資料；API 請求間隔仍由 client 控制，Pool 不代表每秒速率限制。

## 5. 驗證單月執行、重跑與失敗停止點

**預計時間：60～80 分鐘，加上實際雲端等待。**

先用隔離 fixture 驗證 DAG 結構、月份推導與失敗分支，再選一個有權限且可核對的真實月份，從 availability 跑到正式發布。若選擇已發布月份，驗證應為安全的 `already_published`／等效冪等結果；不要為求新增發布而改寫既有成功版本。固定範圍為 `8542／H6`，並保存 Airflow run／task IDs、S3 來源身分、BigQuery job IDs、品質狀態、發布結果與時間。

| 情境 | 預期結果 |
|---|---|
| DAG import、排程與月份邊界 | 無 import error；月初與跨年的目標月份正確；單次最多 3 個候選月份 |
| 兩種來源均可用 | detail／World 身分與 checksum 通過，raw、candidate、audit 與正式版本可追溯 |
| 來源尚未可用 | 明確 `not_available`／skip，不觸發下游寫入；下一次排程或人工執行可再檢查 |
| 擷取、驗證或 raw 載入失敗 | 下游 dbt／發布不執行；任務顯示失敗原因與 log 位置 |
| 品質 FAIL | audit 保留原因；publish 不執行，原正式版本與 `published_at` 不變 |
| 同一月份重跑 | 不複製 raw grain，不產生不必要的新 revision；已發布相同批次維持原時間 |
| 發布結果不明 | 查 job 與發布紀錄後再決定重試；不把逾時直接當成回滾 |

真實來源若沒有 `not_available` 或品質 FAIL，可用明確標記的隔離 fixture 驗證，不將 fixture 結果寫成真實雲端執行。故障復原、獨立 backfill DAG 與三個月 smoke test 留待 Day 16 的 M4 驗收。

## 6. 交付、記錄與學習檢查

**預計時間：25～35 分鐘。**

| 交付物 | 最少內容 |
|---|---|
| Airflow 環境與 DAG | Compose／固定依賴、Pool、monthly DAG、單月任務入口及必要設定 |
| README 操作說明 | 身分與權限前置、啟停方式、手動單月執行、查 log 的方式及本機排程限制 |
| 執行紀錄與證據 | 實際版本、DAG import 結果、月份測試、單月 task／job IDs、品質與發布查核、失敗分支 |
| [學習日誌](learning-log.md) | 實際日期與本人投入時間、task 邊界選擇、驗收結果及未解問題 |

完成後用自己的話回答：

1. 為什麼不能直接拿系統今天日期或 logical date 的月份當作目標資料月份？
2. `not_available`、HTTP 失敗與品質 FAIL 分別在哪個任務停止？
3. 為什麼 XCom 只放 metadata，原始檔與候選資料應放在哪裡？
4. Airflow Pool、`max_active_runs` 與 API client 的請求間隔各控制什麼？
5. dbt candidate build 成功後，為什麼仍需凍結批次、品質 audit 與 gate 才能發布？

- [x] Compose 可重現啟動，版本已固定；monthly DAG 無 import error。
- [x] 月份推導、最多 3 個候選月份、單月參數與 XCom 邊界有可重現驗證。
- [x] 真實已發布月份完成來源 → raw → candidate → audit → gate → publish 的安全重跑；job／run 證據可從 Airflow 與 BigQuery 追溯。
- [x] `not_available`、來源／載入失敗與品質 FAIL 的停損分支已用隔離測試驗證；本次真實雲端沒有遇到這些故障。
- [x] README、執行紀錄與學習日誌寫明實測結果；[總規格](trade-analytics-spec.md)的 Day 14 驗收條件已達成。

Day 15 接續月度運轉、有限期數檢查、重試與告警；Day 16 再以獨立 backfill DAG 驗證復原及 M4。
