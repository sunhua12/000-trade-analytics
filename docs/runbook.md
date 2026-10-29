# 四階段 ETL 操作手冊

## 設定與完整執行

從專案根目錄執行，安裝方式見 README。Pipeline 讀取 `.env`，既有環境變數優先。必要設定為 `RAW_BUCKET`、`DBT_RAW_PROJECT`、`DBT_RAW_DATASET`、`TRADE_BQ_PROJECT`、`TRADE_BQ_DATASET` 與 `TRADE_BQ_LOCATION`。S3 執行權限需要限定前綴的 ListBucket、GetObject 與 PutObject；BigQuery 沿用既有 Raw、稽核與 Mart 權限。需要 Python 3.11、Node.js 22 與 dbt；`TRADE_DBT_EXECUTABLE` 指向 dbt 執行檔。

```bash
.venv/bin/trade-pipeline --start 202607 --end 202609 --refresh --run-id interview_demo
```

`--start`／`--end` 均含邊界；商品維持五個 IC 六碼商品；`--reporters 842 156` 可縮小擷取與載入範圍。`--full-refresh` 只控制 dbt。匯出仍讀取 2016 年起至結束月的完整 Mart 快照。

同批重跑沿用同一 `--run-id`、日期、市場與設定；要重新刷新 API，改用新的 run id。未指定 run id 的完整流程會產生並印出 ID；失敗後可使用該 ID 續跑。`--max-requests` 可於續跑時調整。

## 四階段獨立重跑

以下命令各自可在全新 Worker 執行；使用相同日期、市場及 `--refresh` 設定。S3 是階段交接來源，本機目錄只供單一 Task 暫存。

```bash
.venv/bin/trade-pipeline --start 202607 --end 202609 --refresh --run-id interview_demo --stage extract
.venv/bin/trade-pipeline --start 202607 --end 202609 --refresh --run-id interview_demo --stage load --upstream s3://YOUR_BUCKET/_pipeline/interview_demo/extract.json
.venv/bin/trade-pipeline --start 202607 --end 202609 --refresh --run-id interview_demo --stage transform --upstream s3://YOUR_BUCKET/_pipeline/interview_demo/load.json
.venv/bin/trade-pipeline --start 202607 --end 202609 --refresh --run-id interview_demo --stage publish --upstream s3://YOUR_BUCKET/_pipeline/interview_demo/transform.json
```

| Task | 輸入與工作 | 成功交接成果 |
|---|---|---|
| extract | API、Validation、S3 Raw；同批來源完成紀錄支援續跑 | `extract.json`：範圍、來源 URI、版本、Checksum、缺資料 |
| load | 從 S3 讀取並驗證，BigQuery 完整來源替換 | `load.json`：月份、載入結果、Job 資訊 |
| transform | 獨立 target／logs 執行 dbt build 與測試 | `transform.json`：成功證據、artifacts URI、Raw watermark |
| publish | 讀取 Mart、JSON v2 驗證、暫存目錄網站建置 | `publish.json`：快照與網站成品 URI |

每批成果位於 `_pipeline/<run-id>/`，Raw 路徑維持 `un_comtrade/v3/`。成功描述最後寫入；未完成上傳不能成為成功成果。`extract-progress.json` 僅供擷取續跑，不可拿來執行 load。失敗 dbt artifacts 保存在 `dbt/<attempt>/`，成功證據另存於 `build/<attempt>/`。

重跑 load 不重複資料；重跑 transform 不呼叫 API；重跑 publish 不載入 Raw。最新 transform 嘗試失敗後，即使同批曾成功，也必須修正後重跑 transform。dbt 證據超過 24 小時或 Raw watermark 改變，publish 要求重新 transform。

## 錯誤與 Airflow

| 退出碼 | 意義 | 行動 |
|---|---|---|
| 0 | 階段／指定模式成功 | 檢查最後一行成果 URI |
| 1 | 契約、版本、dbt 品質、網站建置或設定錯誤 | 修正後重跑失敗階段 |
| 2 | HTTP 額度用完 | 下游阻擋；同 run id 再次明確執行 extract |
| 75 | 暫時性網路／服務錯誤 | Airflow 最多重試 3 次，指數退避 |

DAG 固定 `extract → load → transform → publish`，全部使用 `all_success`。每月臺北時間 15 日 04：00 刷新最近三個完整月份；預設停用，以 `TRADE_MULTI_MARKET_SCHEDULE_ENABLED=true` 啟用。使用一個 active run 與 `trade_pipeline` 單槽 pool。先建立該 pool，再啟用排程。

重建 image 後部署，以取得 Node.js 22 與最新版 Python 套件。Compose 的 `PYTHONPATH` 指向掛載的 src，前端來源維持唯讀，publish 在自己的暫存副本建置。更新 image／設定後，以現有 Compose 專案重新建立 Airflow 服務，並保留憑證 override。執行前確認沒有 running／queued DAG run。

```bash
docker compose --project-directory . -f docker/compose.yaml build
docker compose --project-directory . -f docker/compose.yaml -f docker/compose.aws.yaml up -d --no-deps --no-build --wait airflow-apiserver airflow-scheduler airflow-dag-processor airflow-worker airflow-triggerer
```

在 Airflow UI 清除失敗 Task 後重跑；若重新執行上游而改變資料，連同下游一起清除重跑。CLI 與 Airflow 不同時操作同一組正式資料集；writer pool 只約束 Airflow，CLI 的本機 lock 不提供跨主機鎖。保留 BigQuery 交易內版本與併發檢查。

## 人工發布與回復

publish 只將成果保存至 S3，不會 commit、push 或部署。讀取 `publish.json`，下載其 `snapshot` URI，保留 `current.json` 與同一 snapshot id 目錄：

```bash
aws s3 cp s3://YOUR_BUCKET/_pipeline/interview_demo/publish.json /tmp/trade-publish.json
# 將上方 JSON 的 snapshot URI 代入；目的地使用全新的資料夾。
aws s3 cp s3://YOUR_BUCKET/_pipeline/interview_demo/releases/SNAPSHOT_ID/snapshot/ data/review-snapshot/ --recursive
.venv/bin/trade-export --snapshot-root data/review-snapshot
.venv/bin/trade-export --snapshot-root data/review-snapshot --stage-data frontend/public/data
node --test frontend/tests/*.test.mjs
node frontend/build.mjs
```

檢查資料差異後，人工 review、commit，透過既有 Pages workflow 公開。回復時下載較早成功成果，驗證後 stage；不要混合不同 snapshot 的 JSON。失敗發布維持前一份成功 `publish.json`，新檔案未被完成描述引用前不算發布。

舊 `--extract-only` 仍只寫本機 Raw；`--sync-only` 將指定範圍既有本機 Raw 上傳 S3 後接續處理，不呼叫 API，也不表示範圍已完整擷取。

## 五分鐘面試導覽與失敗示範

1. **第 1 分鐘：** 說明多市場貿易資料、月份／市場／商品／Partner 粒度，缺資料與零值分開。
2. **第 2 分鐘：** Python 擷取、HTTP Retry、截斷與 Validation；S3 Raw＋Manifest 支援稽核與重跑。
3. **第 3 分鐘：** BigQuery 來源完整替換與冪等；dbt SQL 負責 staging、fact、mart 與品質測試。核心分析屬 ELT。
4. **第 4 分鐘：** Airflow UI 展示四個 Task、依賴與失敗位置；XCom 只傳 S3 URI，換 Worker 仍可繼續。
5. **第 5 分鐘：** JSON v2、網站建置及人工發布；說明只接受最新倉儲資料，不保證重建歷史網站。

在隔離測試專案加入一個回傳資料列的 dbt data test，執行 transform：應失敗，publish 在 DAG 被阻擋。修正測試後重跑 transform，再執行 publish；API 與 load 不必重跑。不可在正式專案加入故意失敗的測試。自動化隔離腳本也涵蓋實際 dbt 失敗證據拒收。

## 隔離整合驗證

```bash
.venv/bin/python scripts/smoke_etl_cloud.py --project YOUR_PROJECT --bucket YOUR_BUCKET --run-id unique_lowercase_run_id --evidence-dir data/validation/unique-run
```

腳本建立獨立 fixture dataset 與 `_smoke/etl/<run-id>/`，驗證版本、刪除 Partner、併發衝突、dbt、JSON v2、網站建置與四階段持久化交接。刪除本機 Raw 後才執行 load，結束後清理測試 dataset、S3 物件及版本。需要相應建立／刪除權限；不執行正式歷史回補。既有正式 Raw、公開網站及 Pages workflow 不由測試改寫。
