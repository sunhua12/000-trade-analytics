# Day 4：部署 Lambda，實際寫入 Amazon S3

| 項目 | 內容 |
|---|---|
| 對應計畫 | [20 天實作規格](trade-analytics-spec.md) 的 Day 4 |
| 前置條件 | [Day 3 計畫](day-03-learning-plan.md) 的契約、v2 路徑、精度與重跑測試完成 |
| 預計投入 | 約 3～4 小時；首次帳號與權限設定可能需要額外時間 |
| 核心目標 | 讓真實 Lambda 抓取單月明細與 World，寫入 S3，並驗證同事件重跑 |
| 今日交付物 | ECR image、Lambda／IAM／S3 設定、真實執行證據及 Day 4 日誌 |

2026-09-12 進度：本人確認 Console 部署與功能檢查通過，明細下載檔亦完成本機複驗，詳見 [部署紀錄](day04-deployment-record.md) 與 [學習日誌](learning-log.md)。目前總規格另要求 Terraform／remote state，本單日 Console 流程未涵蓋；IaC 與部署追溯證據仍待補。以下保留操作與驗收清單，實際結果以部署紀錄為準。

Day 3 已完成 revision 與 v2 路徑介面；部署時需重新建置包含本次修改的 image，不能將本計畫事件送給舊程式。

## 1. 今天要理解的流程

```text
本機程式 → Docker image → ECR 保存 image
                               ↓
                       Lambda 執行程式
                          ↓         ↓
                   UN Comtrade     S3 保存 data／manifest
                               ↓
                      CloudWatch 查看執行紀錄
```

| 元件 | 用途 |
|---|---|
| Docker image | 封裝程式與執行依賴 |
| ECR | 保存 Lambda 要執行的 image |
| Lambda | 接收事件，執行一次擷取 |
| IAM execution role | 決定 Lambda 可存取哪些 AWS 資源 |
| S3 | 保存資料與 Manifest |
| CloudWatch Logs | 查詢成功、失敗與執行時間 |

重點是能解釋「誰執行、誰授權、資料放哪裡、失敗去哪裡看」。今天不建立 BigQuery、Airflow、API Gateway 或 Function URL。

## 2. 部署前檢查

**預計時間：20～30 分鐘。**

- [ ] Day 3 的 mypy、Ruff 與單元測試通過。
- [ ] Lambda event 支援 revision，預設 1；固定接受 H6。
- [ ] 本機與 S3 的 v2 路徑、schema version 2.0.0 與重跑語意已實作。
- [ ] 本機 `.venv` 可用，Docker Desktop 已啟動。
- [ ] AWS CLI 登入的是本專案預定使用的帳號。
- [ ] 選定 AWS Region，確認預算金額與通知；預算通知不等於費用硬上限。

從專案根目錄執行：

```bash
docker version
aws sts get-caller-identity
git status --short
git rev-parse --short HEAD
```

如果 Day 3 未完成，先閱讀本文件及確認帳號環境；完成前置條件後再建置部署用 image。不要把舊路徑的成功寫入當成新版驗收通過。

記錄以下設定，先以已有且用途吻合的資源為優先，避免重複建立：

| 設定 | 值 |
|---|---|
| AWS 帳號／Region | 待填 |
| Raw bucket | 待填，全域唯一名稱 |
| ECR repository | `trade-analytics-ingestion`，或記錄既有名稱 |
| Lambda function | `trade-analytics-ingestion`，或記錄既有名稱 |
| Image tag／Git SHA | 待填；tag 每次部署唯一 |
| 是否含未提交程式變更 | 待填；若有，不能宣稱 image 完全對應該 SHA |

## 3. 建立 S3 與 ECR

**預計時間：20～30 分鐘。**

### S3

在 S3 Console 建立本專案專用 General purpose bucket：

- Region 與 Lambda 相同，簡化設定。
- Block Public Access 保持全部啟用。
- Object Ownership 採 Bucket owner enforced。
- Default encryption 使用 SSE-S3，避免本日增加 KMS 權限整合。
- Bucket Versioning 啟用，提供意外覆寫的復原能力；它不取代程式的 revision 與不覆写規則。
- 不必手動建立資料夾，第一次寫入時會產生 object keys。

### ECR

建立 Private repository，使用不重複的 immutable image tag，並啟用基本 image 掃描。ECR 與 Lambda 必須使用同一 Region。[AWS Lambda image 文件](https://docs.aws.amazon.com/lambda/latest/dg/python-image.html)

記錄 repository URI。後續指令的 `YOUR_ACCOUNT_ID`、`YOUR_REGION` 與 `YOUR_IMAGE_TAG` 均需先替換，不能原樣執行。

## 4. 設定 Lambda execution role

**預計時間：20～30 分鐘。**

在 IAM 建立供 Lambda 使用的 role，信任主體為 Lambda service，附加 `AWSLambdaBasicExecutionRole`，再加上以下 S3 inline policy。`YOUR_RAW_BUCKET` 必須替換。

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadWriteTradeV2Objects",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject"],
      "Resource": "arn:aws:s3:::YOUR_RAW_BUCKET/un_comtrade/v2/*"
    },
    {
      "Sid": "RecognizeMissingObjectsInTradeBucket",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::YOUR_RAW_BUCKET"
    }
  ]
}
```

本計畫使用專案專用 bucket；ListBucket 允許列出該 bucket 的 object 名稱，實際讀寫仍限於 v2 prefix。若使用共用 bucket，先重新評估列舉權限範圍，不直接套用。

ListBucket 在此有實際用途：程式先讀取 object 判斷是否存在；缺少此權限時，不存在的 key 可能回傳 403，而非可識別的 404。不要將所有 AccessDenied 視為「檔案不存在」。[AWS GetObject 權限說明](https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObject.html)

本機登入身分負責 push ECR 與部署；Lambda execution role 負責執行時讀寫 S3，兩者不同。不要把本機 AWS access key 放入 image 或 Lambda 環境變數。

## 5. 建置 image 並推送 ECR

**預計時間：30～45 分鐘。**

使用現有 [Dockerfile](../Dockerfile)，在專案根目錄建置：

```bash
docker buildx build --platform linux/amd64 --provenance=false --load -t trade-analytics-ingestion:day04 .
```

檢查 image：

```bash
docker image inspect trade-analytics-ingestion:day04 --format 'architecture={{.Architecture}} os={{.Os}} cmd={{json .Config.Cmd}}'
```

預期 architecture 為 `amd64`、OS 為 `linux`、CMD 指向 `trade_analytics.lambda_handler.handler`。Apple Silicon 上也依此建置；Lambda architecture 選 `x86_64`。`--provenance=false` 依 AWS 的 image 建置指引設定。[官方建置步驟](https://docs.aws.amazon.com/lambda/latest/dg/python-image.html)

登入、標記與推送，依序執行；repository 名稱若不同須一併替換：

```bash
aws ecr get-login-password --region YOUR_REGION | docker login --username AWS --password-stdin YOUR_ACCOUNT_ID.dkr.ecr.YOUR_REGION.amazonaws.com
```

```bash
docker tag trade-analytics-ingestion:day04 YOUR_ACCOUNT_ID.dkr.ecr.YOUR_REGION.amazonaws.com/trade-analytics-ingestion:YOUR_IMAGE_TAG
```

```bash
docker push YOUR_ACCOUNT_ID.dkr.ecr.YOUR_REGION.amazonaws.com/trade-analytics-ingestion:YOUR_IMAGE_TAG
```

回 ECR 確認 tag 與 digest，記錄 digest 作為實際部署身分。建置成功不代表 Lambda 可以執行，仍需後面的真實驗證。

## 6. 建立或更新 Lambda

**預計時間：20～30 分鐘。**

在 Lambda Console 建立 Container image function，或更新本專案既有的 container function，選擇剛推送的 image 與 execution role。

| 設定 | 本日設定 |
|---|---|
| Architecture | `x86_64` |
| Memory | 512 MB 起步，依執行結果調整 |
| Timeout | 180 秒起步；記錄實際耗時，並核對 client 重試與 timeout 的總時間 |
| Reserved concurrency | 1；若帳號配額無法設定，記錄限制，保持人工串行測試 |
| RAW_BUCKET | 實際 bucket 名稱 |
| RAW_PREFIX | `un_comtrade`；由 Day 3 程式附加 `v2`，避免重複 v2/v2 |
| COMTRADE_BASE_URL | 可省略，使用已驗證的 `/HS` 預設值 |
| VPC | 本 MVP 不連接自訂 VPC；若使用既有 VPC 設定，先確認可連外存取 API |
| Log level | 確認 application INFO 訊息可見，否則至少保留 invocation 結果與 request ID |

不要只推送 ECR 就假設 Lambda 已更新；在 Lambda 選 Deploy new image，核對實際解析的 digest。180 秒也不是所有重試情境必然足夠，若因 timeout 失敗，先查看實際等待與請求耗時再調整。

## 7. 真實執行兩類查詢與重跑

**預計時間：30～45 分鐘。**

在 Lambda Test 建立以下事件。此介面必須已於 Day 3 實作；H6 由程式預設接受規則控制。

### 夥伴明細

```json
{
  "action": "ingest",
  "period": "202301",
  "cmd_code": "8542",
  "query_type": "partner_detail",
  "revision": 1,
  "run_id": "day04-partner-202301"
}
```

### World Total

```json
{
  "action": "ingest",
  "period": "202301",
  "cmd_code": "8542",
  "query_type": "world_total",
  "revision": 1,
  "run_id": "day04-world-202301"
}
```

先依序執行各一次，保存結果，再依序重跑各一次。新位置首次預期 `success`；相同內容重跑預期 `already_exists`。若該位置已有相同資料，第一次即回傳 already_exists 也合理，需註明初始狀態。

資料應位於：

```text
s3://YOUR_RAW_BUCKET/un_comtrade/v2/
  hs_version=H6/cmd_code=8542/period=202301/
    query_type=partner_detail/revision=1/data.ndjson
    query_type=partner_detail/revision=1/manifest.json
    query_type=world_total/revision=1/data.ndjson
    query_type=world_total/revision=1/manifest.json
```

檢查重跑前後 Last modified 與 Version ID，確認沒有新增同內容的 S3 object version。若來源內容改變，預期 conflict；保留舊檔並調查，不能為了顯示成功直接覆寫。

另用非法 period `202413` 執行一次，應清楚失敗且不新增資料。這能驗證部署版本仍執行輸入檢查；不需要刪除真實檔案製造故障。

## 8. S3 實際檔案驗證

从 S3 Console 下載本次兩個 data 與 manifest 到新的本機驗證目錄，分別保留明細與 World，不覆寫 Day 2／3 資料。這些動作使用操作者身分，需具備相應讀取權限。

- [ ] Manifest 的月份、商品、H6、revision 與 schema version 符合 Day 3 契約。
- [ ] 實際非空 NDJSON 行數與 Manifest／Lambda 回傳筆數相同。
- [ ] 重新計算 data 的 SHA-256，與 Manifest／Lambda 回傳 checksum 相同。
- [ ] 以 Decimal 加總檔案金額，與 Manifest 合計相同。
- [ ] 同月份的明細合計與 World 比較，記錄差額。

macOS 可用以下指令計算 checksum，先替換檔案路徑：

```bash
shasum -a 256 /absolute/path/to/downloaded/data.ndjson
```

輸出雜湊與 Manifest 移除 `sha256:` 前綴後的值比對。S3 ETag 不當成 SHA-256 使用。

Day 2 的 202301 基準為明細 67 筆、World 1 筆，金額各為 2,799,575,181。這是歷史比較值；新格式 checksum 本來就可能不同，來源資料也可能修訂，不能把 Day 2 數字硬寫成永遠固定的驗收值。

## 9. 常見問題

| 現象 | 先檢查 |
|---|---|
| 第一次寫入就 AccessDenied | execution role、bucket、v2 prefix，以及缺少 key 的 ListBucket 權限 |
| image architecture／manifest 不相容 | amd64／x86_64 是否一致，以及建置選項 |
| revision 被當成多餘欄位 | Day 3 是否完成？Lambda 是否仍使用舊 digest？ |
| API 連線 timeout | API 狀態、請求等待時間、既有 VPC 連外設定 |
| 看不到 application INFO | logger 與 Lambda logging configuration；先查 invocation error、START／END／REPORT |
| 有 data 但沒有 manifest | 保存錯誤後重跑，驗證 Day 3 的部分檔案復原；不可假設成功 |
| checksum 與 Day 2 不同 | 區分序列化格式變更與來源修訂，核對本次 Manifest |

舊 [AWS Console 部署指南](aws-console-lambda-deployment.md) 可協助辨識 Console 操作，但其中舊路徑、事件、timeout 與 IAM 範例不直接作為 Day 4 驗收設定。依本計畫及 Day 3 最終介面同步更新。

## 10. 紀錄與完成條件

在 `docs/day04-deployment-record.md` 記錄實際資源設定、image digest、每次 request ID、時間、duration、status、兩個 S3 URI、row_count、checksum、重跑前後 Version ID 與檔案核對結果。此紀錄待實際執行後建立，不預填成功。

在 [學習日誌](learning-log.md) 新增 Day 4，連結部署紀錄，記下遇到的權限／容器問題與解法。記錄資源保留用途、預算通知及後續停用方式；本次 raw 檔留供 Day 5 入倉。

- [ ] Day 3 前置條件已通過，部署 image 對應到可追溯的程式版本。
- [ ] ECR、Lambda、IAM 與 S3 設定已保存。
- [ ] 真實 Lambda 能完成單月兩類查詢。
- [ ] 兩類資料的 data 與 manifest 均存在，筆數、checksum 與金額核對成功。
- [ ] 相同內容重跑不新增 object version、不改寫原資料。
- [ ] 非法輸入清楚失敗，不新增資料。
- [ ] 執行成功／失敗可透過 request ID 與紀錄追查。
- [ ] 部署紀錄與 Day 4 日誌完成，尚存限制已列明。

**完成標準：真實 AWS 上的擷取、S3 寫入與重跑均有證據。**本機測試通過或 image push 成功，仍不足以代表 Day 4 完成。
