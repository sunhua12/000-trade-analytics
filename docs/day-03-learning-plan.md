# Day 3：將資料契約落實到程式

| 項目 | 內容 |
|---|---|
| 對應計畫 | [20 天實作規格](trade-analytics-spec.md) 的 Day 3 |
| 前置成果 | [Day 2 資料契約](data-contract.md) 與 [學習日誌](learning-log.md) |
| 預計投入 | 約 3～4 小時；依實際除錯時間記錄，不以時間到即視為完成 |
| 核心目標 | 拒絕不符合契約的資料，讓金額精度、資料路徑與重跑結果可預期 |
| 今日交付物 | 程式修正、相關測試、新格式說明與 Day 3 日誌 |

實作與驗收已完成，於 2026-09-11 完成文件收尾及離線複驗。真實 API smoke 於 2026-09-10 執行；詳見 [驗證紀錄](evidence/day03-verification.md) 與 [學習日誌](learning-log.md)。下列步驟保留供複習，完成狀態代表技術交付，不代表已測驗本人的理解程度。

## 1. 今天需要理解什麼？

| 概念 | 白話說明 | 本專案的例子 |
|---|---|---|
| 資料契約驗證 | 用程式拒絕不符合約定的資料 | 回應分類是 H5，就不能混入 H6 資料 |
| 冪等 | 相同資料重做，不產生額外有效版本或重複輸出 | 相同 S3 內容重跑回傳 `already_exists` |
| 資料精度 | 金額從讀取到保存都不被意外改變 | JSON 的十進位小數不能先轉成 float 再補救 |
| Revision | 明確保存來源修訂 | 同月份金額更新，寫入 revision 2，保留 revision 1 |
| Schema version | 標示檔案格式的版本 | 金額改成十進位字串後，讀取端需能辨識新格式 |

今天只深入閱讀正在修改的測試。不需要把全部測試、S3 SDK 或型別技巧一次讀完。

## 2. 延續 Day 2 的決策

- 保留 `/public/v1/preview/C/M/HS` endpoint；直接指定 `/H6` 的探測未成功。
- 只接受回應 `classificationCode=H6`，不把其他版本重新貼上 H6 標籤。
- 固定美國、月度進口、商品先使用 `8542`。
- 名稱與 ISO 缺值仍保留；特殊夥伴代碼 490 不刪除、不自行改名。
- 重量 NULL 保留；單位價值與國家映射由後續建模處理。
- Day 1／Day 2 的輸出作為歷史證據保存，新格式使用新目錄。

## 3. 第一組：補上資料契約驗證

**預計時間：45～60 分鐘。**

閱讀 [queries.py](../src/trade_analytics/ingestion/queries.py)、[service.py](../src/trade_analytics/ingestion/service.py) 與 [test_service.py](../tests/unit/ingestion/test_service.py)。

### 實作目標

1. Query 保存 `expected_hs_version`，MVP 預設且只允許 H6。它是接受資料的條件，不是已支援的 API 查詢參數。
2. Service 驗證每筆回應的分類，非 H6 直接失敗。
3. 補驗證 `freqCode=M`、`partner2Code=0`、`customsCode=C00`、`motCode=0`。
4. `primaryValue` 缺失、非有限數值或負值時拒絕；明細 0 值允許保留，World 金額必須 > 0。
5. 不因缺少重量、ISO 或名稱而拒絕整批金額資料。

先用一筆正常 fixture 改成錯誤版本，確認測試失敗，再補實作。其他固定欄位可使用參數化測試逐一驗證。

| 案例 | 預期 |
|---|---|
| 全部 H6，固定欄位正確 | 成功 |
| 全部 H5，或 H6／H5 混合 | 拒絕，不寫入 |
| freqCode、partner2Code、customsCode、motCode 任一不符 | 拒絕 |
| primaryValue 缺失、負值或非有限值 | 拒絕 |
| 明細 primaryValue=0／World primaryValue=0 | 明細保留／World 拒絕 |
| 重量、ISO、名稱為 NULL，含夥伴 490 | 合法核心資料保留 |

執行：

```bash
.venv/bin/pytest tests/unit/ingestion/test_queries.py tests/unit/ingestion/test_service.py -q
```

## 4. 第二組：保留金額精度

**預計時間：45～60 分鐘。**

閱讀 [client.py](../src/trade_analytics/ingestion/client.py)、[schemas.py](../src/trade_analytics/ingestion/schemas.py) 與 [manifest.py](../src/trade_analytics/ingestion/manifest.py)。

### 實作目標

- 從 JSON 解析開始把小數讀成 Decimal，例如使用 JSON decoder 的 `parse_float=Decimal`；不要先經過預設 float 解析。
- `primaryValue` 與其他金額欄位使用 Decimal；重量與數量亦使用可保留十進位精度的型別，NULL 仍保留。
- Manifest 直接加總 Decimal，不再用 `Decimal(str(float_value))` 作為精度保證。
- 新版 NDJSON 的 Decimal 值明確輸出為十進位字串，禁止轉回 float；相同值的表示方式需一致。
- Schema version 更新為 `2.0.0`，記錄哪些欄位改為字串，以及 BigQuery 正規化時需轉為 NUMERIC。
- 保留穩定欄位順序、row 排序與換行規則，確保相同資料產生相同 checksum。

### 精度測試重點

用原始 JSON 文字建立 HTTP fixture，例如金額 `123456789012345.123456789`，再驗證解析、模型、序列化與重新讀取後仍是相同十進位值。不要先用 Python float 建立 fixture，否則進入受測程式前可能已失真。

再測試兩筆金額的合計、NULL 重量、不同 row 順序下 checksum 一致。新格式的 checksum 可以與舊格式不同，但不得因此覆寫舊檔案。

```bash
.venv/bin/pytest tests/unit/ingestion/test_client.py tests/unit/ingestion/test_schemas.py tests/unit/ingestion/test_manifest.py -q
```

## 5. 第三組：修正儲存路徑與重跑行為

**預計時間：60～75 分鐘。**

閱讀 [storage.py](../src/trade_analytics/ingestion/storage.py)、[s3_storage.py](../src/trade_analytics/ingestion/s3_storage.py)、[ingest.py](../ingest.py) 與 [lambda_handler.py](../src/trade_analytics/lambda_handler.py)。

### 新路徑

本機與 S3 採用相同的 partition 層次：

```text
<root-or-prefix>/v2/
  hs_version=H6/cmd_code=8542/period=202401/
    query_type=partner_detail/revision=1/
      data.ndjson
      manifest.json
```

本機 `<root>` 可以是 `data/day03-preview`；S3 `<prefix>` 預設為 `un_comtrade`。版本與商品碼放入路徑，避免相同月份的不同商品共用檔案位置。路徑版本與 schema version 分別為 `v2` 與 `2.0.0`，不要與資料 revision 混淆。

### 實作目標

- CLI／Lambda event 支援正整數 `revision`，預設 1，傳遞至儲存與 Manifest。
- Manifest 除現有欄位外，明確保存 period、query_type、cmd_code、revision；hs_version 必須來自通過驗證的資料。
- 比較已有資料時，同時核對 checksum 與契約識別欄位，不只確認「可以解析 JSON」。
- 本機新格式與 S3 採相同的重跑語意；若本機需補 `status`，同步更新 CLI 回傳與測試。
- 來源內容改變時，由操作者指定新 revision；不自動覆寫、不自動增加版本。
- 不建立通用儲存框架。先沿用兩個 storage 類別，只共用確實重複且有需要的簡單函式。

| 情境 | 預期結果 |
|---|---|
| 首次寫入 | `success`，data 與 manifest 齊全 |
| 相同資料、同 revision 重跑 | `already_exists`，不重寫檔案或更新原 ingested_at |
| 同 revision、內容不同 | conflict，舊檔保留 |
| 只剩 data 或 manifest，且與預期吻合 | 只補缺檔 |
| 只剩一檔且內容／識別欄位不符 | conflict，不覆寫 |
| 指定 revision 2 | 使用新位置，revision 1 保留 |
| 相同月份、不同商品碼 | 位置不同；用 fixture 驗證即可 |

MVP 使用單 writer，不把兩檔寫入宣稱為整體原子交易。若沿用本機暫存檔替換，仍需處理一檔成功、一檔失敗的狀態。

```bash
.venv/bin/pytest tests/unit/ingestion/test_storage.py tests/unit/ingestion/test_s3_storage.py tests/unit/test_ingest_cli.py tests/unit/test_lambda_handler.py -q
```

## 6. 整體驗證與交付

**預計時間：30～45 分鐘。若超出當日工時，記錄未完成項目並接續，不跳過核心驗收。**

### 離線檢查

```bash
.venv/bin/mypy .
.venv/bin/ruff check src tests ingest.py
.venv/bin/ruff format --check src tests ingest.py
.venv/bin/pytest tests/unit -q --cov=trade_analytics.ingestion --cov-report=term-missing --cov-fail-under=90
```

只新增本次行為改變需要的測試；原本 68 個通過是起始基準，不是要求固定測試數量。既有 fixture 若需調整，保留原測試目的，不為了全綠直接刪除斷言。

### 本機 smoke test

先完成上述實作，再執行以下指令。執行前確認新程式會寫入 `v2` 路徑。

```bash
.venv/bin/python ingest.py --period 202301 --cmd-code 8542 --query-type partner_detail --output-dir data/day03-preview
.venv/bin/python ingest.py --period 202301 --cmd-code 8542 --query-type world_total --output-dir data/day03-preview
```

再次執行相同指令，若 API 內容未變，應回傳 `already_exists`；若變更則應回報 conflict。保留狀態、輸出 URI／路徑、筆數、checksum 與 schema version。真實金額若與 Day 2 不同，先調查來源修訂，不強行改成舊金額。

HTTP 測試使用 fixture 時，不代表真實 API 已通過。本日 S3 使用假 client 驗證重跑，真實 AWS 部署與寫入留待 Day 4。

### 文件同步

- 更新 [README](../README.md)：新路徑、revision、重跑回傳與 schema version。
- 更新 [資料契約](data-contract.md)：將實際完成的約束標記為已實作，記錄十進位字串格式與 0 值政策。
- 檢查 [AWS 部署指南](aws-console-lambda-deployment.md) 的 prefix、event、回傳及範例是否需要更新；僅改文件，不建立雲端資源。
- 在 [學習日誌](learning-log.md) 新增 Day 3：實際工時、設計理由、測試與 smoke 結果、已知限制。

## 7. 今天的完成檢查表

- [x] 已記錄維持 `/HS`、只接受 H6 的理由；本人可依第 2 節與資料契約複習。
- [x] 非 H6、固定維度不符與非法金額會被拒絕。
- [x] 精度測試從原始 JSON 文字開始，金額經解析與儲存後仍一致。
- [x] 新格式與 schema version 已定義，舊資料保留。
- [x] 路徑包含分類、商品、月份、查詢類型及 revision。
- [x] 相同資料重跑不改檔，不同內容不靜默覆寫。
- [x] 半成品可安全補齊，新增 revision 保留前版。
- [x] Ruff、mypy 與相關測試通過，覆蓋率符合目標。
- [x] 本機兩類資料 smoke 與重跑結果已記錄。
- [x] README、資料契約與 Day 3 日誌已更新。

**完成標準：能用測試及本機結果證明資料符合 H6 契約、精度保留、儲存互不衝突，且重跑不破壞原檔。**國家映射、HHI、完整回填與雲端部署不列入今天的完成條件。
