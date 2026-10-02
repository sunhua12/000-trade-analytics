# Day 14：手動建置 Airflow 指南

## 為什麼使用 Airflow

目前來源擷取、raw 載入、來源查驗、dbt、品質 audit 與發布都能分別執行，但需要人工掌握順序與停損點。Airflow 負責依月份排程、管理任務相依、記錄每次執行狀態與日誌，並在上游失敗時阻止下游發布。資料仍由現有 Lambda、S3、BigQuery、dbt 與 `Publisher` 處理；Airflow 不儲存原始貿易資料。XCom 只傳月份、URI、checksum、筆數、run ID 等小型 metadata。

本專案採本機 Docker Compose：只有本機服務啟動時，排程才會運作。Compose、獨立的 Airflow image、`hello_world_dag` 練習流程與正式 `trade_monthly_pipeline` 均已建立並驗證。正式 monthly 已於持續營運工作恢復，且真實 scheduled run 發布 202607，見 [營運紀錄](continuous-operations-record.md)。下方 Day 14 驗收狀態保留為歷史；手動正式寫入前仍需先暫停 monthly。

## 已備妥的單月工作入口

從專案根目錄以 `scripts/monthly_steps.py` 執行。各指令成功時輸出一行 JSON metadata，失敗時以非零 exit code 結束；不要在 DAG 中呼叫固定 2023～2024 範圍的 Day 11 批次腳本。

| 順序 | 指令範例 | 任務用途 |
|---|---|---|
| 1 | `.venv/bin/python scripts/monthly_steps.py ingest --period 202401 --kind partner_detail --run-id local-202401` | 呼叫 Lambda 取得明細；另以 `--kind world_total` 取得 World |
| 2 | `.venv/bin/python scripts/monthly_steps.py load --period 202401 --kind partner_detail` | 驗證 S3 原檔並載入 raw；World 需再執行一次 |
| 3 | `.venv/bin/python scripts/monthly_steps.py attest --period 202401` | 從 S3 重新驗證兩種原檔與 raw，保存發布所需的來源查驗紀錄 |
| 4 | `.venv/bin/python scripts/monthly_steps.py build --period 202401 --dbt-executable .venv-dbt/bin/dbt` | 按目標月設定 raw 與月份維度範圍，執行 dbt build／test |
| 5 | `.venv/bin/python scripts/monthly_steps.py audit --period 202401 --run-id local-202401` | 凍結候選批次並持久化品質判定 |
| 6 | `.venv/bin/python scripts/monthly_steps.py gate --period 202401 --run-id local-202401` | 只讓 PASS／WARN 通過；FAIL 回傳非零 exit code |
| 7 | `.venv/bin/python scripts/monthly_steps.py publish --period 202401 --run-id local-202401` | 交易式發布指定月份，回報 `published` 或 `already_published` |

`ingest` 與 `load` 的兩種類型都必須完成，再開始 `attest`。每次新的品質嘗試要使用新的 run ID；同一次中斷重試沿用原 run ID。修訂來源時，逐一指定正確的 `--revision`，不假設兩種來源的 revision 一樣。`attest` 需要 Day 10 已存在的發布資料表；首次建立全新環境時，要先建出候選模型並初始化發布表。容器內指令改用容器中的 Python／dbt 路徑，不能呼叫 macOS 的 `.venv` 執行檔。

若該月份已由另一個 run ID 發布，`publish` 預設會阻擋再次取代；確認來源修訂與新候選批次後，才對該次 `publish` 加上 `--allow-republish`。用全新 run ID 重跑歷史月份不等於 `already_published`。同一批次重試仍由底層發布程序檢查冪等。

`build` 會重建 dbt 的模型，不是只更新單一 partition。它把原始資料讀取範圍與月份維度延伸到目標月；正式發布仍只針對指定月份。需要在同一個候選 Dataset 寫入時維持單一 writer。已用真實雲端的已發布月份驗證安全重跑；新月份的首次發布尚未驗證。

## 1. 啟動 Compose 與身分掛載

本專案已由 [Airflow 3.3.2 官方 Docker Compose 指南](https://airflow.apache.org/docs/apache-airflow/3.3.2/howto/docker-compose/index.html)建立設定，並擴充為專用 image。在專案根目錄操作：

```bash
docker compose version
docker compose -f docker-compose.yaml -f compose.aws.yaml config --quiet
docker compose -f docker-compose.yaml -f compose.aws.yaml up -d --build
docker compose -f docker-compose.yaml -f compose.aws.yaml ps
docker compose -f docker-compose.yaml -f compose.aws.yaml exec airflow-dag-processor airflow dags list-import-errors --local
```

`compose.aws.yaml` 是不提交的本機檔案；可由 [身分掛載範本](../compose.identity.example.yaml)建立，並指定現有的 `hua` AWS profile 和 GCP ADC。不要重新下載官方 `docker-compose.yaml` 或用範例 `.env` 覆蓋現有檔案；目前設定已含專用 image 與 Fernet key。在 macOS 上，確認 Docker Desktop 至少分配 4 GB 記憶體，較寬裕可配置 8 GB。開啟 `http://localhost:8080`；本機管理員使用啟動時設定的帳密。這個 Compose 是學習用環境，不代表雲端常駐部署。

## 2. 讓 worker 能執行本專案指令

已使用 `Dockerfile.airflow` 擴充官方 image，並在獨立 virtualenv 固定 dbt Core `1.12.5`／BigQuery adapter `1.12.1`。worker 已驗證 AWS、GCP 身分及 dbt 連線；以下是目前的執行邊界：

1. Airflow 與專案依賴維持分開；容器的專案 Python 為 `/opt/trade-venv/bin/python`，dbt 為 `/opt/trade-venv/bin/dbt`。主機的 `.venv` 不掛入 Linux 容器。
2. `scripts/`、`src/` 與 `dbt/` 已掛載到 `/opt/trade-analytics`；DAG 檔放 `dags/`。使用 Celery Compose 時，task 在 `airflow-worker` 執行，身分與檔案存取也需從 worker 驗證。
3. AWS SDK 透過 worker 的 `AWS_PROFILE=hua` 讀取本機唯讀掛載的 AWS 設定，提供 Lambda invoke 與 S3 read 權限；GCP 透過唯讀 ADC 與 `GOOGLE_CLOUD_PROJECT` 執行 BigQuery job。不要複製 credential 到 image、Git 或 XCom。更換身分後，從 worker 重新驗證唯讀身分與 BigQuery 查詢。
   AWS Lambda／S3 使用 `ap-northeast-1`，BigQuery 使用 `asia-northeast1`；兩者是不同供應商的區域代碼。
4. 將 `scripts/monthly_steps.py` 每個 subcommand 綁成獨立 task。`ingest`、`load` 各有明細與 World 兩支；下游依賴兩支都成功。`attest` → `build` → `audit` → `gate` → `publish` 依序執行，`gate` 失敗不走 `publish`。

官方也提供[擴充 image 的範例](https://airflow.apache.org/docs/apache-airflow/3.3.2/howto/docker-compose/index.html#using-custom-images)。使用專案獨立 virtualenv 時，DAG 的外部程式執行路徑應是該 virtualenv 的 Python；`build` 的 `--dbt-executable` 也指向同一環境的 dbt。

## 3. monthly DAG 的排程與驗證

正式 DAG 採台北時間每月 1 日的 `CronDataIntervalTimetable`、`catchup=False`、`max_active_runs=1` 與 `max_active_tasks=1`。排程 run 依 `data_interval_end` 確定已結束的月份；例如 2026-10-01 的 interval 結束時，最近一個完整月份為 202609。Day 15 的 DAG 已改成按最早月份優先，串行處理最多 3 個候選月中的可用月份；超過三期範圍的未發布月份另列為 `older_unpublished`。Airflow 3 的手動觸發要明確提供 `conf.period`。[官方模板說明](https://airflow.apache.org/docs/apache-airflow/3.3.2/templates-ref.html)可對照日期欄位。

建立 `trade_pipeline` Pool、slot 設為 1，讓 monthly 與 Day 16 backfill 共用。可用 CLI：

```bash
docker compose -f docker-compose.yaml -f compose.aws.yaml exec airflow-worker airflow pools get trade_pipeline
docker compose -f docker-compose.yaml -f compose.aws.yaml exec airflow-dag-processor airflow dags list-import-errors --local
docker compose -f docker-compose.yaml -f compose.aws.yaml exec airflow-worker airflow dags list-runs trade_monthly_pipeline
```

`scripts/monthly_plan.py` 在 S3 來源成對存在時直接認定可用；來源不存在時詢問 Comtrade Preview API。空結果為 `not_available`，HTTP／解析／不完整 S3 配對為錯誤。月份上限與未就緒分支已用隔離測試驗證；真實雲端的已發布月份完整重跑結果見 [執行紀錄](day14-run-record.md)。Day 15 重試與告警操作見 [操作手冊](day15-operations-manual.md)；獨立 backfill DAG 與故障復原驗收屬 Day 16。

手動執行已發布月份時，指定原本的發布 run ID 才會重跑同一批次。只有 `period` 時，已發布月份會略過；未發布月份會產生新的 run ID。先在 UI 確認 DAG 仍為暫停，然後使用：

```bash
docker compose -f docker-compose.yaml -f compose.aws.yaml exec airflow-worker airflow dags test trade_monthly_pipeline -c '{"period":"202412","replay_run_id":"day11-202412-final-v1"}'
docker compose -f docker-compose.yaml -f compose.aws.yaml down
```

## 驗收提醒

- `airflow dags list-import-errors` 為空，且兩種來源均成功後才開始 dbt。
- XCom 只保留 metadata；原始檔留在 S3，品質 audit 與正式版本留在 BigQuery。
- 品質 FAIL 不呼叫發布；同批次重跑確認正式版本與 `published_at` 不被不必要地改寫。
- 本機 Airflow 停止後不會自動處理未來月份；需明確處理下一次啟動時的漏跑期數。
