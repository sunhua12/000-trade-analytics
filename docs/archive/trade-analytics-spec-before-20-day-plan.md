# U.S. Semiconductor Import Intelligence & Supply Chain Resilience Platform

## 工程實作規格

| 文件欄位 | 內容 |
|---|---|
| 專案名稱 | U.S. Semiconductor Import Intelligence & Supply Chain Resilience Platform |
| 文件類型 | MVP Engineering Specification |
| 主要語言 | Python、SQL |
| 資料來源 | UN Comtrade API、UN M49、USITC DataWeb／HTS |
| 雲端服務 | AWS Lambda、Amazon S3、Google BigQuery、Google Cloud Run |
| 排程與建模 | Apache Airflow、Astronomer Cosmos、dbt Core |
| 分析介面 | Streamlit |

---

## 1. 專案目標

建立一套可重跑、可稽核且具備資料品質監控的美國半導體進口分析平台，定期擷取 UN Comtrade 月資料，分析來源國結構、進口市占率、單位價格及供應鏈集中度。

平台最終需提供：

- 美國半導體月度進口明細。
- 各來源國進口金額、重量、單位價格及市占率。
- 供應鏈集中度 HHI。
- 夥伴國合計與 World Total 的對帳結果。
- 可互動查詢的 Streamlit Dashboard。
- 每月自動更新及指定期間歷史回填能力。

## 2. MVP 範圍

### 2.1 納入範圍

- Reporter 固定為美國：`reporterCode=842`。
- Flow 固定為進口：`flowCode=M`。
- Frequency 固定為月：`frequency=M`。
- 固定一個明確的 HS Classification Version。
- 商品範圍包含 HS `8542` 與專案指定的 6 碼細項。
- 分開擷取 Partner Detail 與 World Total。
- 歷史回填範圍預設為 `202001～202412`；正式執行前可調整。
- BigQuery Mart、Streamlit Dashboard、Airflow 月度排程及 CI。

### 2.2 暫不納入範圍

- 即時或分鐘級資料流。
- 自動交易或投資建議。
- 多國 Reporter。
- 完整 USITC 關稅模擬引擎。
- 生產級多區域災難復原。

## 3. 核心設計原則

1. 每個擷取工作只處理一個 `period × query_type`。
2. API Key 不得寫入 Git、Log、XCom、S3 Raw 或 Manifest。
3. S3 Raw 資料不可變；相同輸入重跑時必須具有可預期結果。
4. XCom 只傳遞 URI、period、row count、checksum 等 metadata。
5. Partner Detail 與 World Total 分開儲存及載入。
6. 市占率以 World Total 為主要分母。
7. HHI 僅使用實際夥伴國，排除 World 與區域／群組代碼。
8. Unit Test 不連線至真實 AWS、GCP 或 UN Comtrade。
9. 真實外部服務測試歸類為 Integration Test 或 End-to-End Test。
10. 所有資源名稱、版本及重要閾值應由設定檔或環境變數控制。

## 4. 建議目錄結構

```text
000-trade-analytics/
├── src/
│   └── trade_analytics/
│       ├── config.py
│       ├── ingestion/
│       │   ├── client.py
│       │   ├── queries.py
│       │   ├── schemas.py
│       │   ├── rate_limit.py
│       │   ├── storage.py
│       │   ├── manifest.py
│       │   └── handler.py
│       ├── metrics/
│       │   ├── unit_value.py
│       │   ├── market_share.py
│       │   └── reconciliation.py
│       └── dashboard/
│           ├── queries.py
│           └── transforms.py
├── dags/
│   ├── trade_monthly.py
│   ├── trade_backfill.py
│   └── trade_pipeline/
│       ├── alerts.py
│       ├── availability.py
│       ├── periods.py
│       └── task_groups.py
├── dbt/
│   ├── dbt_project.yml
│   ├── models/
│   │   ├── staging/
│   │   ├── intermediate/
│   │   └── marts/
│   ├── macros/
│   ├── seeds/
│   └── tests/
├── app/
│   ├── app.py
│   └── pages/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   ├── dags/
│   └── fixtures/
├── infrastructure/
│   ├── airflow/
│   ├── aws/
│   └── gcp/
├── scripts/
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── requirements.txt
├── .env.example
└── README.md
```

---

# Phase 1：API PoC 與資料契約

## 1.1 目標

完成 UN Comtrade API 的本機擷取程式，確認查詢參數、回應格式、限流行為與資料契約，產出可供後續 Lambda 與 S3 共用的 Python package。

## 1.2 使用工具

| 類型 | 工具 | 用途 |
|---|---|---|
| Runtime | Python 3.11 | 本機與 Lambda 共用執行版本 |
| HTTP Client | `httpx` | 呼叫 API、設定 timeout 及連線池 |
| Retry | `tenacity` | 429／503 指數退避與重試 |
| Validation | Pydantic | API response 與 Manifest Schema Validation |
| Data | `orjson` 或 Python `json` | JSON／NDJSON 序列化 |
| 設定 | `pydantic-settings` | 環境變數及本機設定管理 |
| 測試 | `pytest`、`pytest-cov` | Unit Test 與覆蓋率 |
| HTTP Mock | `respx` | Mock `httpx` API response |
| 品質 | Ruff、mypy | Lint、format 與型別檢查 |

## 1.3 實作項目

### API Query

固定參數：

```text
reporterCode=842
flowCode=M
frequency=M
partner2Code=0
customsCode=C00
motCode=0
```

建立兩種查詢：

| Query Type | partnerCode | 說明 |
|---|---:|---|
| `partner_detail` | 實際夥伴國集合或 API 支援的明細查詢值 | 取得各夥伴國資料 |
| `world_total` | `0` | 取得世界總計 |

輸入資料模型：

```json
{
  "period": "202401",
  "query_type": "partner_detail",
  "hs_version": "<FIXED_HS_VERSION>",
  "cmd_codes": ["8542"]
}
```

輸出 metadata：

```json
{
  "period": "202401",
  "query_type": "partner_detail",
  "row_count": 100,
  "primary_value_sum": 123456.78,
  "checksum": "sha256:...",
  "schema_version": "1.0.0"
}
```

### Retry 與錯誤分類

- `429`：讀取 `Retry-After`；不存在時採 exponential backoff。
- `500／502／503／504`：最多重試 3 次。
- `400／401／403`：不重試，立即失敗。
- Connect timeout／read timeout：最多重試 3 次。
- 每次 request 必須設定 connect 與 read timeout。
- Log 不得包含 API Key 或完整 Authorization Header。

### 資料檢查

- 回應 period 必須等於 requested period。
- Reporter 必須為 `842`。
- Flow 必須為 `M`。
- `partner_detail` 不得包含 World row，或在標準化時明確移除。
- `world_total` 必須只包含 `partnerCode=0`。
- 檢查必要欄位、資料型別及空資料。
- 檢查 grain 重複：`period × partner_code × cmd_code`。
- 若單次回傳達 API 上限，標記為疑似截斷並依商品碼拆分重取。

## 1.4 Unit Test 方法

所有測試均使用固定 fixture，不呼叫真實 API。

| 測試檔 | 測試案例 | 方法 | 預期結果 |
|---|---|---|---|
| `test_queries.py` | Partner Detail 參數 | 比對產生的 query dict | 固定參數與 period 正確 |
| `test_queries.py` | World Total 參數 | 輸入 `world_total` | `partnerCode=0` |
| `test_client.py` | HTTP 200 | `respx` 回傳 fixture | 解析成 Pydantic model |
| `test_client.py` | HTTP 429 | 依序回傳 429、200 | 執行重試後成功 |
| `test_client.py` | HTTP 503 | 依序回傳 503、200 | 執行指數退避後成功 |
| `test_client.py` | HTTP 401 | Mock 401 | 不重試並拋出認證錯誤 |
| `test_client.py` | Timeout | Mock timeout exception | 在上限內重試 |
| `test_schemas.py` | 缺少必要欄位 | 刪除 fixture 欄位 | Validation Error |
| `test_schemas.py` | period 不一致 | 修改 response period | Validation Error |
| `test_schemas.py` | 空資料 | 回傳空 list | 依設定回傳 Not Available 或失敗 |
| `test_schemas.py` | 重複 grain | 建立重複 rows | 驗證失敗 |
| `test_manifest.py` | Checksum 穩定性 | 相同內容計算兩次 | checksum 相同 |
| `test_logging.py` | Secret 遮罩 | 使用假 API Key 執行錯誤流程 | `caplog` 不含 Key |

測試指令：

```bash
pytest tests/unit/ingestion -q
pytest tests/unit/ingestion --cov=trade_analytics.ingestion --cov-report=term-missing
ruff check src tests
mypy src
```

## 1.5 Integration Test

- 使用測試 API Key 呼叫單一月份與單一 HS Code。
- 僅在本機手動或受保護的 CI job 執行。
- 驗證 Partner Detail 與 World Total 均有資料。
- 將實際 response 去識別化後保存成 Contract Test fixture。

## 1.6 交付物

- `src/trade_analytics/ingestion/`。
- API response Pydantic models。
- 測試 fixtures。
- `.env.example`，只列變數名稱，不含值。
- API Contract 文件。

## 1.7 驗收標準

- 單一 period 的兩種 query 均可成功取得資料。
- 429／503／timeout 測試通過。
- Secret 不出現在 Log。
- Unit Test 覆蓋率至少 85%。
- Ruff 與 mypy 通過。

---

# Phase 2：AWS Lambda、S3 與 BigQuery Raw

## 2.1 目標

將 Phase 1 擷取程式部署為 AWS Lambda，寫入不可變 S3 Raw Layer，並透過 BigQuery Data Transfer Service 載入 BigQuery Raw Dataset。

## 2.2 使用工具

| 類型 | 工具 | 用途 |
|---|---|---|
| Compute | AWS Lambda Container Image | 執行單一 period 擷取 |
| Registry | Amazon ECR | 保存 Lambda Image |
| Secret | AWS Secrets Manager | 保存 Comtrade API Key |
| Storage | Amazon S3 | Raw NDJSON／Parquet 與 Manifest |
| AWS SDK | `boto3` | Secrets Manager 與 S3 操作 |
| Warehouse | Google BigQuery | Raw Dataset 與分區表 |
| Transfer | BigQuery Data Transfer Service for Amazon S3 | S3 跨雲載入 BigQuery |
| IaC | Terraform 或 AWS SAM | 建立雲端資源；MVP 擇一 |
| AWS Mock | `moto` | Unit Test Mock S3／Secrets Manager |
| Container Test | Docker | Lambda Image 本機測試 |

## 2.3 S3 儲存規格

```text
s3://<raw-bucket>/un_comtrade/
└── period=202401/
    ├── query_type=partner_detail/
    │   ├── data.ndjson
    │   └── manifest.json
    └── query_type=world_total/
        ├── data.ndjson
        └── manifest.json
```

Manifest 必要欄位：

```json
{
  "request_parameters": {},
  "checksum": "sha256:...",
  "schema_version": "1.0.0",
  "hs_version": "<FIXED_HS_VERSION>",
  "row_count": 100,
  "primary_value_sum": 123456.78,
  "ingested_at": "2026-08-28T00:00:00Z",
  "source": "UN Comtrade"
}
```

### 冪等策略

- Object key 由 `period` 與 `query_type` 決定。
- 若 data 與 manifest 已存在且 checksum 驗證成功，回傳 `already_exists`。
- 若只存在其中一個檔案，視為不完整執行並重新產生。
- 預設不得靜默覆蓋 checksum 不同的 Raw 資料。
- 需要更正資料時，以 `revision=<n>` 或獨立 reprocess policy 保存版本。

## 2.4 Lambda 介面

輸入：

```json
{
  "action": "ingest",
  "period": "202401",
  "query_type": "partner_detail",
  "run_id": "manual__2026-08-28T00:00:00Z"
}
```

輸出：

```json
{
  "status": "success",
  "period": "202401",
  "query_type": "partner_detail",
  "s3_uri": "s3://.../data.ndjson",
  "manifest_uri": "s3://.../manifest.json",
  "row_count": 100,
  "checksum": "sha256:..."
}
```

Lambda 設定：

- Reserved concurrency：`1`。
- API request rate limit：在程式內限制；Airflow Pool 只限制 task concurrency。
- Structured logging 欄位：`run_id`、`period`、`query_type`、`row_count`、`primary_value_sum`、`request_duration`。
- Lambda execution role 採最小權限。

## 2.5 BigQuery Raw 規格

Dataset：`raw_dataset`

資料表：

- `un_comtrade_partner_detail`
- `un_comtrade_world_total`

必要欄位：

- `period`：STRING，格式 `YYYYMM`。
- `period_start_date`：DATE，分區欄位。
- `reporter_code`：STRING。
- `partner_code`：STRING。
- `flow_code`：STRING。
- `cmd_code`：STRING。
- `primary_value`：NUMERIC。
- `net_weight`：NUMERIC。
- `quantity`：NUMERIC。
- `ingested_at`：TIMESTAMP。
- `source_file`：STRING。

BigQuery 設定：

- Partition：`period_start_date`。
- Cluster：`partner_code`、`cmd_code`。
- S3 Transfer 使用 period prefix，避免每次掃描整個 bucket。
- 載入策略需明確設定為 append、truncate partition 或 staging 後 `MERGE`；MVP 建議 staging 後 `MERGE`。

## 2.6 Unit Test 方法

| 測試檔 | 測試案例 | 方法 | 預期結果 |
|---|---|---|---|
| `test_handler.py` | 合法事件 | Mock client 與 storage | 回傳成功 metadata |
| `test_handler.py` | 非法 period | 輸入 `202413` | Validation Error |
| `test_handler.py` | 不支援 query type | 輸入未知值 | Validation Error |
| `test_storage.py` | S3 寫入 | 使用 `moto` | data 與 manifest 路徑正確 |
| `test_storage.py` | 已存在相同 checksum | 預先建立 objects | 回傳 `already_exists` |
| `test_storage.py` | checksum 衝突 | 預先建立不同內容 | 拒絕靜默覆蓋 |
| `test_storage.py` | 半成品狀態 | 只建立 data | 重新產生完整輸出 |
| `test_secrets.py` | 讀取 Secret | `moto` 建立假 secret | 正確取得假 Key |
| `test_manifest.py` | Manifest Schema | 驗證 fixture | 所有必要欄位存在 |
| `test_bq_schema.py` | BigQuery Schema | 比對 schema JSON | 欄位、partition、cluster 正確 |

測試指令：

```bash
pytest tests/unit/lambda tests/unit/storage -q
docker build -t trade-ingestion:test .
```

## 2.7 Integration Test

- 使用測試 bucket 執行一次 Lambda。
- 驗證 S3 data 與 manifest 同時存在。
- 觸發一次 S3 Transfer run。
- 查詢 BigQuery staging／raw，核對 row count 與 `primary_value_sum`。
- 再執行相同事件，確認不產生重複資料。

## 2.8 交付物

- Lambda Dockerfile。
- Lambda handler。
- S3 bucket／policy。
- Secrets Manager secret reference。
- BigQuery Dataset／table schema。
- S3 Transfer configuration。
- IaC 定義與部署說明。

## 2.9 驗收標準

- Lambda 單一事件可在限制時間內完成。
- S3 data 與 manifest checksum 一致。
- 相同事件重跑不重複寫入。
- BigQuery row count 與 manifest 相符。
- AWS／GCP credential 不存在於 repository。

---

# Phase 3：dbt 維度建模與指標計算

## 3.1 目標

將 BigQuery Raw 資料轉換為一致、可測試且可供分析的 Staging、Intermediate 與 Mart models。

## 3.2 使用工具

| 類型 | 工具 | 用途 |
|---|---|---|
| Transformation | dbt Core、`dbt-bigquery` | SQL 模型與資料測試 |
| Warehouse | Google BigQuery | 執行轉換與保存 models |
| Package | `dbt-utils` | 通用 tests 與 macros |
| SQL Quality | SQLFluff | dbt SQL lint |
| Unit Test | dbt Unit Tests | 固定輸入資料驗證 SQL 邏輯 |
| Fixture | dbt seeds | 國家、HS Code 及測試資料 |

## 3.3 Model 規格

### Staging

- `stg_un_comtrade__partner_trades`
- `stg_un_comtrade__world_totals`
- `stg_usitc__tariff_rates`
- `stg_un__country_m49`

責任：

- snake_case 命名。
- 型別轉換。
- `YYYYMM` 轉為 `period_start_date`。
- 空字串轉 `NULL`。
- 依明確 grain 去重。
- 保存來源 metadata。

### Intermediate

- `int_semiconductor_imports_enriched`
- `int_hs_code_crosswalk`
- `int_unit_values_calculated`
- `int_partner_market_share`
- `int_market_concentration_hhi`

計算規則：

```text
unit_value_usd_per_kg = primary_value / net_weight
```

- 僅在 `net_weight > 0` 時計算。
- `net_weight <= 0` 或 `NULL` 時回傳 `NULL`，不得除以零。

```text
market_share = partner_primary_value / world_primary_value
```

- 分母使用相同 `period × cmd_code` 的 World Total。
- 分母為 `0` 或 `NULL` 時回傳 `NULL`。

```text
HHI = SUM(POWER(market_share * 100, 2))
```

- HHI 採 `0～10,000` 尺度。
- 僅使用實際國家。
- 排除 World、Unknown、區域與經濟群組 aggregate codes。

### Dimensions／Facts／Marts

- `dim_countries`
- `bridge_country_groups`
- `dim_hs_codes`
- `fct_monthly_semiconductor_imports`
- `mart_us_semiconductor_supply_chain`

Fact grain：

```text
period_start_date × partner_code × cmd_code
```

Mart 必要指標：

- 進口金額。
- Net Weight。
- 單位價格。
- Market Share。
- 月增率。
- 年增率。
- HHI。
- World Total。
- 對帳差額與差異率。

## 3.4 Unit Test 方法

使用 dbt Unit Tests，為 SQL 模型提供少量固定輸入 rows，不查詢完整生產資料。

| Model | 測試案例 | 輸入 | 預期結果 |
|---|---|---|---|
| `int_unit_values_calculated` | 正常重量 | value=100、kg=20 | unit value=5 |
| `int_unit_values_calculated` | 重量為 0 | value=100、kg=0 | `NULL` |
| `int_unit_values_calculated` | 重量為負 | value=100、kg=-1 | `NULL` |
| `int_partner_market_share` | 正常分母 | partner=25、world=100 | share=0.25 |
| `int_partner_market_share` | World 為 0 | partner=25、world=0 | `NULL` |
| `int_partner_market_share` | 無 World row | partner row only | `NULL` 或模型明確失敗 |
| `int_market_concentration_hhi` | 兩國各 50% | 0.5、0.5 | HHI=5000 |
| `int_market_concentration_hhi` | 排除 World | country rows + World row | World 不進入 HHI |
| `stg_*` | period 轉換 | `202401` | `2024-01-01` |
| `stg_*` | 重複 rows | 相同 grain 不同 ingest time | 保留指定最新版 |
| `mart_*` | MoM／YoY | 固定 13 個月資料 | 成長率正確 |

測試指令：

```bash
dbt deps --project-dir dbt
dbt compile --project-dir dbt
dbt test --project-dir dbt --select test_type:unit
sqlfluff lint dbt/models --dialect bigquery
```

## 3.5 Integration Test

- 在開發 Dataset 執行 `dbt build`。
- 驗證所有模型可由空 Dataset 建立。
- 驗證 incremental model 執行兩次不產生重複 grain。
- 對一個固定月份人工計算 market share 與 HHI，和 SQL 結果比對。

## 3.6 交付物

- 完整 dbt project。
- Staging、Intermediate、Dimensions、Facts、Mart models。
- Model descriptions 與 column descriptions。
- dbt Unit Tests。
- dbt docs artifacts。

## 3.7 驗收標準

- `dbt compile` 通過。
- 所有 dbt Unit Tests 通過。
- SQLFluff 通過。
- Mart grain 唯一。
- 市占率、單位價格及 HHI 的人工抽樣結果一致。

---

# Phase 4：資料品質與對帳

## 4.1 目標

建立資料完整性、關聯一致性與 World reconciliation 機制，並區分警告與阻擋 pipeline 的錯誤。

## 4.2 使用工具

| 類型 | 工具 | 用途 |
|---|---|---|
| Data Test | dbt Generic Tests | unique、not_null、relationships 等 |
| Custom Test | dbt Singular Tests | World reconciliation 與業務規則 |
| Utility | `dbt-utils` | 組合唯一鍵、expression tests |
| Python Test | pytest | 閾值及資料品質函式 Unit Test |
| Reporting | dbt artifacts | 保存 test result 與失敗資訊 |

## 4.3 品質規則

### Schema 與 Grain

- `period_start_date` 不得為 NULL。
- `partner_code` 不得為 NULL。
- `cmd_code` 不得為 NULL。
- `flow_code` 僅接受 `M`。
- `reporter_code` 僅接受 `842`。
- Fact grain 必須唯一。
- Partner 必須能對應 `dim_countries` 或列入允許的 unresolved 清單。

### API 完整性

- row count 必須大於 0。
- 單次 response 若等於 API 上限，視為疑似截斷。
- Manifest row count 必須等於 BigQuery Raw row count。
- Manifest checksum 必須存在。

### Reconciliation

```text
partner_sum = SUM(partner_detail.primary_value)
difference = partner_sum - world_total
difference_rate = ABS(difference) / NULLIF(ABS(world_total), 0)
```

規則：

- `difference_rate <= 0.5%`：通過。
- `0.5% < difference_rate <= 2%`：警告並記錄。
- `difference_rate > 2%`：失敗。
- World Total 為 `0` 或缺少時：失敗。
- 閾值以設定檔管理，不寫死於多個 SQL 檔。
- 上線前需先分析歷史差異分布，再確認正式門檻。

對帳稽核表：`analytics_dataset.audit_world_reconciliation`

必要欄位：

- `period_start_date`
- `cmd_code`
- `partner_sum`
- `world_total`
- `difference`
- `difference_rate`
- `status`
- `tested_at`
- `run_id`

## 4.4 Unit Test 方法

| 測試檔／Model | 測試案例 | 輸入 | 預期結果 |
|---|---|---|---|
| `test_reconciliation.py` | 完全相等 | 100 vs 100 | PASS |
| `test_reconciliation.py` | 差異 0.4% | 100.4 vs 100 | PASS |
| `test_reconciliation.py` | 差異 1% | 101 vs 100 | WARN |
| `test_reconciliation.py` | 差異 3% | 103 vs 100 | FAIL |
| `test_reconciliation.py` | World 為 0 | 0 vs 0 | FAIL／明確狀態 |
| `test_reconciliation.py` | World 缺少 | partner only | FAIL |
| dbt Unit Test | 排除 aggregate rows | 國家 + 區域 rows | 只加總實際國家 |
| dbt Generic Test | 重複 grain | 重複 fixture | Test failure |
| dbt Relationships | 未知 country code | 無對應 dimension | Test failure 或 accepted exception |

測試指令：

```bash
pytest tests/unit/metrics -q
dbt test --project-dir dbt --select tag:data_quality
dbt test --project-dir dbt --select tag:reconciliation
```

## 4.5 Integration Test

- 在開發 Dataset 人工植入 PASS、WARN、FAIL 三種月份。
- 驗證 dbt exit code 與 severity 設定。
- 驗證 audit table 保存每次執行結果。
- 驗證失敗資料能定位至 period 與 cmd code。

## 4.6 交付物

- `schema.yml` Generic Tests。
- Singular Tests。
- Reconciliation macro。
- Audit table model。
- 閾值設定與說明。

## 4.7 驗收標準

- PASS／WARN／FAIL fixture 結果正確。
- World 缺失時不得讓 pipeline 靜默成功。
- 所有失敗均能定位至明確 partition。
- 測試結果可由 dbt artifacts 追蹤。

---

# Phase 5：Airflow 排程與歷史回填

## 5.1 目標

建立本機 Docker Airflow，編排每月同步流程與歷史回填流程，整合 Lambda、BigQuery Transfer、Cosmos dbt build、資料品質檢查及失敗告警。

## 5.2 使用工具

| 類型 | 工具 | 用途 |
|---|---|---|
| Orchestration | Apache Airflow | DAG 排程、重試、監控及回填 |
| Local Runtime | Docker Compose | 本機 Airflow 環境 |
| AWS Provider | `apache-airflow-providers-amazon` | Lambda invocation |
| GCP Provider | `apache-airflow-providers-google` | BigQuery Transfer／BigQuery jobs |
| dbt Integration | `astronomer-cosmos` | 將 dbt project 建成 TaskGroup |
| Test | pytest、Airflow DagBag | DAG import 與結構測試 |
| Time | Pendulum | 月份與時區處理 |
| Alert | Slack provider 或 LINE Webhook client | 失敗通知 |

## 5.3 Monthly DAG 規格

DAG ID：`trade_monthly`

建議流程：

```text
resolve_period
    → wait_for_availability
    → invoke_partner_detail_lambda
    → invoke_world_total_lambda
    → start_s3_transfer
    → wait_for_s3_transfer
    → validate_raw_load
    → dbt_build
    → reconciliation
```

設定：

- Schedule：每月固定日期執行，例如台北時間每月 10 日 09:00。
- `catchup=False`，歷史資料交由 Backfill 處理。
- `max_active_runs=1`。
- `retries=3`。
- `retry_exponential_backoff=True`。
- `execution_timeout` 依 task 類型設定。
- `on_failure_callback` 設定 Slack／LINE 告警。
- `period` 必須由明確函式產生，不直接依賴模糊的 logical date 假設。

### Availability Sensor

- 檢查目標 period 是否已發布。
- 使用 `reschedule` 或 deferrable mode。
- API Key 無效立即失敗。
- 尚未發布則繼續等待。
- Timeout 後失敗並告警。

### Pool 與限流

- Airflow Pool：`un_comtrade_api`，slots=`1`。
- 所有 Lambda ingestion tasks 指定該 Pool。
- Pool 只控制 Lambda tasks concurrency。
- 實際每秒 API request 限流由 Lambda 程式處理。

### Cosmos

- 使用 `DbtTaskGroup`，因為 dbt 是完整 pipeline 的其中一段。
- 將 period 透過 dbt vars 傳入 incremental models。
- dbt test failure 必須使 DAG 失敗。
- Airflow Connection 映射成 dbt BigQuery profile，避免維護第二份 credential。

## 5.4 Backfill 規格

DAG ID：`trade_backfill`

輸入：

```json
{
  "start_period": "202001",
  "end_period": "202412",
  "reprocess_policy": "missing"
}
```

行為：

- 將起訖區間展開為月份清單。
- 每個 mapped task 僅處理一個 period。
- 先完成 1～3 個月份 smoke backfill。
- 再執行完整年份。
- `max_active_runs=1`。
- ingestion task 仍受單 slot Pool 限制。
- 已存在且 checksum 一致時略過重新擷取。
- 支援 `missing`、`failed`、`force_revision` 等明確重跑政策。

若使用 Airflow 3 原生 Backfill，Monthly DAG 必須有明確的 time-based schedule，並使用 `airflow backfill create`；若採獨立參數化 Backfill DAG，則使用 Dynamic Task Mapping，不混用兩套語意。

## 5.5 Unit Test 方法

Unit Test 不啟動 Scheduler，也不連線 AWS／GCP。

| 測試檔 | 測試案例 | 方法 | 預期結果 |
|---|---|---|---|
| `test_dag_import.py` | DAG import | 使用 `DagBag` | `import_errors` 為空 |
| `test_dag_structure.py` | Monthly tasks | 比對 task IDs | 必要 tasks 全部存在 |
| `test_dag_structure.py` | Dependency | 檢查 upstream／downstream | 順序符合規格 |
| `test_dag_defaults.py` | Retry 設定 | 讀取 task properties | retries=3、backoff 開啟 |
| `test_dag_defaults.py` | Pool 設定 | 檢查 Lambda tasks | pool 正確 |
| `test_periods.py` | 上一完整月份 | 固定時間 | period 正確 |
| `test_periods.py` | 跨年 | 2026-01 執行 | 回傳 202512 |
| `test_periods.py` | 展開區間 | 202011～202102 | 4 個月份且順序正確 |
| `test_periods.py` | 非法區間 | start > end | Validation Error |
| `test_availability.py` | period 可用 | Mock Lambda／HTTP | Sensor success |
| `test_availability.py` | 尚未發布 | Mock unavailable | Sensor 持續等待 |
| `test_alerts.py` | 失敗 payload | Fake context | 訊息含 DAG、task、period、log URL |
| `test_alerts.py` | Secret 遮罩 | Fake error | 告警不含 credential |

測試指令：

```bash
pytest tests/dags -q
airflow dags list-import-errors
airflow dags test trade_monthly 2026-08-10
```

其中 `airflow dags test` 屬於本機 DAG 測試，不視為純 Unit Test；外部 Operator 必須切換至 mock／test configuration。

## 5.6 Integration Test

- Docker Compose 啟動 Scheduler、API Server／Webserver、Triggerer 與 metadata database。
- 手動觸發一個測試 period。
- 驗證 Lambda、Transfer、dbt、reconciliation 的完整 task state。
- 故意讓一個 task 失敗，確認 retry 與 callback。
- 清除失敗 task 後重跑，確認冪等性。
- 對 1～3 個月份執行 Backfill smoke test。

## 5.7 交付物

- `trade_monthly.py`。
- `trade_backfill.py` 或原生 Backfill 操作文件。
- Availability Sensor／Trigger。
- Cosmos `DbtTaskGroup`。
- Airflow Connections 與 Pool 建立說明。
- Slack／LINE callback。
- DAG Unit Tests。

## 5.8 驗收標準

- DagBag 無 import error。
- Monthly DAG 可完成單一測試月份。
- 失敗 task 按設定重試並發出告警。
- Backfill 每個 task 只處理一個 period。
- 相同月份重跑不造成 S3／BigQuery 重複資料。

---

# Phase 6：Streamlit、Cloud Run、CI/CD 與成果交付

## 6.1 目標

建立可互動的分析看板，部署至 Cloud Run，並以 GitHub Actions 自動執行程式、dbt、DAG 與 Container 測試。

## 6.2 使用工具

| 類型 | 工具 | 用途 |
|---|---|---|
| App | Streamlit | Dashboard UI |
| Visualization | Plotly | 地圖、趨勢與散佈圖 |
| Data Access | `google-cloud-bigquery`、BigQuery Storage API | 查詢 Mart |
| Cache | `st.cache_data` | 降低重複查詢成本 |
| Container | Docker | 建置應用映像 |
| Registry | Artifact Registry | 保存 Cloud Run Image |
| Hosting | Google Cloud Run | 部署 Streamlit |
| CI/CD | GitHub Actions | 自動測試、建置與部署 |
| App Test | Streamlit AppTest、pytest | UI 與純函式測試 |
| Security | Trivy 或 `pip-audit` | Image／dependency 弱點掃描 |

## 6.3 Dashboard 規格

### 共用篩選器

- 日期區間。
- HS Code。
- Partner Country。
- 指標。

### 模組一：來源國地理版圖

- Choropleth Map。
- 使用 ISO alpha-3 對應地圖。
- Tooltip 顯示進口金額、市占率與 YoY。
- 無法對應 ISO 的資料顯示於 unmapped 清單，不可靜默丟棄。

### 模組二：市占率消長趨勢

- 顯示指定國家月度 Market Share。
- 可選 Top N。
- 可切換金額與市占率。
- 顯示資料最新月份。

### 模組三：單價 vs 重量散佈圖

- X 軸：Net Weight。
- Y 軸：USD／KG。
- Bubble size：Import Value。
- Color：Partner Country 或 Region。
- 排除 unit value 為 NULL 的資料。

### 安全與效能

- Dashboard 只能查詢 Mart，不直接查 Raw。
- SQL 使用 query parameters，不拼接未驗證輸入。
- Service Account 採 BigQuery read-only 權限。
- `@st.cache_data` 必須設定 TTL。
- 每次查詢必須有日期 partition filter。
- 設定 BigQuery maximum bytes billed 或對等成本防護。

## 6.4 Cloud Run 規格

- Container 綁定 `0.0.0.0` 與環境變數 `PORT`。
- `min-instances=0`。
- 設定 memory、CPU、concurrency 與 timeout。
- 使用 Cloud Run Service Account 連線 BigQuery。
- 不在 image 內放入 Service Account JSON Key。
- MVP 可先使用預設 `run.app` URL。
- 正式自訂網域優先使用 External Application Load Balancer。
- Route 53 記錄依 Google 產生的 A／AAAA／CNAME 設定，不預設一律為 CNAME。

## 6.5 CI/CD Pipeline

### Pull Request

1. 安裝 Python dependencies。
2. 執行 Ruff、mypy、pytest。
3. 執行 Airflow DagBag tests。
4. 建立唯一名稱的暫時 BigQuery Dataset。
5. 執行 `dbt deps`、`dbt compile`、`dbt build`。
6. 建置 Docker image。
7. 執行 Container smoke test。
8. 無論成功或失敗都刪除暫時 Dataset。

暫時 Dataset 命名：

```text
ci_trade_analytics_pr_<PR_NUMBER>_<RUN_ID>
```

### Main Branch

1. 重跑完整 CI。
2. 建置帶有 Git SHA tag 的 image。
3. 推送至 Artifact Registry。
4. 部署至 Cloud Run staging。
5. 執行 smoke test。
6. MVP 可採手動批准後部署 production。

## 6.6 Unit Test 方法

| 測試檔 | 測試案例 | 方法 | 預期結果 |
|---|---|---|---|
| `test_dashboard_queries.py` | 日期參數 | Mock BigQuery client | 使用 query parameters |
| `test_dashboard_queries.py` | Partition filter | 檢查 SQL | 必須包含日期條件 |
| `test_dashboard_queries.py` | 空結果 | Mock empty DataFrame | 回傳空狀態、不 crash |
| `test_dashboard_transforms.py` | ISO mapping | 固定國家 fixture | ISO alpha-3 正確 |
| `test_dashboard_transforms.py` | 未知國家 | 未對應 code | 進入 unmapped 清單 |
| `test_dashboard_transforms.py` | NULL unit value | 固定 rows | 散佈圖資料排除 NULL |
| `test_dashboard_transforms.py` | Top N | 多國資料 | 排序及筆數正確 |
| `test_app.py` | 首頁載入 | Streamlit AppTest | 無 exception |
| `test_app.py` | 篩選器操作 | AppTest 設定值 | 圖表更新 |
| `test_config.py` | 缺少設定 | 清除必要 env | 清楚的啟動錯誤 |

測試指令：

```bash
pytest tests/unit/dashboard -q
pytest tests/unit/dashboard --cov=trade_analytics.dashboard --cov-report=term-missing
docker build -t trade-dashboard:test .
pip-audit
```

## 6.7 Integration／End-to-End Test

- 使用測試 Dataset 啟動 Streamlit。
- 驗證三個模組均可產生圖表。
- Docker container health check 通過。
- 部署 Cloud Run staging 後檢查 HTTP 200。
- 使用固定篩選條件查詢，核對 Dashboard 與 BigQuery 結果。
- 驗證未授權帳號無法讀取 BigQuery。
- 驗證 `min-instances=0` 與 Service Account 設定。

## 6.8 交付物

- Streamlit application。
- Dashboard Dockerfile 與 `.dockerignore`。
- Cloud Run deployment configuration。
- GitHub Actions workflows。
- Container／dependency security scan。
- README、架構圖、資料字典、指標公式與 Live Demo URL。

## 6.9 驗收標準

- 三個互動模組正常顯示。
- 空資料與未知國家不造成 application crash。
- Cloud Run staging smoke test 通過。
- Pull Request CI 可自動建立及清除暫時 Dataset。
- Production image 可追溯至 Git SHA。
- Repository 不包含任何長期 Cloud credential。

---

# 7. 跨 Phase 測試策略

## 7.1 測試分層

| 層級 | 外部服務 | 執行時機 | 目的 |
|---|---|---|---|
| Unit Test | 全部 Mock | 每次 commit／PR | 驗證純函式與錯誤分支 |
| Contract Test | 使用固定 API fixtures | PR | 驗證 API response schema 相容性 |
| Integration Test | 測試 AWS／GCP 資源 | PR protected job／手動 | 驗證服務整合 |
| End-to-End Test | Staging 全流程 | Main branch／發布前 | 驗證實際 pipeline |
| Data Test | BigQuery 開發／CI Dataset | PR、排程執行 | 驗證資料內容與業務規則 |

## 7.2 覆蓋率門檻

- Python Unit Test：整體至少 80%。
- Ingestion、Manifest、Reconciliation 核心模組：至少 90%。
- 新增或修改的 Python 程式碼：至少 85%。
- dbt 核心指標 models：每個主要分支至少一個 Unit Test。
- DAG：每個 DAG 都必須具有 import、task、dependency 與 default args tests。

## 7.3 測試資料原則

- Fixture 不得包含 API Key、Access Key 或 Service Account Key。
- API fixture 應裁切至最小重現資料。
- 所有 fixture 必須包含來源 schema version。
- 測試資料至少涵蓋正常值、NULL、0、負值、重複值及缺失維度。
- 金額比較使用 Decimal／BigQuery NUMERIC，避免 binary float 誤差。

# 8. Definition of Done

每個 Phase 必須同時符合下列條件才算完成：

- 實作項目完成並通過 code review。
- Unit Test 通過且達到覆蓋率門檻。
- 相關 Integration Test 通過。
- Secret scan 未發現 credential。
- 文件、設定範例及操作方式已更新。
- 交付物可由乾淨環境重新建立。
- 已記錄已知限制與後續工作。

# 9. 建議執行時程

| Phase | 內容 | MVP 預估 |
|---|---|---:|
| Phase 1 | API PoC 與資料契約 | 1～1.5 天 |
| Phase 2 | Lambda、S3、BigQuery Raw | 1～1.5 天 |
| Phase 3 | dbt 建模與指標 | 1～2 天 |
| Phase 4 | 資料品質與對帳 | 0.5～1 天 |
| Phase 5 | Airflow 與 Backfill | 1～2 天 |
| Phase 6 | Streamlit、Cloud Run、CI/CD | 1～1.5 天 |
| 合計 | 可展示 MVP | 5.5～9.5 天 |

# 10. 實作閘門

| Gate | 必須通過的條件 | 才可進入 |
|---|---|---|
| Gate 1 | API Contract、retry、schema tests 通過 | Phase 2 |
| Gate 2 | Lambda 冪等、S3 Manifest、BigQuery Raw 驗證通過 | Phase 3 |
| Gate 3 | dbt 指標 Unit Tests 與 Mart grain 通過 | Phase 4 |
| Gate 4 | 對帳 PASS／WARN／FAIL 行為通過 | Phase 5 |
| Gate 5 | Monthly DAG 與 smoke backfill 通過 | Phase 6 |
| Gate 6 | Dashboard、Cloud Run staging、CI 全部通過 | MVP 交付 |

# 11. 參考文件

- [UN Comtrade API](https://comtradeapi.un.org/)
- [BigQuery Data Transfer Service：Amazon S3](https://cloud.google.com/bigquery/docs/s3-transfer)
- [Apache Airflow Backfill](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/backfill.html)
- [Astronomer Cosmos Core Concepts](https://astronomer.github.io/astronomer-cosmos/getting_started/core-concepts.html)
- [Cloud Run Custom Domains](https://cloud.google.com/run/docs/mapping-custom-domains)
