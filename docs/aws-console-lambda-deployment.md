# AWS Console：Lambda Container 與 S3 手動部署

本文件只建立 Phase 2 第一個子階段：ECR、Lambda、IAM 與 S3。程式仍使用公開 UN Comtrade Preview API；不需要 Comtrade API Key，也不包含 BigQuery 或 Airflow。

Day 3 已更新為 schema version 2.0.0、v2 路徑與顯式 revision。實際部署驗收依 [Day 4 計畫](day-04-learning-plan.md) 執行。本文件更新不表示已建立或驗證 AWS 資源。Day 3 修改後必須重新建置 image，不能沿用先前 image 驗收新介面。

```bash
docker buildx build --platform linux/amd64 --provenance=false --load -t trade-analytics-ingestion:phase2 .
```

## 1. 先決條件

- 本機 Docker Desktop 已啟動。
- 已安裝並登入 AWS CLI；CLI 使用的 IAM identity 可以登入 ECR 並 push image。
- 選定一個 AWS Region，例如 `ap-northeast-1`。ECR repository 與 Lambda 必須位於同一 Region；S3 也建議使用相同 Region。
- 本機已有 `trade-analytics-ingestion:phase2` Image，且 architecture 是 `linux/amd64`。

檢查本機 Image：

```bash
docker image inspect trade-analytics-ingestion:phase2 \
  --format 'architecture={{.Architecture}} os={{.Os}} cmd={{json .Config.Cmd}}'
```

預期：

```text
architecture=amd64 os=linux cmd=["trade_analytics.lambda_handler.handler"]
```

AWS Lambda 只接受單一 Linux architecture 的 Container Image，本專案因此固定使用 `linux/amd64`／`x86_64`。[AWS Lambda Container Image requirements](https://docs.aws.amazon.com/lambda/latest/dg/images-create.html)

## 2. 透過 S3 Console 建立 Raw Bucket

1. 開啟 AWS Console，切換至選定 Region。
2. 進入 **S3** → **Buckets** → **Create bucket**。
3. **Bucket type** 選擇 **General purpose**。
4. 輸入全域唯一名稱，例如 `<your-prefix>-trade-analytics-raw`。
5. **Object Ownership** 保持 **Bucket owner enforced**，不要啟用 ACL。
6. **Block Public Access settings** 保持四項全部啟用。
7. **Bucket Versioning** 選擇 **Enable**。
8. **Default encryption** 選擇 **Server-side encryption with Amazon S3 managed keys（SSE-S3）**。
9. 建立 bucket，記下 bucket 名稱與 Region。

AWS 對新 bucket 預設封鎖公開存取，並以 SSE-S3 提供基礎加密；此專案的 Raw bucket 不需要公開存取。[AWS S3 bucket 建立文件](https://docs.aws.amazon.com/AmazonS3/latest/userguide/create-bucket-overview.html)

不必預先建立 `un_comtrade/` 資料夾；Lambda 第一次成功寫入時會直接建立 object keys。

## 3. 透過 ECR Console 建立 Private Repository

1. 進入 **Elastic Container Registry（ECR）**。
2. 選擇 **Private registry** → **Repositories** → **Create repository**。
3. **Visibility settings** 選擇 **Private**。
4. Repository name 輸入 `trade-analytics-ingestion`。
5. **Image tag immutability** 選擇 **Immutable**。
6. 啟用 **Scan on push**；若 Console 將掃描移至 registry-level 設定，至少為這個 repository 啟用 basic scanning。
7. Encryption 保持預設 AES-256。
8. 建立後記下 Repository URI：

```text
<AWS_ACCOUNT_ID>.dkr.ecr.<AWS_REGION>.amazonaws.com/trade-analytics-ingestion
```

AWS Console 可建立 repository，但 Docker Image 仍需從本機 push。Repository 頁面可以選擇 **View push commands** 取得帳號與 Region 已代入的指令。[AWS ECR repository 建立文件](https://docs.aws.amazon.com/AmazonECR/latest/userguide/repository-create.html)

## 4. Push Image 到 ECR

以下三個 placeholder 必須替換：

```text
<AWS_ACCOUNT_ID>
<AWS_REGION>
<IMAGE_TAG>
```

`<IMAGE_TAG>` 使用不重複版本，例如 `phase2-20260829-1`；因為 repository 已啟用 immutable tags，相同 tag 不可再次 push。

登入 ECR：

```bash
aws ecr get-login-password --region <AWS_REGION> | \
  docker login \
    --username AWS \
    --password-stdin \
    <AWS_ACCOUNT_ID>.dkr.ecr.<AWS_REGION>.amazonaws.com
```

Tag：

```bash
docker tag \
  trade-analytics-ingestion:phase2 \
  <AWS_ACCOUNT_ID>.dkr.ecr.<AWS_REGION>.amazonaws.com/trade-analytics-ingestion:<IMAGE_TAG>
```

Push：

```bash
docker push \
  <AWS_ACCOUNT_ID>.dkr.ecr.<AWS_REGION>.amazonaws.com/trade-analytics-ingestion:<IMAGE_TAG>
```

ECR login token 有效時間有限，而且登入與 repository 必須使用相同 Region。[AWS ECR push 文件](https://docs.aws.amazon.com/AmazonECR/latest/userguide/docker-push-ecr-image.html)

回到 ECR Console，確認 image 顯示：

- 正確 tag。
- Image digest。
- Architecture／OS 符合 `linux/amd64`。
- Scan 沒有需要立即處理的 Critical findings。

## 5. 透過 IAM Console 建立 Lambda Execution Role

1. 進入 **IAM** → **Roles** → **Create role**。
2. **Trusted entity type** 選擇 **AWS service**。
3. **Use case** 選擇 **Lambda**。
4. 附加 AWS managed policy：`AWSLambdaBasicExecutionRole`。
5. Role name 輸入 `trade-analytics-ingestion-lambda-role`。
6. 建立 Role。
7. 進入該 Role → **Add permissions** → **Create inline policy** → **JSON**。
8. 貼上以下 policy，替換 `<RAW_BUCKET_NAME>`：

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadWriteComtradeRawPrefix",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject"
      ],
      "Resource": "arn:aws:s3:::<RAW_BUCKET_NAME>/un_comtrade/v2/*"
    },
    {
      "Sid": "RecognizeMissingObjectsInTradeBucket",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::<RAW_BUCKET_NAME>"
    }
  ]
}
```

Inline policy name 輸入 `TradeAnalyticsRawS3Access`。不要授予 `s3:*` 或整個帳號所有 bucket 權限。

`AWSLambdaBasicExecutionRole` 提供 CloudWatch Logs 所需權限；Lambda 存取 S3 則由上述最小權限 policy 提供。[Lambda execution role 文件](https://docs.aws.amazon.com/lambda/latest/dg/lambda-permissions.html)、[CloudWatch Logs 權限](https://docs.aws.amazon.com/lambda/latest/dg/monitoring-cloudwatchlogs.html)

若把 `RAW_PREFIX` 改成其他值，IAM Resource 也必須改成相同 prefix。

上述 ListBucket 採專案專用 bucket 的範圍，讓 GetObject 遇到尚不存在的 key 時能得到 404；缺少此權限可能是 403，不能一律當成不存在。共用 bucket 應另行評估列舉權限。Lambda 不需 DeleteObject 權限。

## 6. 透過 Lambda Console 建立 Function

1. 進入 **Lambda**，確認 Region 與 ECR 相同。
2. 選擇 **Create function**。
3. 選擇 **Container image**。
4. Function name 輸入 `trade-analytics-ingestion`。
5. 選擇 **Browse images**，挑選 ECR repository 與剛 push 的 tag／digest。
6. **Architecture** 選擇 **x86_64**。
7. 展開 **Permissions**，選擇 **Use an existing role**。
8. 選擇 `trade-analytics-ingestion-lambda-role`。
9. 建立 Function。

Container Image function 無法直接轉換成 ZIP function；需要改部署類型時必須建立另一個 Lambda。[AWS Lambda Container Image 文件](https://docs.aws.amazon.com/lambda/latest/dg/images-create.html)

建立後設定：

### General configuration

進入 **Configuration** → **General configuration** → **Edit**：

- Memory：`512 MB`。
- Timeout：先設 `3 min 0 sec`，依實際 API 重試與等待耗時調整。

### Environment variables

進入 **Configuration** → **Environment variables** → **Edit**：

| Key | Value |
|---|---|
| `RAW_BUCKET` | 實際 S3 bucket 名稱 |
| `RAW_PREFIX` | `un_comtrade` |

`COMTRADE_BASE_URL` 可省略；省略時使用 Phase 1 Preview endpoint。不要把 AWS access key 或 secret key 放進環境變數。

保留 `/HS` endpoint，H6 由回應驗證層限制。`RAW_PREFIX=un_comtrade`，程式會自動附加 v2，不要設成 `un_comtrade/v2`。

### Reserved concurrency

進入 **Configuration** → **Concurrency** → **Edit**：

- Reserved concurrency：`1`。

這可以降低 Preview API 限流及相同月份併發寫入的風險。

## 7. 在 Lambda Console 測試

進入 **Test**，建立 `partner-detail-202401` event：

```json
{
  "action": "ingest",
  "period": "202401",
  "cmd_code": "8542",
  "query_type": "partner_detail",
  "revision": 1,
  "run_id": "console-partner-202401"
}
```

成功回傳應包含：

```json
{
  "status": "success",
  "period": "202401",
  "query_type": "partner_detail",
  "row_count": 62,
  "checksum": "sha256:...",
  "data_uri": "s3://.../data.ndjson",
  "manifest_uri": "s3://.../manifest.json"
}
```

再建立 `world-total-202401` event：

```json
{
  "action": "ingest",
  "period": "202401",
  "cmd_code": "8542",
  "query_type": "world_total",
  "revision": 1,
  "run_id": "console-world-202401"
}
```

第一次執行預期 `status=success`。相同事件再次執行，若來源資料沒有改變，預期 `status=already_exists`，且不會覆蓋 S3 Raw objects。

## 8. 在 S3 Console 驗證

進入 Raw bucket，確認：

```text
un_comtrade/v2/hs_version=H6/cmd_code=8542/period=202401/
    ├── query_type=partner_detail/revision=1/
    │   ├── data.ndjson
    │   └── manifest.json
    └── query_type=world_total/revision=1/
        ├── data.ndjson
        └── manifest.json
```

檢查 `manifest.json`：

- `row_count` 與 Lambda response 相同。
- `checksum` 與 Lambda response 相同。
- `request_parameters.period` 是 `202401`。
- `request_parameters.reporterCode` 是 `842`。
- `source` 是 `UN Comtrade Preview API`。
- `schema_version=2.0.0`、`hs_version=H6`、`revision=1`，period／cmd_code／query_type 對應事件。
- 金額與重量的非 NULL 值以十進位字串保存，需重新計算金額及 data 的 SHA-256。
- 重跑前後 S3 Version ID 與 Last modified 不變；不把 ETag 當成 SHA-256。

## 9. 常見問題

### Lambda 顯示 Image architecture 不相容

重新確認本機 Image 是 `amd64`，Lambda architecture 是 `x86_64`。Lambda 不支援在同一 Image 使用 multi-architecture manifest。

### `AccessDenied` 寫入 S3

確認：

- `RAW_BUCKET` 完全符合 bucket 名稱。
- IAM policy resource 的 bucket 與 `un_comtrade/v2/*` prefix 正確。
- Lambda 使用的是 `trade-analytics-ingestion-lambda-role`。

### ECR Image 已更新，但 Lambda 還是舊版本

Lambda 建立或更新時會解析當下 image digest；只 push 新 tag 不會自動更新 Function。到 Lambda **Code** 頁面選擇 **Deploy new image**，重新選擇新 tag／digest。

### Log 暫時找不到

第一次 invocation 後，CloudWatch Log group 通常是 `/aws/lambda/trade-analytics-ingestion`；AWS 文件指出 Log 顯示可能有數分鐘延遲。

## 10. 本階段不執行的操作

- 不在 repository 保存 AWS credential。
- 不自動建立或刪除 AWS 資源。
- 不 push ECR，除非使用者另外明確要求並提供 AWS 登入環境。
- 不切換正式 Comtrade API，也不建立 Secrets Manager secret。
- 不建立 BigQuery、dbt 或 Airflow。
