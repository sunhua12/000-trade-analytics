# UN Comtrade Preview Ingestion Design

## 1. 目標

完成 Phase 1 的本機資料擷取模組，使用 UN Comtrade Preview API 取得美國半導體月度進口資料，並建立可供後續 AWS Lambda 重用的 Python package、CLI、資料契約與自動化測試。

本階段只處理本機擷取與本機檔案輸出，不建立 AWS Lambda、S3 或 BigQuery 資源。

## 2. 固定查詢範圍

| 參數 | 值 |
|---|---|
| API | UN Comtrade Preview API |
| Type | `C` |
| Frequency | `M` |
| Classification Search Code | `HS` |
| Reporter | `842`，美國 |
| Flow | `M`，進口 |
| Partner 2 | `0` |
| Customs | `C00` |
| Mode of Transport | `0` |
| 預設 Period | `202401` |
| 預設 Commodity Code | `8542` |

Base URL：

```text
https://comtradeapi.un.org/public/v1/preview/C/M/HS
```

Preview API 不使用 API Key。Client 介面仍與 endpoint 設定解耦，Phase 2 可替換正式 endpoint，而不改變 query、validation 與 storage 介面。

## 3. 方案選擇

採用「可重用 package ＋ CLI ＋兩種明確 query type」：

- `partner_detail`：查詢目標月份與商品碼的所有進口夥伴，驗證後排除 `partnerCode=0`。
- `world_total`：另外查詢同一月份與商品碼，明確指定 `partnerCode=0`。
- 兩種查詢分開產生資料檔與 manifest，保留獨立稽核軌跡。

不採用下列方案：

- 單一大型 `ingest.py`：HTTP、驗證、儲存互相耦合，不利 Lambda 重用及 Unit Test。
- 單次請求後拆出 World Total：請求成本較低，但無法證明 World 查詢是以 `partnerCode=0` 明確取得。

## 4. 元件與檔案

```text
src/trade_analytics/
├── __init__.py
└── ingestion/
    ├── __init__.py
    ├── client.py
    ├── exceptions.py
    ├── manifest.py
    ├── queries.py
    ├── schemas.py
    ├── service.py
    └── storage.py
ingest.py
tests/
├── fixtures/
│   └── comtrade_preview_response.json
└── unit/
    └── ingestion/
        ├── test_client.py
        ├── test_manifest.py
        ├── test_queries.py
        ├── test_schemas.py
        ├── test_service.py
        └── test_storage.py
pyproject.toml
.gitignore
README.md
```

### `queries.py`

負責：

- `QueryType` enum。
- `ComtradeQuery` 輸入模型。
- 建立 Preview API query parameters。
- 驗證 `period` 為合法 `YYYYMM`。
- 驗證 `cmd_code` 為 2、4 或 6 碼數字。

### `schemas.py`

負責：

- Pydantic response models。
- 對應 Preview API camelCase 欄位。
- 保留後續分析需要的交易欄位及估計旗標。
- 容許 API 中 description、weight、value 等 nullable 欄位。

### `client.py`

負責：

- 透過注入的 `httpx.Client` 呼叫 Preview API。
- 設定 connect／read timeout。
- 對 429、500、502、503、504 與網路 timeout 重試。
- 400、401、403 及其他非重試狀態立即失敗。
- 解析 top-level `count`、`data`、`error`。
- 當 `count >= 500` 時拋出 `ResponseTruncatedError`，避免保存疑似截斷資料。

重試總嘗試次數為 4 次：首次請求加 3 次重試。等待時間使用 exponential backoff；429 若包含可解析的 `Retry-After`，優先採用該值。

### `service.py`

負責：

- 協調 query、client、validation、storage 與 manifest。
- 驗證所有 rows：
  - `period` 等於 requested period。
  - `reporterCode=842`。
  - `flowCode=M`。
  - `cmdCode` 等於 requested cmd code。
- `partner_detail` 排除 `partnerCode=0`，並要求至少一筆實際夥伴資料。
- `world_total` 要求每筆均為 `partnerCode=0`，且最終恰好一筆。
- 檢查 grain 唯一性：`period × partnerCode × cmdCode`。
- 回傳 ingestion result metadata。

### `manifest.py`

負責：

- 產生 deterministic SHA-256 checksum。
- checksum 以 canonical NDJSON bytes 為輸入。
- 建立 manifest model。

Manifest：

```json
{
  "request_parameters": {},
  "checksum": "sha256:...",
  "schema_version": "1.0.0",
  "hs_version": "H6",
  "row_count": 62,
  "primary_value_sum": "123456.78",
  "ingested_at": "2026-08-28T00:00:00Z",
  "source": "UN Comtrade Preview API"
}
```

金額總和使用 `Decimal`，manifest 以字串輸出，避免 binary floating-point 誤差。

### `storage.py`

負責本機輸出：

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

寫入規則：

- NDJSON 每行一筆交易資料。
- Row 依穩定鍵排序後輸出，使 checksum 可重現。
- 先寫入同目錄 temporary file，再以 replace 完成單檔原子更新。
- data 與 manifest 均成功後才回傳成功結果。
- `data/` 加入 `.gitignore`。

### `ingest.py`

提供 CLI：

```bash
python ingest.py \
  --period 202401 \
  --cmd-code 8542 \
  --query-type partner_detail
```

參數：

- `--period`：預設 `202401`。
- `--cmd-code`：預設 `8542`。
- `--query-type`：`partner_detail` 或 `world_total`，必要參數。
- `--output-dir`：預設 `data/preview`。

成功時輸出精簡 metadata，不輸出完整 response。失敗時使用非零 exit code，且不得輸出 request headers。

## 5. 資料流

```text
CLI arguments
    → ComtradeQuery validation
    → Preview API parameter generation
    → HTTP request with retry
    → response schema parsing
    → query-type validation and filtering
    → duplicate-grain validation
    → canonical NDJSON serialization
    → checksum and manifest generation
    → local atomic writes
    → metadata summary
```

## 6. 錯誤模型

自訂 exceptions：

- `ComtradeError`：共同基底。
- `ComtradeRequestError`：HTTP 或網路錯誤。
- `ComtradeAuthenticationError`：401／403。
- `ComtradeResponseError`：API top-level error 或 schema 無效。
- `ResponseTruncatedError`：Preview response 達 500 筆上限。
- `EmptyDataError`：驗證後沒有資料。
- `DataContractError`：period、reporter、flow、commodity、partner 或 grain 不符合契約。

錯誤訊息包含 endpoint、period、query type 與 status code，但不包含完整 headers、credential 或完整 response body。

## 7. 測試策略

### Unit Test

所有 Unit Test 禁止連線真實網路：

- Query parameters：固定 reporter、flow 與 query-type partner 行為。
- Input validation：合法與非法 period／cmd code。
- Response parsing：nullable 欄位與 alias。
- HTTP retry：429、503、timeout 後成功。
- Non-retry：400、401、403 只嘗試一次。
- Truncation：`count=500` 拒絕處理。
- Contract：錯誤 period、reporter、flow、cmd code、World row 與重複 grain。
- Serialization：穩定排序、NDJSON 及 deterministic checksum。
- Storage：temporary write、輸出路徑與 manifest。
- Secret hygiene：Log 不包含假 Authorization value。

測試使用 `pytest`、`respx`、`tmp_path`、`caplog` 與固定 JSON fixture。

### Integration Test

Integration Test 預設不由一般 `pytest` 執行，透過 marker 明確啟用：

```bash
pytest -m integration --run-integration
```

驗證：

- 月資料 endpoint 可連線。
- `flowCode=M`。
- `period=202401`。
- response 未達截斷上限。
- Partner Detail 與 World Total 各自符合契約。

## 8. 品質門檻

- Python 3.11。
- Ruff lint／format 通過。
- mypy 通過。
- pytest 通過。
- `src/trade_analytics/ingestion` Unit Test coverage 至少 85%。
- Repository 不提交 `data/`、credential、cache 或 virtual environment。

## 9. Phase 1 完成條件

- CLI 可分別擷取 `partner_detail` 與 `world_total`。
- 本機產生 deterministic NDJSON 與 manifest。
- 429／503／timeout、non-retry errors、schema、empty、duplicate、truncation 測試通過。
- 真實 Preview API integration test 通過。
- README 記載安裝、執行及測試指令。
- 實作保持與 Preview endpoint 解耦，可在 Phase 2 切換正式 API。

