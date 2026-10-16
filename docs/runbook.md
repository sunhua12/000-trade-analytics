# 核心流程操作手冊

首次安裝、身分設定、建表與單月操作見 [README](../README.md)。Lambda image 建置與部署設定見 [手動部署與首次建表](../README.md#手動部署與首次建表)。以下啟動與停止指令均從專案根目錄執行。

## 啟動靜態網站

```bash
node frontend/build.mjs
node frontend/serve.mjs
```

開啟 http://127.0.0.1:4173。使用已提交的公開快照，不需啟動 Python 或提供雲端憑證。終端機以 Ctrl+C 停止預覽。

## 啟動 Airflow Web UI

先啟動 Docker Desktop。在第二個終端機進入專案根目錄：

```bash
cd /Users/syunhua/Documents/10_Projects/000-trade-analytics
```

### 首次設定

若尚無本機 override，複製範本；已有設定時保留原檔：

```bash
if [ ! -f docker/compose.aws.yaml ]; then
  cp docker/compose.identity.example.yaml docker/compose.aws.yaml
fi
```

確認 `.env` 的 AWS profile、S3 bucket、GCP project 與 Dataset 已填妥，並設定 `FERNET_KEY` 與 `AIRFLOW__API_AUTH__JWT_SECRET`。尚未設定時，可用以下指令產生，再將結果填入 `.env`；既有環境沿用原 key：

```bash
.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 啟動與登入

```bash
docker compose --project-directory . \
  -f docker/compose.yaml -f docker/compose.aws.yaml \
  up -d --build
```

Compose 會先執行 `airflow-init`，其他 Airflow 服務等待初始化完成。等待服務啟動後，開啟 [Airflow：http://localhost:8080](http://localhost:8080)。未修改管理員設定時，預設帳號與密碼都是 `airflow`；自訂值使用 `_AIRFLOW_WWW_USER_USERNAME` 與 `_AIRFLOW_WWW_USER_PASSWORD`，既有帳號沿用原登入資料。

Dockerfile 與 Compose 設定集中於 `docker/`；`.dockerignore` 與 `.env` 留在根目錄。`--project-directory .` 保持原本的建置範圍、掛載路徑與 Compose 專案名稱，沿用現有 PostgreSQL volume。`docker/compose.aws.yaml` 不提交 Git。

第一次執行 pipeline 前，建立單 slot Pool：

```bash
docker compose --project-directory . \
  -f docker/compose.yaml -f docker/compose.aws.yaml \
  exec airflow-scheduler airflow pools set trade_pipeline 1 'Serial trade pipeline'
```

登入後可找到 `trade_monthly_pipeline` 與 `trade_backfill_pipeline`。啟用月度 DAG 才會依排程執行；backfill 僅接受手動觸發，輸入方式見下方「重跑與修訂」。

### 狀態與日誌

若頁面尚未開啟，先確認服務狀態與 API server 日誌：

```bash
docker compose --project-directory . \
  -f docker/compose.yaml -f docker/compose.aws.yaml ps
docker compose --project-directory . \
  -f docker/compose.yaml -f docker/compose.aws.yaml \
  logs --tail=100 airflow-apiserver airflow-init
```

## 本機 CLI 擷取

安裝套件後使用 `trade-ingest`；若從舊版本切換，先重新安裝以註冊新指令：

```bash
.venv/bin/python -m pip install -e '.[dev,warehouse]'
.venv/bin/trade-ingest --period 202412 --query-type partner_detail
.venv/bin/trade-ingest --period 202412 --query-type world_total
```

預設將 Raw 與 Manifest 寫入 `data/preview/`，可用 `--output-dir` 指定目錄。此指令呼叫 Comtrade API 並保存本機資料，不會呼叫 Lambda 或載入 BigQuery。啟用虛擬環境後可直接使用 `trade-ingest`，也可用 `.venv/bin/python -m trade_analytics.ingestion.cli` 執行相同入口。

## 重跑與修訂

- 同月同 revision：沿用來源檔，驗證 checksum、Manifest 與 Raw snapshot；重跑 load 不追加資料。
- 來源修訂：明確指定下一個 revision，保存舊來源；Raw loader 防止舊版覆蓋新版。
- 手動 monthly：`{"period":"202412"}`，可用 `replay_run_id` 指定本次擷取識別碼。
- Backfill：`{"start_period":"202301","end_period":"202303"}`；每批最多 3 個月。`revisions` 可指定兩種來源版本，`replay_run_ids` 可指定每月擷取識別碼。
- Monthly 每次處理最近最多 3 個完整月份，已存在的來源與 Raw 仍驗證後重跑 dbt；更早月份需人工 backfill。immutable 來源不自動偵測同 revision 的 API 修訂。

## 失敗排查

1. 從 Airflow task log 的 period、run_id、step、kind 找到失敗位置。
2. ingestion 失敗查看 Lambda 基本日誌；S3 檔案不完整或 checksum conflict 應先查明，不覆寫來源。
3. load 失敗查看 BigQuery job 與 `audit_ingestion_runs`；交易式替換失敗後重跑相同 task。
4. dbt 失敗查看 `dbt/target/run_results.json` 與 `dbt/logs`；修正來源或模型後重跑 build。後續 task 不會繼續，但先前建立的表不會自動 rollback。
5. 匯出失敗檢查 ADC、展示 Dataset 與 dbt artifacts 是否同 target；網站資料驗證失敗則重新建置同一版本，勿逐檔覆蓋正式資源。

## 切換到簡化版本

先暫停兩個 DAG、等待既有 run 結束，再依 [README](../README.md)設定新 dbt profile、建置 Mart、建置靜態網站 並恢復排程。不要讓舊版 worker 與新版流程交錯操作。

## 停止與清理

`docker compose --project-directory . -f docker/compose.yaml -f docker/compose.aws.yaml down` 停止本機 Airflow；不加 `-v` 以保留 PostgreSQL volume。網站預覽用 Ctrl+C 停止。

本次程式瘦身不清除任何雲端服務。現有 Cloud Run、Alarm／SNS、GitHub 部署角色與專用 state bucket 若不再使用，另行盤點後手動停用；Lambda、來源 S3、ECR 與執行角色保留。共享 IAM／OIDC provider 不隨單一專案移除。

## 匯出靜態前端 JSON

資料契約見 [前端資料契約](frontend-data-contract.md)，頁面資訊架構見 [頁面草圖](dashboard-wireframe.md)。此步驟只產生 JSON；網站建置與部署見下節。

先停止其他資料寫入與 dbt 建置。沿用專案既有 GCP ADC 與 dbt profile，確保 dbt 與匯出使用相同 project／dataset。以下需要已載入的 Raw 資料及已建立的 seeds；新環境仍應先依前面的設定流程準備。

```bash
.venv-dbt/bin/dbt build --project-dir dbt --profiles-dir dbt
.venv/bin/python -m trade_analytics.export.cli \
  --dbt-artifacts dbt/target \
  --start-month 2023-01-01 \
  --end-exclusive 2025-01-01 \
  --output-dir data/frontend
.venv/bin/python -m trade_analytics.export.cli \
  --verify-only --output-dir data/frontend
```

上面三個指令依序執行，前一步成功才進行下一步。dbt build 成功後須在 24 小時內匯出。匯出沿用 `TRADE_BQ_PROJECT`、`TRADE_BQ_DATASET`、`TRADE_BQ_LOCATION`、`TRADE_BQ_MAX_BYTES_BILLED`；CLI 的 `--project`、`--dataset` 可覆寫前兩者。未指定日期時沿用現有 `TRADE_EXPORT_FIRST_MONTH` 與 `TRADE_EXPORT_AFTER_LAST_MONTH`；為相容既有 .env，仍接受舊 TRADE_DASHBOARD 日期變數作為 fallback。

亦可安裝更新後的套件取得 `trade-export` entrypoint：

```bash
.venv/bin/python -m pip install -e '.[warehouse]'
trade-export --dbt-artifacts dbt/target --output-dir data/frontend
```

成功時 stdout 回傳 JSON metadata，內含版本目錄、筆數與 checksum。`data/frontend/current.json` 指向可用版本；驗證失敗回傳非零 exit code，不切換舊版本。使用 `--verify-only` 不需雲端憑證。

公開前只複製該版本目錄中的 `manifest.json`、`monthly.json`、`partners.json`，不要複製 `audit/`。下一階段再將這三檔接到前端及網站發布流程。

更新 Python 契約後，以以下指令同步 JSON Schema；離線測試會檢查 schema 與程式碼一致：

```bash
.venv/bin/python -m trade_analytics.export.schemas --output-dir docs/schemas
```


## 批次更新與完整網站產物

月度與回填 DAG 已改為兩個 task：前置檢查、process_batch。後者在單 slot Pool 中持續占用到整批寫入、dbt 測試、JSON 匯出與網站建置完成。空計畫不匯出，任一選定月份失敗也不匯出。

本機可使用相同入口；先依 README 載入 .env 與雲端身分：

```bash
.venv/bin/python scripts/run_batch.py \
  --plan '{"selected":[{"period":"202412","run_id":"manual-202412","revisions":{"partner_detail":1,"world_total":1}}]}' \
  --dbt-executable .venv-dbt/bin/dbt
```

產物分為 `data/frontend/current.json`（JSON 版本）與 `data/website/current.json`（完整網站版本）。回填舊月份不會縮短既有展示上界。超過 60 個月時拒絕匯出，需另行規劃展示範圍。

同一個檔案系統上的支援入口以 `data/pipeline.lock` 序列化；worker 共用 Compose 掛載的 data 目錄。直接呼叫 dbt／BigQuery 或不支援 flock 的跨主機檔案系統不受此鎖保護。手動直接執行這些工具前，仍須暫停兩個 DAG 並等待既有批次結束。

暫時性錯誤會重試整批，先前成功步驟依冪等規則重跑；永久驗證錯誤停止。既有 backfill recovery_probe 現在作用於 process_batch 的首次嘗試，模擬 load 已提交但回覆遺失，不會在每次重試重複注入。

## 建置與發布網站

更新前端的公開快照並建置：

```bash
.venv/bin/python scripts/build_frontend.py --stage-data
node --test frontend/tests/*.test.mjs
node frontend/build.mjs
```

Python builder 先驗證目前 JSON，再產生完整 `data/website/<release_id>/`。Node builder 核對前端公開快照的版本、checksum 與筆數，再產生 `frontend/dist/`。兩者都只攜帶公開 manifest／monthly／partners 與前端資源，不攜帶 audit、.env 或雲端憑證。

正式網站由 Sites 插件管理，identity 位於 `frontend/.openai/hosting.json`。更新時沿用同一個 project_id 與原有 audience，取得短效來源憑證，在獨立且清理過的 frontend checkout 執行 Sites source helper，推送相符來源並封裝 dist，最後保存及部署該版本。憑證只能透過 stdin 傳入 helper，不存入 repository、檔案或 shell 參數。

Airflow 不持有 Sites 憑證，也不直接發布網站。每次資料更新後，完成上述建置與驗證，再透過 Sites 發布整個版本；正式網站在部署成功前仍顯示上一版。若部署失敗，保留原版本及回傳的 deployment/version IDs，不建立新的 Site。

## 升級現有 Airflow 環境

暫停兩個 DAG 並等待舊 run 結束，再重新 build／啟動 Compose。新 worker 需要更新過的 Python 套件，Compose 也新增 data 共享寫入目錄與 frontend 唯讀掛載。不要讓舊版 19-task DAG 的 worker 與新版批次任務並行。

檢查 data 目錄對 AIRFLOW_UID 有寫入權限，並維持 trade_pipeline Pool 為 1。這次不會自動觸發正式資料更新或變更既有排程的 paused 狀態。
