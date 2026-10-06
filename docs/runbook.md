# 核心流程操作手冊

首次安裝、身分設定、建表與單月操作見 [README](../README.md)。Lambda image 建置與部署設定見 [手動部署與首次建表](../README.md#手動部署與首次建表)。以下啟動與停止指令均從專案根目錄執行。

## 啟動 Streamlit demo

在第一個終端機載入本機設定並啟動：

```bash
cd /Users/syunhua/Documents/10_Projects/000-trade-analytics
set -a
source .env
set +a
.venv/bin/streamlit run src/trade_analytics/dashboard/app.py
```

開啟 [Streamlit：http://localhost:8501](http://localhost:8501)，終端機需保持運行。Dashboard 直接讀取 BigQuery Analytics Mart，展示前需已有資料，且 `TRADE_BQ_DATASET` 與 dbt profile 一致。

若尚未設定或需更新 GCP Application Default Credentials，先執行以下指令再啟動 Streamlit：

```bash
gcloud auth application-default login
```

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
.venv/bin/python -m pip install -e '.[dev,warehouse,dashboard]'
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
5. Streamlit 權限錯誤檢查 ADC、query job 權限及 `TRADE_BQ_DATASET`；更新資料後按重新讀取清除快取。

## 切換到簡化版本

先暫停兩個 DAG、等待既有 run 結束，再依 [README](../README.md)設定新 dbt profile、建置 Mart、切換 Dashboard 並恢復排程。不要讓舊版 worker 與新版流程交錯操作。

## 停止與清理

`docker compose --project-directory . -f docker/compose.yaml -f docker/compose.aws.yaml down` 停止本機 Airflow；不加 `-v` 以保留 PostgreSQL volume。Streamlit 用 Ctrl+C 停止。

本次程式瘦身不清除任何雲端服務。現有 Cloud Run、Alarm／SNS、GitHub 部署角色與專用 state bucket 若不再使用，另行盤點後手動停用；Lambda、來源 S3、ECR 與執行角色保留。共享 IAM／OIDC provider 不隨單一專案移除。
