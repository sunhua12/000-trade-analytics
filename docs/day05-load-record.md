# Day 5 載入紀錄

## 環境與目前狀態

| 項目 | 紀錄 |
|---|---|
| Project ID | `trade-analytics-508604`，本人提供 |
| Datasets | `trade_landing`、`trade_raw`，本人確認已建立 |
| Location | 兩者均為 `asia-northeast1`，本人提供 |
| S3 來源核對 | 本人確認 Day 5 步驟 1 已比對正確；本輪未重新讀取雲端來源 |
| Schema／SQL | 本人已建立 landing 表；截圖確認兩張 raw 表存在，分區／clustering 與取消分區到期均經截圖確認 |
| API／計費／Transfer 權限 | 尚未逐項保存驗證結果 |
| 載入狀態 | 明細與 World 已可查詢；本人確認明細重跑後仍為 67 筆，執行識別如下 |

## 已準備的檔案

- [landing-schema.json](../infrastructure/gcp/landing-schema.json)：依 TradeRecord 宣告建立 47 欄；Decimal 對應 STRING，NULL 保留。
- [landing-tables.sql](../infrastructure/gcp/landing-tables.sql)：建立兩張單月 landing 空表。
- [raw-tables.sql](../infrastructure/gcp/raw-tables.sql)：建立兩張 raw 空表，含日期分區與 clustering。
- [day05-verification.sql](evidence/day05-verification.sql)：載入後比對筆數、金額及來源身分。

本機驗證涵蓋 Day 4 明細下載檔 67 筆，以及 Day 3 明細 67 筆／World 1 筆，共 135 個資料列（含重複月份的歷史樣本）。所有來源 key 均被 schema 涵蓋，非 NULL JSON 值型別與 schema 一致；這不代表已查驗此次 S3 World 物件。DDL 依 [BigQuery 官方語法](https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#create_table_statement) 準備；後續本人提供 BigQuery 查詢成功與 raw 表清單截圖。

## 真實載入與驗證結果

依本人提供的 BigQuery 截圖與重跑回報記錄；助理未透過 GCP API 獨立讀取執行狀態。

| 類型 | 筆數 | 金額合計 | invalid_amounts | invalid_identity | missing_partner | world_rows |
|---|---:|---:|---:|---:|---:|---:|
| partner_detail | 67 | 2799575181 | 0 | 0 | 0 | 0 |
| world_total | 1 | 2799575181 | 0 | 0 | 0 | 1 |

明細與 World 合計差額為 0。本人確認重跑明細 Transfer 後仍為 67 筆；未將重跑本身等同於 raw MERGE 冪等驗收。兩張 raw 表的存在已由截圖確認，分區／clustering 與欄位詳細設定已由後續截圖核對。

## Transfer 與查詢識別

Project number：`898093147725`，來自本人提供的 run resource name；與 Project ID `trade-analytics-508604` 分開保存。

| Transfer 名稱 | Config ID |
|---|---|
| day05-world-total-202301 | `6ab919db-0000-2944-b907-34c7e9363257` |
| day05-partner-detail-202301 | `6ab86e9f-0000-2944-b907-34c7e9363257` |

明細首次：

```text
projects/898093147725/locations/asia-northeast1/transferConfigs/6ab86e9f-0000-2944-b907-34c7e9363257/runs/6ab87709-0000-2944-b907-34c7e9363257
```

明細重跑：

```text
projects/898093147725/locations/asia-northeast1/transferConfigs/6ab86e9f-0000-2944-b907-34c7e9363257/runs/6ab92bbe-0000-2944-b907-34c7e9363257
```

World 首次：

```text
projects/898093147725/locations/asia-northeast1/transferConfigs/6ab919db-0000-2944-b907-34c7e9363257/runs/6aa7fbb3-0000-2fb1-8bf4-34c7e91fd0db
```

筆數／金額驗證 Query Job ID：

```text
trade-analytics-508604:asia-northeast1.job_BR1B1pqmsdZptFv-yq_JVs67prOx
```

對應 SQL 見 [day05-count-amount-verification.sql](evidence/day05-count-amount-verification.sql)。此 ID 是 SELECT 查詢工作，不是 Transfer 底層 load job；也不對應 [day05-verification.sql](evidence/day05-verification.sql) 的完整欄位驗證。完整驗證結果已有截圖，未提供其 Job ID；不要求為補 ID 重跑成功查詢。

## 尚待收尾

1. 已完成：兩張 raw 表的 schema、月份分區、clustering、必填分區篩選器與永不到期設定符合 DDL。
2. 保存選定 S3 Transfer 的非機密設定、實際來源 URI 與 manifest checksum 對應；不保存 AWS keys。
3. 來源缺重量／ISO 與夥伴 490 的入倉抽查結果尚未另存。
4. 計費、預算與實際投入時間未逐項記錄。核心單月載入與圖中 SQL 驗證已通過，其餘項目不預填完成。

## Raw 詳細設定截圖確認

本人提供兩張 raw 表的詳細資訊：MONTH 分區、period_start_date、必填分區篩選器、依序 partner_code／cmd_code clustering、asia-northeast1，列數均為 0，符合本階段設計。

發現兩表 partition expiration 均為 60 天。歷史月份會依分區時間判斷到期，不從載入日重新計算 60 天；因此在 Day 6 寫入前需移除期限。原 DDL 未明確覆寫分區到期設定，是準備流程的缺口；可能繼承 Dataset 預設，尚未查驗來源。已更新 raw-tables.sql，明確指定 NULL 並提供 ALTER 修正既有表。後續本人已執行修正並提供截圖確認成功。表格本身「永不到期」不表示分區不會到期。

### 2026-09-15：取消到期設定確認

本人提供兩張更新後截圖，均顯示「分區永不過期」，MONTH／period_start_date、必填分區篩選器及 partner_code／cmd_code clustering 保持正確，列數均為 0。截圖顯示實際上次修改時間為 2026-09-14 21:54:49（明細）與 21:54:50（World），UTC+8；本節日期為確認日期。此項已驗收，不需重建表或重跑 Transfer。Dataset 預設期限未獨立確認，不能推論其他新表也永不到期。
