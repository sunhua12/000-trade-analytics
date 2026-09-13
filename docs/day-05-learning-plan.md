# Day 5：將 S3 單月資料載入 BigQuery

| 項目 | 內容 |
|---|---|
| 對應計畫 | [20 天實作規格](trade-analytics-spec.md) 的 Day 5 |
| 前置成果 | [Day 4 部署紀錄](day04-deployment-record.md)、S3 的 v2 data／manifest |
| 預計投入 | 約 3～4 小時；權限或替代方案除錯另記實際時間 |
| 核心目標 | 將 202301／8542／H6 的明細與 World 載入真實 BigQuery，能用 SQL 核對 |
| 今日交付物 | landing schema、raw DDL、單一載入方案與設定、查詢證據及 Day 5 日誌 |
| 目前狀態 | 待實作；本文件是學習計畫，不代表已建立或驗收雲端資源 |

Day 4 已由本人確認 Console 功能檢查通過，助理另複驗明細下載檔；World 原始證據、Terraform 與部署追溯仍待補。本日先補齊兩類來源的核對資料，IaC 缺口繼續保留於待辦，不因完成入倉而視為結案。

## 1. 今天要理解的流程

```text
S3：data.ndjson ＋ manifest.json
           ↓ 明確指定一個 data 檔，manifest 用來核對
BigQuery landing：保留來源欄位與十進位字串
           ↓ SQL 檢查筆數、金額、月份與分類
單月載入 PoC 完成
           ↓ Day 6
正規化 ＋ load audit ＋ raw MERGE ＋ 重跑驗證
```

| 概念 | 白話說明 | 本專案用途 |
|---|---|---|
| Dataset | 表格的管理範圍，包含位置與權限 | 分開 landing 與 raw |
| Landing | 先接住來源資料的表 | 保留 `primaryValue` 字串，檢查後再轉型 |
| Raw | 正規化後、最新已接受版本的資料 | 明細與 World 分成兩表 |
| Schema | 欄位名稱、型別及可否為空 | 避免金額被推斷成 FLOAT64 |
| Partition | 依指定欄位分割資料 | raw 使用月份起始日 |
| Cluster | 在分區內按欄位組織資料 | raw 使用夥伴碼與商品碼 |
| Load job／Transfer run | 一次雲端載入的執行識別 | 載入失敗時找到對應工作與來源 |

今天以兩類資料成功進入 landing 並可查詢為入倉 PoC 的完成點；raw 建立 schema 與空表。正式正規化、稽核表及 MERGE 在 Day 6 完成。

## 2. 準備來源與 GCP 環境

**預計時間：25～35 分鐘。**

先確認兩組來源，以下 `YOUR_RAW_BUCKET` 必須替換：

```text
s3://YOUR_RAW_BUCKET/un_comtrade/v2/hs_version=H6/cmd_code=8542/period=202301/query_type=partner_detail/revision=1/data.ndjson
s3://YOUR_RAW_BUCKET/un_comtrade/v2/hs_version=H6/cmd_code=8542/period=202301/query_type=world_total/revision=1/data.ndjson
```

- [ ] 取得兩個 data 及同目錄 manifest，分別計算 SHA-256、非空行數及 Decimal 金額合計。
- [ ] 確認 schema version 為 `2.0.0`，月份、商品、H6、query type 與 revision 一致。
- [ ] 保存來源完整 URI、checksum 與 `ingested_at`，後續與載入工作建立對應。
- [ ] 確認 GCP Project、計費與預算通知，啟用 BigQuery API；使用 Transfer 時另啟用 BigQuery Data Transfer API。
- [ ] 選定 Dataset location，landing 與 raw 使用同一位置，查詢與 job 設定也使用該位置。
- [ ] 確認操作者可建立 Dataset／table、執行 query／load job；Transfer 使用的身分另依官方權限要求設定。

建立開發用途的 `trade_landing` 與 `trade_raw` Dataset。若已有同用途 Dataset，沿用並記錄實際名稱。設定查詢處理量上限；預算通知不等於費用硬上限。

202301 的歷史基準為明細 67 筆、World 1 筆，兩者金額各為 2,799,575,181；本次驗收以實際來源 manifest 為準，不能用歷史值取代核對。

## 3. 設計 landing schema

**預計時間：30～40 分鐘。**

閱讀 [schemas.py](../src/trade_analytics/ingestion/schemas.py) 與 [資料契約](data-contract.md)，並檢查兩個實際 NDJSON 檔案的欄位聯集。模型允許額外欄位，不能只看 Python 宣告就假設 schema 完整。

建立兩張專用 PoC 表：

- `trade_landing.day05_partner_detail_202301_r1`
- `trade_landing.day05_world_total_202301_r1`

| 來源欄位 | Landing 型別 | 原因 |
|---|---|---|
| `period`、`cmdCode`、`classificationCode`、`flowCode` | STRING | 保留來源語意與商品碼 |
| `reporterCode`、`partnerCode`、`partner2Code`、`motCode` | INT64 | 與現有來源 JSON 整數一致 |
| `primaryValue`、`cifvalue`、`fobvalue` | STRING | v2 已保存為十進位字串 |
| `netWgt`、`grossWgt`、`qty`、`altQty` | STRING，可為 NULL | 避免載入階段失去精度 |
| 名稱、ISO、描述欄位 | STRING，可為 NULL | NULL 保留，後續建模再補維度 |
| 布林旗標、其餘整數 | BOOL／INT64，可為 NULL | 依來源契約明確宣告 |

表格只列重點，實作時需保存完整 JSON schema，涵蓋所有來源欄位；全為 NULL 的欄位也依契約指定型別。不要單靠 schema autodetect，也不要勾選忽略未知欄位來掩蓋 schema 不完整。NDJSON 每行是一個物件，載入格式選 newline-delimited JSON。[BigQuery JSON 載入文件](https://docs.cloud.google.com/bigquery/docs/loading-data-cloud-storage-json)

`run_id`、revision、checksum 與來源 URI 不一定存在於資料列中，先保存在本次載入紀錄；Day 6 再於正規化時補入 raw。不要假設 S3 路徑的 partition 名稱或檔名會自動成為欄位。

## 4. 完成單一載入方案

**預計時間：60～80 分鐘；前 40 分鐘作為 Transfer 可行性檢查點。**

### 優先方案：BigQuery Data Transfer Service

依 [官方 S3 Transfer 設定文件](https://docs.cloud.google.com/bigquery/docs/s3-transfer) 建立 Amazon S3 transfer。以兩個設定分別對應上述明細與 World 表，串行執行。

| 設定 | 本日選擇 |
|---|---|
| 來源範圍 | 每個設定只指定一個完整 `data.ndjson` URI |
| Destination | 該類型的專用 PoC landing 表 |
| File format | Newline-delimited JSON |
| Write disposition | `WRITE_TRUNCATE`，只用於本日專用 landing 表 |
| Max bad records | `0` |
| Ignore unknown values | `false` |
| 排程 | 使用手動執行；確認沒有非預期的週期排程 |

`WRITE_TRUNCATE` 會重載匹配檔案並覆寫目的表，可能產生 AWS 對外傳輸費用；來源必須限縮到該次檔案。官方設定需要 AWS access key ID／secret access key；使用專用讀取身分，依官方需求授權，憑證不寫入程式、Git 或驗證截圖。這與 GitHub 部署用的 OIDC 是不同用途。[設定及寫入行為](https://docs.cloud.google.com/bigquery/docs/s3-transfer)

依序執行明細與 World，等各次 run 成功後再查詢。記錄 Transfer config ID、run ID 與可取得的底層 load job ID。不要用「已建立 Transfer」代替「資料已載入」。

### 切換條件與替代方案：Python adapter

若檢查點仍有無法排除的權限、憑證或 Transfer 設定阻礙，記下原因與已花時間，依總規格切換 Python adapter；當日只保留選定方案作為 MVP 路徑。

替代方案的最小工作順序：

1. 在專案 `.venv` 加入並記錄 BigQuery client 依賴；AWS 使用既有 SDK 憑證鏈，GCP 使用 Application Default Credentials。
2. 從 S3 讀取指定 data 與 manifest，驗證身分、checksum、筆數及 Decimal 合計。
3. 將驗證後的 NDJSON bytes／file stream 透過 BigQuery `load_table_from_file` 上傳到專用 landing 表；明確設定 schema、JSON 格式與 `WRITE_TRUNCATE`。
4. 保存 job ID，等待 `job.result()` 完成再驗收。網路中斷時先依既有 job ID 查詢狀態；確認失敗後才記錄新的嘗試。
5. 補 checksum 不符時不提交 job、load 失敗不回報成功的測試，並保存真實雲端 job 證據。

BigQuery load job 的上傳介面見 [Python client 官方文件](https://docs.cloud.google.com/python/docs/reference/bigquery/latest/google.cloud.bigquery.client.Client#google_cloud_bigquery_client_Client_load_table_from_file)。不能把 `s3://` 直接當成 Cloud Storage URI 傳給一般 GCS load 範例。

兩種方案都需留下：`run_id`、period、query type、revision、來源 URI、checksum、載入識別、筆數、金額、狀態與錯誤原因。當日先保存紀錄，Day 6 再落實 `audit_ingestion_runs`。切換後同步保存依賴與設定，停用棄用的 Transfer 排程。

## 5. 用 SQL 驗證真實載入結果

**預計時間：30～40 分鐘。**

將 `YOUR_PROJECT` 替換成實際 Project ID，在 BigQuery 執行。此查詢以 landing 的字串金額為前提：

```sql
WITH loaded AS (
  SELECT 'partner_detail' AS query_type, period, cmdCode,
         classificationCode, partnerCode, primaryValue
  FROM `YOUR_PROJECT.trade_landing.day05_partner_detail_202301_r1`
  UNION ALL
  SELECT 'world_total', period, cmdCode,
         classificationCode, partnerCode, primaryValue
  FROM `YOUR_PROJECT.trade_landing.day05_world_total_202301_r1`
)
SELECT
  query_type,
  COUNT(*) AS row_count,
  COUNTIF(primaryValue IS NULL
          OR SAFE_CAST(primaryValue AS NUMERIC) IS NULL) AS invalid_amounts,
  COUNTIF(period IS NULL OR period != '202301'
          OR cmdCode IS NULL OR cmdCode != '8542'
          OR classificationCode IS NULL
          OR classificationCode != 'H6') AS invalid_identity,
  COUNTIF(partnerCode IS NULL) AS missing_partner,
  COUNTIF(partnerCode = 0) AS world_rows,
  SUM(CAST(primaryValue AS NUMERIC)) AS primary_value_sum
FROM loaded
GROUP BY query_type;
```

載入前先用 Decimal 確認金額可無損表示為 NUMERIC：至多 9 位有效小數、值在支援範圍內。`SAFE_CAST` 成功不保證沒有小數捨入；不要將它當作精度驗證。超出範圍時停止並記錄轉換決策，不靜默捨入。[NUMERIC 型別規格](https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/data-types#numeric_types)

- [ ] 兩組 row count 與各自 manifest 相同。
- [ ] `invalid_amounts`、`invalid_identity`、`missing_partner` 都為 0。
- [ ] 明細 `world_rows=0`；World 恰有 1 筆且 `world_rows=1`。
- [ ] 各自合計與 manifest 的 Decimal 合計完全相同。
- [ ] 額外抽查 NULL 重量／ISO 與夥伴 490，確認資料沒有被丟棄或改名。
- [ ] 再載入同一個明細檔，確認專用 landing 筆數不增加，保存第二次 run／job ID。

這次重跑只驗證 landing 寫入設定；raw grain 唯一、revision 保護與失敗復原仍屬 Day 6。

## 6. 建立 raw schema 與分區設計

**預計時間：20～30 分鐘。**

建立 `trade_raw.un_comtrade_partner_detail` 與 `trade_raw.un_comtrade_world_total` 空表。以下 DDL 為明細範例，World 使用相同欄位及實體設定，表名改為 `un_comtrade_world_total`：

```sql
CREATE TABLE IF NOT EXISTS
  `YOUR_PROJECT.trade_raw.un_comtrade_partner_detail` (
    period STRING,
    reporter_code STRING,
    partner_code STRING,
    flow_code STRING,
    cmd_code STRING,
    hs_version STRING,
    period_start_date DATE,
    primary_value NUMERIC,
    net_weight NUMERIC,
    quantity NUMERIC,
    ingested_at TIMESTAMP,
    source_file STRING,
    checksum STRING,
    run_id STRING,
    revision INT64
  )
PARTITION BY DATE_TRUNC(period_start_date, MONTH)
CLUSTER BY partner_code, cmd_code
OPTIONS (require_partition_filter = TRUE);
```

日期 `202301` 對應 `2023-01-01`；raw 的代碼統一轉成 STRING。`ingested_at` 使用來源 manifest 的擷取時間，載入工作時間另記於 audit。分區與 clustering 依 [BigQuery 分區表文件](https://docs.cloud.google.com/bigquery/docs/creating-partitioned-tables) 設定。

在 Console 核對兩張表的 schema、分區、cluster 與位置，保存 DDL。`IF NOT EXISTS` 不會修正已有表的 schema，若已有表必須比對差異。分區不會自動去重；有效 grain 為 `period_start_date × partner_code × cmd_code × hs_version`，Day 6 才實作其維護規則。

## 7. 紀錄、複習與完成條件

**預計時間：15～20 分鐘。**

實作時新增下列交付物；此清單不代表檔案已存在：

| 建議路徑 | 內容 |
|---|---|
| `infrastructure/gcp/landing-schema.json` | 兩類來源共用的完整明確 schema |
| `infrastructure/gcp/raw-tables.sql` | 兩張 raw 表的 DDL |
| `infrastructure/gcp/load-config.example.json` | 選定方案的非機密設定與佔位符 |
| `docs/day05-load-record.md` | 環境、方案決策、兩類來源與每次執行證據 |
| `docs/evidence/day05-verification.sql` | 實際使用的驗證查詢 |
| `docs/learning-log.md` | Day 5 實際時間、結果、問題與限制 |

載入紀錄需能回答「哪個檔案，透過哪次 job，進入哪張表，核對結果為何」。失敗也記錄來源、run／job ID、錯誤與處理結果，敏感設定遮蔽。

完成後用自己的話解釋：

1. 為什麼 landing 的金額先存 STRING，而 raw 使用 NUMERIC？
2. 為什麼 manifest 不能一起載入明細表？
3. 為什麼 landing 重載成功，還不能證明 raw 重跑安全？
4. 為什麼分區與 clustering 無法代替唯一性檢查？
5. 如果只有明細成功、World 失敗，如何找到失敗來源與工作？

- [ ] 明細與 World 都已載入真實 BigQuery，可成功查詢。
- [ ] 完整 landing schema 與兩張 raw 空表建立完成，DDL／設定已保存。
- [ ] 筆數、精度、金額、來源身分與 World 分離檢查通過。
- [ ] 同檔 landing 重載不累加，原始 S3 檔案保留。
- [ ] 明確選定一種載入方案，記錄決策、權限與執行識別。
- [ ] 驗證證據與學習日誌完成；尚未通過的項目明確列出。

若只有本機 fixture 或 schema 文件完成，真實入倉仍標示待驗收。下一步 Day 6 完成正規化、load audit、Manifest gate、raw MERGE，以及舊 revision 與來源刪列的重跑處理。
