# Lambda Container Image and S3 Ingestion Design

## 1. 目標與範圍

將 Phase 1 的 UN Comtrade ingestion package 封裝為 AWS Lambda Container Image，讓單一 Lambda event 可擷取一個月份、單一查詢類型的資料，並將 `data.ndjson` 與 `manifest.json` 寫入 Amazon S3。

本次交付包含 Lambda Handler、S3 storage adapter、Docker Image、測試與 AWS Console 操作說明。AWS 帳號內的 ECR、Lambda、S3、IAM 與環境變數由使用者透過 AWS Console 手動建立。本次不建立 IaC、不推送 ECR、不部署 Lambda，也不包含正式 UN Comtrade API Key、BigQuery 或 Airflow。

## 2. 架構與責任邊界

```text
Lambda event
  -> Lambda handler
  -> ComtradeQuery
  -> ComtradeClient
  -> IngestionService
  -> S3Storage
  -> s3://<bucket>/<prefix>/period=<YYYYMM>/query_type=<type>/
       data.ndjson
       manifest.json
```

- Phase 1 的 query、HTTP retry、schema 與資料契約保持不變。
- Handler 只負責事件解析、組裝依賴、記錄結果與回傳可序列化 metadata。
- `S3Storage` 只負責序列化、冪等檢查及 S3 object 寫入。
- Docker Image 使用 AWS 官方 Python 3.11 Lambda Base Image。
- AWS credential 不進入 Image；執行時使用 Lambda execution role。

## 3. Lambda 事件與回傳

輸入事件：

```json
{
  "action": "ingest",
  "period": "202401",
  "cmd_code": "8542",
  "query_type": "partner_detail",
  "run_id": "manual__2026-08-29T00:00:00Z"
}
```

規則：

- `action` 必須是 `ingest`。
- `period` 必須是有效 `YYYYMM`。
- `cmd_code` 預設為 `8542`。
- `query_type` 僅接受 `partner_detail` 或 `world_total`。
- `run_id` 可省略；若有提供，會出現在 structured log，不寫進 Raw data。

成功回傳：

```json
{
  "status": "success",
  "period": "202401",
  "query_type": "partner_detail",
  "row_count": 62,
  "checksum": "sha256:...",
  "data_uri": "s3://bucket/un_comtrade/period=202401/query_type=partner_detail/data.ndjson",
  "manifest_uri": "s3://bucket/un_comtrade/period=202401/query_type=partner_detail/manifest.json"
}
```

相同內容已存在時，`status` 回傳 `already_exists`。輸入錯誤、API 錯誤、資料契約錯誤與 S3 checksum 衝突會讓 invocation 失敗，保留 Lambda 的失敗狀態供告警與重試使用。

## 4. 執行環境設定

必要環境變數：

| 名稱 | 用途 |
|---|---|
| `RAW_BUCKET` | S3 Raw bucket 名稱 |

選用環境變數：

| 名稱 | 預設值 | 用途 |
|---|---|---|
| `RAW_PREFIX` | `un_comtrade` | S3 object key 前綴 |
| `COMTRADE_BASE_URL` | Phase 1 Preview endpoint | 覆寫 API endpoint |

Image 不包含 AWS access key、secret key 或 Comtrade API Key。正式 API 認證留待後續正式 API 子階段設計。

## 5. S3 儲存與冪等性

Object key：

```text
<prefix>/period=<period>/query_type=<query_type>/data.ndjson
<prefix>/period=<period>/query_type=<query_type>/manifest.json
```

寫入規則：

1. 對 Phase 1 產生的 deterministic NDJSON 計算 SHA-256。
2. 若兩個 objects 都不存在，依序寫入 data 與 manifest。
3. 若兩個 objects 都存在且 manifest checksum 相同，回傳 `already_exists`。
4. 若已存在的 checksum 不同，拋出衝突錯誤，不覆蓋 Raw data。
5. 若只存在其中一個 object，驗證既有內容；內容與本次輸出相符才補齊另一個 object，否則拋出衝突錯誤。
6. Objects 使用 `application/x-ndjson` 與 `application/json` content type，並依 bucket 預設加密設定保存。

Lambda reserved concurrency 建議在 Console 設為 `1`，降低 Preview API 限流與相同 partition 併發寫入風險。

## 6. Docker Image

Dockerfile：

- Base image：`public.ecr.aws/lambda/python:3.11`。
- 將 package 安裝到 `${LAMBDA_TASK_ROOT}`。
- 安裝專案宣告的 runtime dependencies，包含明確版本範圍的 `boto3`。
- Handler command：`trade_analytics.lambda_handler.handler`。
- `.dockerignore` 排除 `.git`、`.venv`、測試 cache、Raw data、文件及本機秘密檔案。

本機預設建置 `linux/amd64`，AWS Lambda 建立時必須選擇相同架構。Image tag 供人工測試使用；正式部署建議在 Lambda 選取 ECR image digest，以避免 tag 被覆寫。

## 7. 測試策略

### Unit Tests

- Handler 合法事件會建立 query 並回傳 storage metadata。
- Handler 拒絕未知 action、非法 period 與未知 query type。
- Handler 缺少 `RAW_BUCKET` 時回報明確設定錯誤。
- `S3Storage` 產生正確 key、body 與 content type。
- 完整相同 objects 回傳 `already_exists`。
- checksum 衝突不覆蓋既有 objects。
- 單一 object 殘留時可安全補齊，內容衝突時失敗。

AWS 呼叫以 botocore `Stubber` 或等價的記憶體 fake 驗證行為，測試不連真實 AWS，也不要求開發者 AWS credential。

### Container Verification

1. 執行完整 unit tests、Ruff 與 mypy。
2. 建置 `linux/amd64` Image。
3. 啟動 Lambda Runtime Interface Emulator。
4. 以不會進入 API／S3 流程的非法事件呼叫 Handler，確認收到預期的輸入錯誤。
5. 檢查 Image architecture、Handler 可匯入及 container health；完整成功事件留待部署至使用者的測試 bucket 後驗證。

若本機沒有 Docker daemon，交付 Dockerfile 與測試結果，並明確標示 Image 尚未在本機完成建置；不得宣稱 Image 已驗證。

## 8. AWS Console 手動建置範圍

部署文件依序說明：

1. 建立阻擋公開存取並啟用預設加密的 S3 bucket。
2. 建立 ECR private repository，從本機登入、tag 並 push Image。
3. 建立最小權限 Lambda execution role，只允許指定 prefix 的 S3 read/write 與 CloudWatch Logs。
4. 由 ECR Image 建立 Lambda，選擇 `x86_64`，設定 timeout、memory、reserved concurrency 與環境變數。
5. 使用兩個測試事件分別驗證 `partner_detail` 與 `world_total`。
6. 在 S3 Console 檢查 data、manifest、row count 與 checksum。

文件不要求使用 Terminal 建立 AWS 資源；只有 Docker build、ECR login/tag/push 需要執行 AWS CLI 與 Docker commands。

## 9. 交付物與驗收標準

交付物：

- Lambda Handler 與事件 schema。
- S3 storage adapter 與錯誤類型。
- Unit Tests。
- `Dockerfile` 與 `.dockerignore`。
- 本機 Image 建置及 invocation scripts／指令。
- AWS Console 手動部署文件。

驗收標準：

- 現有 Phase 1 tests 不退步。
- 新增 Unit Tests 通過，總 coverage 不低於 85%。
- Ruff、mypy 與 Docker build 通過。
- Image 可由 Lambda Runtime Interface Emulator 載入 Handler。
- 同一事件重跑不重複或靜默覆蓋 Raw data。
- Repository 與 Image 不包含 credential。
- AWS 資源由使用者依文件在 Console 建立，程式不自動修改 AWS 帳號狀態。
