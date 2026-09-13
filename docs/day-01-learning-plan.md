# Day 1：理解資料擷取流程與確認開發環境

| 項目 | 內容 |
|---|---|
| 對應計畫 | [20 天實作規格](trade-analytics-spec.md) |
| 預計投入 | 約 3～4 小時 |
| 核心目標 | 看懂主要資料流程與各模組的責任，成功執行一次本機擷取 |
| 今日交付物 | 測試結果、資料流程圖、本機輸出與環境檢查紀錄 |

## 1. 今天要看懂到什麼程度？

第一天先掌握成功流程，不需要一次理解整個專案的每一行。

讀每個模組時，回答三個問題：

1. **輸入是什麼？**
2. **做了哪些處理？**
3. **輸出是什麼？**

先能說明「執行一個指令後，資料如何從 API 變成檔案」。重試的實作細節、型別標註、依賴注入與測試技巧，留到第二輪閱讀再深入。

今天不需要重寫現有程式；雲端資源建立與部署安排在後續實作日。

## 2. 執行既有測試

**預計時間：30 分鐘。**

在終端機切換至專案目錄：

```bash
cd /Users/syunhua/Documents/10_Projects/000-trade-analytics
```

依序執行：

```bash
.venv/bin/pytest tests/unit -q
.venv/bin/ruff format --check src tests ingest.py
.venv/bin/ruff check src tests ingest.py
.venv/bin/mypy src ingest.py
```

| 指令 | 用途 |
|---|---|
| pytest | 驗證程式行為；這組單元測試不呼叫真實 API／AWS |
| Ruff format | 檢查排版格式是否一致 |
| Ruff check | 檢查程式碼規則與常見問題 |
| mypy | 檢查型別使用是否一致 |

2026-09-06 的先前驗證結果為 **68 個單元測試通過**，Ruff 與 mypy 也通過。這是參考基準，今天仍需記錄自己的實際結果。

若找不到 `.venv` 或相關指令，先依 [README](../README.md) 的環境需求與安裝步驟建立環境。若測試失敗，記錄失敗項目及錯誤訊息，先判斷原因，不直接修改預期值讓測試通過。

## 3. 沿著一次擷取流程閱讀程式

**預計時間：60～90 分鐘。**

### 第一輪：追蹤本機成功流程

```text
CLI：輸入月份、商品碼與查詢類型
    ↓
ComtradeQuery：驗證輸入、組合查詢參數
    ↓
ComtradeClient：呼叫 API、解析回應
    ↓
IngestionService：驗證資料、篩選 World 與檢查重複
    ↓
LocalStorage：協調序列化與檔案寫入
    ↓
data.ndjson ＋ manifest.json
    ↓
CLI：顯示筆數、檔案路徑與 checksum
```

這張圖表示資料處理順序；實際呼叫由 `ingest.py` 組裝 client，再透過 service 執行擷取，最後交給 storage。

| 順序 | 閱讀檔案 | 先找出什麼？ |
|---|---|---|
| 1 | [ingest.py](../ingest.py) | `main()` 如何讀參數？`run_ingestion()` 如何串接各模組？ |
| 2 | [queries.py](../src/trade_analytics/ingestion/queries.py) | 月份與商品碼如何驗證？兩種查詢的參數差在哪裡？ |
| 3 | [client.py](../src/trade_analytics/ingestion/client.py) | 在哪裡送出 HTTP request？成功後回傳什麼？ |
| 4 | [schemas.py](../src/trade_analytics/ingestion/schemas.py) | API JSON 如何對應到資料模型？先看月份、國家、商品與金額欄位 |
| 5 | [service.py](../src/trade_analytics/ingestion/service.py) | 如何確認回應符合請求？如何處理 World 與重複資料？ |
| 6 | [storage.py](../src/trade_analytics/ingestion/storage.py) | 輸出資料夾怎麼決定？如何寫入兩個檔案？ |
| 7 | [manifest.py](../src/trade_analytics/ingestion/manifest.py) | 資料如何序列化？checksum 與 Manifest 如何產生？ |

先看函式呼叫與重要欄位；遇到不熟悉的語法記下來，不必立刻中斷主線研究所有細節。

### 第二輪：對照 Lambda 入口

讀完本機流程後，查看 [lambda_handler.py](../src/trade_analytics/lambda_handler.py) 與 [s3_storage.py](../src/trade_analytics/ingestion/s3_storage.py)。

找出以下差異即可：

- 本機從 CLI 接收參數，Lambda 從 event 接收參數。
- 本機寫入檔案系統，Lambda 使用 S3 storage。
- 兩個入口如何重用 query、client 與 service？

## 4. 執行本機資料擷取

**預計時間：30～45 分鐘。**

以下指令會呼叫真實 Preview API，並寫入本機資料檔。現有版本使用公開 Preview API，不需要 Comtrade API Key。

擷取夥伴國明細：

```bash
.venv/bin/python ingest.py \
  --period 202401 \
  --cmd-code 8542 \
  --query-type partner_detail
```

擷取世界總計：

```bash
.venv/bin/python ingest.py \
  --period 202401 \
  --cmd-code 8542 \
  --query-type world_total
```

目前版本預設輸出結構：

```text
data/preview/
└── period=202401/
    ├── query_type=partner_detail/
    │   ├── data.ndjson
    │   └── manifest.json
    └── query_type=world_total/
        ├── data.ndjson
        └── manifest.json
```

這是現有程式的路徑；新版 spec 規劃的 `v2` 路徑尚待後續實作。

### 打開輸出檔案，逐項確認

- [ ] 明細與 World 分開存放。
- [ ] 資料的月份為 `202401`，商品碼為 `8542`。
- [ ] 明細沒有 `partnerCode=0`，World 只有世界總計。
- [ ] 實際資料列數與 Manifest 的 `row_count` 一致。
- [ ] 能找到 Manifest 的查詢參數、分類版本、金額合計、時間與 checksum。
- [ ] 能說明 NDJSON 每行一筆資料，與一般 JSON array 的差別。

不要假設筆數永遠與 README 範例相同，以當次 API 結果為準。若執行失敗，保存 HTTP 狀態或錯誤摘要，區分網路、來源服務與資料驗證問題；未成功時標記「未驗收」。

## 5. 盤點開發與雲端環境

**預計時間：20～30 分鐘。**

| 項目 | 今天確認的內容 | 狀態／備註 |
|---|---|---|
| Python | 專案 `.venv` 可用，測試可以執行 | 待填 |
| Docker | Docker Desktop 能啟動，`docker version` 顯示 Client 與 Server | 待填 |
| AWS | 能登入 Console，知道使用的 Region；列出是否已有 S3、ECR、Lambda | 待填 |
| GCP | 能登入 Console，知道 Project ID 與計費是否啟用 | 待填 |
| GitHub | 確認 repository 位置與帳號是否有推送權限 | 待填 |
| 雲端預算 | 記錄本專案可接受的預算，供後續建資源前設定限制 | 待填 |

今天只確認現況，不需要為了測試權限而額外建立資源或推送變更。紀錄中不要放入密碼、API Key 或雲端金鑰。

## 6. 整理學習紀錄

**預計時間：15～30 分鐘。**

在 `docs/learning-log.md` 建立今天的紀錄，可使用以下範本：

```markdown
## Day 1：理解資料擷取流程

- 實作日期：
- 實際投入時間：
- 單元測試結果：
- Ruff／mypy 結果：
- 本機擷取結果與輸出位置：
- 環境已具備項目：
- 尚缺環境與阻礙：

### 我理解的資料流程

用自己的話描述 CLI → query → client → service → storage。

### 四個問題

1. 為什麼要把 Partner Detail 與 World Total 分開？
2. 為什麼資料驗證放在 service，而不是全部放進 CLI？
3. Manifest 與 checksum 各自解決什麼問題？
4. 單元測試如何在不呼叫真實 API／AWS 的情況下驗證程式？

### 尚未理解的地方

記錄函式、語法或錯誤訊息，以及下一步要查什麼。
```

## 7. Day 1 完成檢查表

- [ ] 執行既有測試與品質檢查，保存自己的結果。
- [ ] 能指出程式入口，並說明主要模組的輸入、處理與輸出。
- [ ] 能用自己的話講完資料從 API 變成檔案的流程。
- [ ] 成功擷取單月明細與 World，查看資料檔及 Manifest。
- [ ] 知道 Lambda 與本機流程共用哪些程式。
- [ ] 記錄開發環境現況與尚缺項目。
- [ ] 完成今天的學習紀錄與待解問題。

**主要完成標準：理解一次成功擷取的完整流程，拿出本機執行結果，並清楚知道環境還缺什麼。**不以背下所有語法或逐行解釋整個專案作為今天的要求。
