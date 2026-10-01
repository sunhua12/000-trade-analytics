# Day 18：Cloud Run 展示操作手冊

## 服務與執行邊界

[Live Demo](https://trade-dashboard-898093147725.asia-northeast1.run.app) 使用專案 `trade-analytics-508604`、region `asia-northeast1`、服務 `trade-dashboard` 與 Artifact Registry repository `trade-dashboard`。公開頁面只展示已發布的美國月度進口 `8542／H6`；目前雲端展示範圍為 `202301～202504`，共 28 個已發布月份，不代表最新可取得月份。

Runtime 為 `trade-dashboard-runtime@trade-analytics-508604.iam.gserviceaccount.com`，只取得專案 `roles/bigquery.jobUser` 與 `trade_analytics_published` Dataset `READER`。部署使用既有授權的 gcloud 使用者，首次操作需要 API 啟用、registry／Service Account 建立及 IAM 設定權限；日常部署需要推送映像、更新 Cloud Run 及對 runtime 的 `iam.serviceAccounts.actAs` 權限。本日未建立 GCP WIF，也未使用 Day 17 的 AWS OIDC role 部署 GCP。

## 首次環境建立

在專案根目錄，以已授權身分操作。先用 `describe` 查明資源是否存在；存在則沿用，不刪除重建。下列 create 指令僅執行於資源不存在時。

```bash
gcloud services enable run.googleapis.com artifactregistry.googleapis.com iam.googleapis.com --project=trade-analytics-508604
gcloud artifacts repositories create trade-dashboard --repository-format=docker --location=asia-northeast1 --project=trade-analytics-508604
gcloud iam service-accounts create trade-dashboard-runtime --project=trade-analytics-508604 --display-name='Trade dashboard published-data reader'
gcloud projects add-iam-policy-binding trade-analytics-508604 --member=serviceAccount:trade-dashboard-runtime@trade-analytics-508604.iam.gserviceaccount.com --role=roles/bigquery.jobUser --condition=None
.venv-dbt/bin/python scripts/configure_dashboard_access.py
```

BigQuery 權限腳本以執行者的 ADC 更新 ACL，保留原有 access entries，重跑不重複新增 runtime。完成後檢查 project IAM、project ancestors 與 raw／candidate／published ACL：本專案沒有 organization／folder ancestor；runtime 沒有 project viewer／editor 等額外角色，raw 與 `trade_analytics_day10_dev` candidate 未授權此身分。日後新增群組或專案層角色時應重新檢查有效權限。

## 建置與更新

```bash
bash scripts/deploy_dashboard.sh
```

腳本建置 `linux/amd64` 的 `Dockerfile.dashboard`，推送 Artifact Registry，再用 image digest 部署；映像 tag 與 revision label 保存 base Git SHA 及容器來源 SHA-256 的前 16 碼。工作目錄未提交時，base Git SHA 不是完整部署原始碼版本，須同時保存 source hash／來源清單與修改內容。部署證據輸出於 `docs/evidence/day18/`，新部署前先保存上一批證據。

容器以 UID `10001` 執行，Streamlit 綁定 `0.0.0.0` 與 `$PORT`，不內建 JSON key 或 ADC。僅複製 `pyproject.toml`、`src/` 與 `dashboard.py`；實際 BigQuery ADC 來自 Cloud Run runtime 身分。

| 設定 | 本次值 |
|---|---|
| CPU／memory | 1 CPU／1 GiB |
| 最小／最大 instances | 0／1；service 與 revision 上限均為 1 |
| Concurrency／request timeout | 10／3600 秒；長連線仍受 request timeout 影響 |
| BigQuery project／location | `trade-analytics-508604`／`asia-northeast1` |
| 每 query 上限／快取 TTL | `1000000000` bytes／`3600` 秒 |
| 日期設定 | `TRADE_DASHBOARD_FIRST_MONTH=2023-01-01`；`TRADE_DASHBOARD_AFTER_LAST_MONTH=2025-05-01`，後者不含 |
| 公開存取 | `allUsers` 的 Cloud Run invoker；registry 與 BigQuery Dataset 沒有公開授權 |

可透過 `TRADE_DASHBOARD_AFTER_LAST_MONTH` 改變部署腳本的日期上界；其他公開參數為 `TRADE_BQ_PROJECT`、`TRADE_BQ_LOCATION`、`TRADE_RUN_REGION`、`TRADE_RUN_SERVICE`、`TRADE_RUN_REPOSITORY`。展示範圍最多 60 個完整月份；頁面只列出此範圍內已有正式資料的月份。擴大日期範圍不會觸發回填，必須先由 pipeline 發布。

## 驗證與故障排查

```bash
bash scripts/check_dashboard_container.sh trade-dashboard:cloud-run
.venv-dbt/bin/python scripts/verify_day18.py
gcloud run services describe trade-dashboard --region=asia-northeast1 --project=trade-analytics-508604
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="trade-dashboard"' --project=trade-analytics-508604 --limit=30
```

第一個命令需要先以對應 tag 建置本機 image；它驗證不同的 `PORT=8090`、健康端點與非 root UID，不需要雲端憑證。第二個命令使用執行者 ADC，核對真實 SQL 與本機 Streamlit AppTest，不能取代 Live URL 瀏覽器操作。CI 已加入 Dashboard image 建置與上述無雲端身分的容器 smoke。

線上至少驗證 `202401～202412／partner 458` 與 `202504`：日期、Partner、金額、YoY、HHI 狀態及品質時間都應隨篩選更新。資料未更新時依序檢查正式發布、設定的日期上界、快取、image digest 與 revision。按「重新讀取已發布資料」可清除目前 instance 快取；快取不跨 instance 共用。查詢權限或處理量錯誤應顯示清楚錯誤，不能展示舊結果冒充成功。

## E2E 安全重跑

沿用 [Day 16 手冊](day16-backfill-manual.md)，先查正式狀態並保存基準；保持 monthly DAG 暫停與單 slot Pool，不與其他 candidate writer 平行。本次重跑：

```bash
docker compose -f docker-compose.yaml -f compose.aws.yaml exec -T airflow-worker \
  airflow dags test trade_backfill_pipeline \
  -c '{"start_period":"202504","end_period":"202504","replay_run_ids":{"202504":"backfill-202504-32a1f3080f769f4e"}}'
```

這是既有來源與原發布 ID 的正常路徑安全重跑，ingest／load 可回傳 `already_exists`／`already_loaded`，publish 應回傳 `already_published`。不宣稱新增擷取或新發布，不傳 `--allow-republish`。重跑後比較 raw grain、正式 run ID 及 `published_at`，再核對線上該月份。

## 預算、停止與清理

使用者原始預算為 **USD 10／月**，因帳單幣別為 TWD，另明確指定本專案通知額度 **TWD 250／月**；不是匯率換算。Budget `98fca4e8-5f9b-46b0-ba06-1af7c38eb891` 限定 `projects/898093147725`、月曆月、排除 credits，50％／90％／100％ actual spend 及 100％ forecasted spend 使用預設 billing IAM recipients 通知。設定已查核，沒有刻意產生成本觸發通知，實際收到預算 email 尚未驗證。

預算通知與單 query／instances 上限均不是費用硬上限。保持 WebSocket 連線可能使 instance 持續活躍；展示完成後關閉頁面，降低持續運算。Artifact Registry 儲存與 pipeline 資源另有成本。Cloud Run WebSocket 限制參考 [Google 官方文件](https://docs.cloud.google.com/run/docs/triggering/websockets)；服務部署參考 [Streamlit 官方 Cloud Run 快速入門](https://docs.cloud.google.com/run/docs/quickstarts/build-and-deploy/deploy-python-streamlit-service)。

暫時停止外部展示可移除公開 invoker 並將 ingress 改為 internal，應同步檢查沒有其他公開存取方式；這仍保留服務與映像，不等於刪除所有費用來源：

```bash
gcloud run services remove-iam-policy-binding trade-dashboard --region=asia-northeast1 --project=trade-analytics-508604 --member=allUsers --role=roles/run.invoker
gcloud run services update trade-dashboard --region=asia-northeast1 --project=trade-analytics-508604 --ingress=internal
```

回復既有可用 revision 時先列出 revisions 並確認 digest，使用 `gcloud run services update-traffic ... --to-revisions=已驗證REVISION=100`。目前只有首次 revision，不能假設已有可回復舊版；真實回復與乾淨重建留待 Day 19。

永久清理時，先保存驗收證據與所需映像，再依序刪除 Cloud Run service、確認無共用者的 registry images／repository、移除 runtime 的 Dataset ACL 與 project binding、刪除專用 Service Account。Budget 保留或刪除依專案是否仍需通知決定。不得順帶刪除 BigQuery 正式／raw 資料、AWS pipeline 或既有 state。
