# U.S. Semiconductor Import Intelligence

Phase 1 提供可重用的 Python ingestion package 與 CLI，從 UN Comtrade Preview API 擷取美國半導體月度進口資料。Phase 2 的第一個子階段將相同 package 封裝為 AWS Lambda Container Image，並支援寫入 Amazon S3 Raw Layer。

Day 3 已實作資料契約與 v2 儲存格式。真實 AWS 部署屬於 Day 4；目前 API 仍使用 `/HS`，但程式只接受 H6（HS2022）回應。H5 或混合分類會被拒絕，不會重新標記成 H6。

目前固定資料範圍：

- Reporter：美國，`reporterCode=842`。
- Frequency：月，`C/M/HS`。
- Flow：進口，`flowCode=M`。
- 預設期間：`202401`。
- 預設商品：HS `8542`。
- Query Type：`partner_detail`、`world_total`。
- 固定維度：`partner2Code=0`、`customsCode=C00`、`motCode=0`，均在回應中驗證。
- Revision：正整數，預設 `1`。必要金額必須有限且非負；World 必須大於 0。

## 環境需求

- Python 3.11。
- Docker Desktop，用於建置與本機驗證 Lambda Image。
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

明確保存來源修訂，使用新 revision：

```bash
.venv/bin/python ingest.py --period 202401 --query-type partner_detail --revision 2
```

revision 不送給 API，僅作為本地／S3 原檔身分；`expected_hs_version` 同樣不是 API 參數，MVP 固定為 H6。

成功時 CLI 只輸出 metadata：

```json
{
  "checksum": "sha256:...",
  "data_path": "data/preview/v2/hs_version=H6/cmd_code=8542/period=202401/query_type=partner_detail/revision=1/data.ndjson",
  "manifest_path": "data/preview/v2/hs_version=H6/cmd_code=8542/period=202401/query_type=partner_detail/revision=1/manifest.json",
  "period": "202401",
  "query_type": "partner_detail",
  "row_count": 62,
  "status": "success"
}
```

## 輸出結構

```text
data/preview/v2/hs_version=H6/cmd_code=8542/period=202401/
    ├── query_type=partner_detail/revision=1/
    │   ├── data.ndjson
    │   └── manifest.json
    └── query_type=world_total/revision=1/
        ├── data.ndjson
        └── manifest.json
```

`data.ndjson` 保存 API 欄位名稱，schema version 為 `2.0.0`。金額、重量與數量從 JSON 解析起使用 Decimal，輸出為無指數、無多餘尾零的十進位字串；NULL 保持 NULL。相同資料會穩定排序，使相同內容產生相同 checksum。

受影響欄位為 `primaryValue`、`cifvalue`、`fobvalue`、`netWgt`、`grossWgt`、`qty`、`altQty`。例如 `100.00` 存為 `"100"`，`-0.0` 存為 `"0"`。其他新出現的 JSON 小數也保存為十進位字串。BigQuery 載入時需要正規化為 NUMERIC，超出其精度範圍必須另行處理。Manifest 合計使用足夠的 Decimal 精度，避免預設 28 位有效數造成加總捨入。

舊版 `data/preview/period=...` 與 Day 2 檔案保留，不自動搬移；格式不同的 checksum 不應直接比較。

`manifest.json` 包含：

- Request parameters。
- SHA-256 checksum。
- Schema version 與 HS version。
- Row count。
- Primary value sum。
- Ingestion timestamp。
- Period、query type、commodity code 與 revision。

本機與 S3 採相同重跑規則：

| 狀態 | 行為 |
|---|---|
| 首次寫入 | `success` |
| 相同內容、相同 revision | `already_exists`；保留檔案及原始 ingested_at |
| 同 revision 內容或 Manifest 身分／合計不符 | `StorageConflictError`；不覆寫 |
| 只存在一個吻合的檔案 | 只補缺檔，回傳 `success` |
| 需要保存來源更正 | 操作者明確指定新 revision；保留舊版 |

Manifest 核對排除 ingested_at，其餘契約欄位都需符合本次資料。採單 writer 操作，兩個檔案不是整體原子交易；可以安全重跑補檔，不提供跨 writer 鎖定。重跑仍會呼叫 API，再比較內容。

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
  --cov-fail-under=90
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
.venv/bin/mypy .
```

Ruff 排除與專案無關的個人 `tests/TEST/` 字典轉換目錄；專案測試仍全部檢查。開發依賴包含 `boto3-stubs[s3]`，以便驗證真實 SDK 與測試替身的介面。

## Lambda Container Image

建置與 AWS Lambda `x86_64` 相同架構的 Image：

```bash
docker buildx build \
  --platform linux/amd64 \
  --provenance=false --load \
  -t trade-analytics-ingestion:phase2 \
  .
```

啟動 AWS Lambda Runtime Interface Emulator：

```bash
docker run \
  --platform linux/amd64 \
  --rm \
  -p 9000:8080 \
  -e RAW_BUCKET=local-smoke-only \
  trade-analytics-ingestion:phase2
```

另一個 Terminal 使用非法事件驗證 Handler 可以載入，而且不會呼叫 Comtrade 或 S3：

```bash
curl -sS -X POST \
  http://localhost:9000/2015-03-31/functions/function/invocations \
  -d '{"action":"unsupported","period":"202401","query_type":"partner_detail"}'
```

預期收到 Pydantic Validation Error。這個 smoke test 只驗證 Container 與 Handler 載入；成功寫入 S3 必須部署至具有 IAM Role 的 Lambda 後測試。

Lambda 成功事件格式：

```json
{
  "action": "ingest",
  "period": "202401",
  "cmd_code": "8542",
  "query_type": "partner_detail",
  "revision": 1,
  "run_id": "manual-test"
}
```

必要環境變數是 `RAW_BUCKET`；`RAW_PREFIX` 預設為 `un_comtrade`，`COMTRADE_BASE_URL` 預設使用 Phase 1 Preview endpoint。

S3 的新路徑為 `un_comtrade/v2/hs_version=H6/cmd_code=8542/period=202401/query_type=partner_detail/revision=1/`；`RAW_PREFIX` 不必額外附加 v2。

AWS S3、ECR、IAM 與 Lambda 的網頁操作請參考 [AWS Console 手動部署指南](docs/aws-console-lambda-deployment.md)。

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
- 目前 Lambda Image 仍使用 Preview API，尚未包含正式 API Key、BigQuery、dbt 或 Airflow。

## 本機 Streamlit Dashboard

Day 12 的 Dashboard 從 BigQuery 的 `trade_analytics_published.mart_us_semiconductor_supply_chain` 與 `publication_quality_summary` 唯讀取數。它提供日期、Partner 與 Top N 篩選、來源國／地區金額排名、月度趨勢及品質摘要；商品與分類固定為 `8542／H6`。需先有可查詢正式 Dataset 的 Google ADC 身分，以及執行 BigQuery job 的權限。

```bash
.venv-dbt/bin/python -m pip install -e '.[dashboard]'
.venv-dbt/bin/streamlit run dashboard.py
```

從專案根目錄執行。預設 GCP 專案為 `trade-analytics-508604`、location 為 `asia-northeast1`；可用 `TRADE_BQ_PROJECT` 與 `TRADE_BQ_LOCATION` 指定其他同結構環境。`TRADE_BQ_MAX_BYTES_BILLED` 預設 `1000000000`，限制每次 BigQuery 查詢的處理量；`TRADE_DASHBOARD_CACHE_TTL` 預設 `3600` 秒。畫面提供「重新讀取已發布資料」以清除快取。憑證由 ADC 提供，勿將金鑰放進 repository。

Dashboard 僅讀正式表與品質摘要，不讀 candidate／raw，也不修改資料。期間 World 金額按月只取一次，不能加總重複在夥伴列上的 `world_value`；來源國排名排除特殊代碼 490。對固定條件重跑唯讀核對：

```bash
.venv-dbt/bin/python scripts/verify_day12.py
```

實測結果與 BigQuery job IDs 見 [Day 12 查詢驗證](docs/evidence/day12-verification.json)，篩選畫面數值見 [UI 驗證](docs/evidence/day12-ui-verification.json)。圖表以浮點數顯示趨勢，精確金額核對使用 BigQuery `NUMERIC`；HHI、YoY 與深入解讀留待 Day 13。

## 設計與實作計畫

- [AWS Terraform 管理與接管流程](infrastructure/aws/README.md)
- [Terraform 實際接管驗證](docs/evidence/aws/terraform-adoption.md)

- [20 天規格](docs/trade-analytics-spec.md)
- [資料契約](docs/data-contract.md)
- [Day 3 學習計畫](docs/day-03-learning-plan.md)
- [學習日誌](docs/learning-log.md)

- [Phase 1 Design](docs/superpowers/specs/2026-08-28-un-comtrade-preview-ingestion-design.md)
- [Phase 1 Implementation Plan](docs/superpowers/plans/2026-08-28-un-comtrade-preview-ingestion.md)
- [Lambda Container and S3 Design](docs/superpowers/specs/2026-08-29-lambda-container-s3-ingestion-design.md)
- [Lambda Container and S3 Implementation Plan](docs/superpowers/plans/2026-08-29-lambda-container-s3-ingestion.md)

### 對帳與正式發布

Day 10 以固定候選批次、追加品質 audit 及交易式分區替換管理正式資料。一般 dbt build 不會發布；只有 PASS／WARN 才能更新正式表，FAIL 保留舊版。來源原檔查驗、操作命令、Dataset 與失敗復原方式見 [對帳與發布操作紀錄](docs/day10-quality-publish-record.md)，實際結果見 [驗收摘要](docs/evidence/day10-verification.md)。

### 24 個月回填

Day 11 已將 202301～202412 的兩類來源逐月載入、查驗、建置與發布；24 個月份皆為品質 PASS。實際操作採 S3 原檔驗證後的 Python／BigQuery 交易式 raw 載入，不沿用早期單月 Transfer PoC。指令、修訂 fixture、品質限制與證據見 [Day 11 執行紀錄](docs/day11-backfill-record.md)及[覆蓋清單](docs/evidence/day11/coverage.csv)。
