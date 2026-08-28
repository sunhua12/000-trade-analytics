# U.S. Semiconductor Import Intelligence

Phase 1 提供可重用的 Python ingestion package 與 CLI，從 UN Comtrade Preview API 擷取美國半導體月度進口資料。

目前固定資料範圍：

- Reporter：美國，`reporterCode=842`。
- Frequency：月，`C/M/HS`。
- Flow：進口，`flowCode=M`。
- 預設期間：`202401`。
- 預設商品：HS `8542`。
- Query Type：`partner_detail`、`world_total`。

## 環境需求

- Python 3.11。
- 不需要 UN Comtrade API Key；Phase 1 使用公開 Preview API。

建立專案虛擬環境：

```bash
/opt/homebrew/bin/python3.11 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

所有 Python dependencies 都會安裝於專案的 `.venv`，不會安裝到全域 Python site-packages。

## 執行擷取

Partner Detail：

```bash
.venv/bin/python ingest.py \
  --period 202401 \
  --cmd-code 8542 \
  --query-type partner_detail
```

World Total：

```bash
.venv/bin/python ingest.py \
  --period 202401 \
  --cmd-code 8542 \
  --query-type world_total
```

自訂輸出根目錄：

```bash
.venv/bin/python ingest.py \
  --query-type partner_detail \
  --output-dir /tmp/trade-preview
```

成功時 CLI 只輸出 metadata：

```json
{
  "checksum": "sha256:...",
  "data_path": "data/preview/period=202401/query_type=partner_detail/data.ndjson",
  "manifest_path": "data/preview/period=202401/query_type=partner_detail/manifest.json",
  "period": "202401",
  "query_type": "partner_detail",
  "row_count": 62,
  "status": "success"
}
```

## 輸出結構

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

`data.ndjson` 保存 API 欄位名稱與資料型別；資料列會穩定排序，使相同資料能產生相同 checksum。

`manifest.json` 包含：

- Request parameters。
- SHA-256 checksum。
- Schema version 與 HS version。
- Row count。
- Primary value sum。
- Ingestion timestamp。

本機 `data/` 已由 `.gitignore` 排除。

## 測試

Unit Tests 不會呼叫真實網路：

```bash
.venv/bin/pytest tests/unit -q
```

執行 coverage：

```bash
.venv/bin/pytest tests/unit -q \
  --cov=trade_analytics.ingestion \
  --cov-report=term-missing \
  --cov-fail-under=85
```

手動執行真實 Preview API Integration Tests：

```bash
.venv/bin/pytest tests/integration/test_preview_api.py \
  --run-integration \
  -v
```

程式品質檢查：

```bash
.venv/bin/ruff format --check src tests ingest.py
.venv/bin/ruff check src tests ingest.py
.venv/bin/mypy src ingest.py
```

## 錯誤與重試

- HTTP `429` 與 `500／502／503／504` 最多執行 4 次 request。
- HTTP `401／403` 不重試。
- Connect／read timeout 與 transport error 會重試。
- `count >= 500` 視為 Preview API 疑似截斷，拒絕寫入不完整資料。
- CLI 與 Log 不輸出完整 response、Authorization header 或 credential。

## Preview API 限制

- Preview API 單次最多回傳 500 筆；本專案會偵測並拒絕疑似截斷結果。
- Preview response 的國家名稱、ISO、重量及部分描述欄位可能為 `null`。
- Phase 1 使用月度端點 `C/M/HS`，不使用年度端點 `C/A/HS`。
- 本階段不包含 AWS Lambda、Amazon S3、BigQuery、dbt 或 Airflow；這些屬於後續 Phase。

## 設計與實作計畫

- [Phase 1 Design](docs/superpowers/specs/2026-08-28-un-comtrade-preview-ingestion-design.md)
- [Phase 1 Implementation Plan](docs/superpowers/plans/2026-08-28-un-comtrade-preview-ingestion.md)
