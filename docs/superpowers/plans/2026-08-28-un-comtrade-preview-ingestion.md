# UN Comtrade Preview Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可由 CLI 執行、可驗證並可重用於 Lambda 的 UN Comtrade 月度 Preview API 擷取模組。

**Architecture:** 將 query、response schema、HTTP retry、資料契約、manifest 與本機 storage 分成獨立模組，由 service 統一協調。CLI 只處理參數與 exit code；Unit Test 全部使用 mock HTTP 與 temporary directory，真實 API 僅由明確啟用的 Integration Test 呼叫。

**Tech Stack:** Python 3.11、httpx、Pydantic 2、Tenacity、pytest、respx、pytest-cov、Ruff、mypy。

**Spec:** `docs/superpowers/specs/2026-08-28-un-comtrade-preview-ingestion-design.md`

## Global Constraints

- Runtime 固定為 Python 3.11。
- Base URL 固定為 `https://comtradeapi.un.org/public/v1/preview/C/M/HS`，但必須可由 client constructor 覆寫。
- Reporter 固定為 `842`，Flow 固定為 `M`，Partner 2 固定為 `0`，Customs 固定為 `C00`，Mode of Transport 固定為 `0`。
- 預設 Period 為 `202401`，預設 Commodity Code 為 `8542`。
- `partner_detail` 排除 `partnerCode=0`；`world_total` 明確指定並只接受 `partnerCode=0`。
- Preview response `count >= 500` 必須視為疑似截斷並拒絕保存。
- API Key、Authorization header、完整 response body 不得寫入 Log。
- 所有 production behavior 都必須先有一個正確失敗的測試。
- Unit Test 不得連線真實網路。
- Unit Test coverage 至少 85%。

---

## File Map

| Path | Responsibility |
|---|---|
| `pyproject.toml` | Runtime、development dependencies 與 pytest／Ruff／mypy 設定 |
| `.gitignore` | 排除 virtual environment、cache、coverage 與本機 `data/` |
| `src/trade_analytics/ingestion/queries.py` | Query type、輸入驗證與 API parameters |
| `src/trade_analytics/ingestion/exceptions.py` | Domain exceptions |
| `src/trade_analytics/ingestion/schemas.py` | Preview API response models |
| `src/trade_analytics/ingestion/client.py` | HTTP request、timeout、retry 與 response parsing |
| `src/trade_analytics/ingestion/service.py` | Query-type filtering、data contract 與 ingestion orchestration |
| `src/trade_analytics/ingestion/manifest.py` | Canonical NDJSON、checksum 與 manifest |
| `src/trade_analytics/ingestion/storage.py` | 本機原子寫入與 output paths |
| `ingest.py` | CLI entry point |
| `tests/fixtures/comtrade_preview_response.json` | 最小 contract fixture |
| `tests/unit/ingestion/` | 不連網 Unit Tests |
| `tests/integration/test_preview_api.py` | 手動啟用的真實 API test |
| `tests/conftest.py` | Integration test option 與 network guard |
| `README.md` | 安裝、執行、輸出與測試文件 |

---

### Task 1: Package Setup and Query Contract

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `src/trade_analytics/__init__.py`
- Create: `src/trade_analytics/ingestion/__init__.py`
- Create: `src/trade_analytics/ingestion/exceptions.py`
- Create: `src/trade_analytics/ingestion/queries.py`
- Test: `tests/unit/ingestion/test_queries.py`

**Interfaces:**
- Consumes: CLI values `period: str`、`cmd_code: str`、`query_type: str`。
- Produces: `QueryType`、`ComtradeQuery`、`ComtradeQuery.to_params() -> dict[str, str | int]`。

- [ ] **Step 1: 建立 package 設定與 failing query tests**

Create `pyproject.toml` with project metadata, `src` package discovery, dependencies `httpx>=0.27,<1`、`pydantic>=2.8,<3`、`tenacity>=9,<10`, and dev dependencies `pytest>=8,<10`、`pytest-cov>=5,<8`、`respx>=0.21,<1`、`ruff>=0.8,<1`、`mypy>=1.13,<2`。

Create `tests/unit/ingestion/test_queries.py`:

```python
import pytest
from pydantic import ValidationError

from trade_analytics.ingestion.queries import ComtradeQuery, QueryType


def test_partner_detail_parameters_fix_us_monthly_import_scope() -> None:
    query = ComtradeQuery(
        period="202401",
        cmd_code="8542",
        query_type=QueryType.PARTNER_DETAIL,
    )

    assert query.to_params() == {
        "reporterCode": 842,
        "period": "202401",
        "cmdCode": "8542",
        "flowCode": "M",
        "partner2Code": 0,
        "customsCode": "C00",
        "motCode": 0,
    }


def test_world_total_parameters_explicitly_request_world_partner() -> None:
    query = ComtradeQuery(
        period="202401",
        cmd_code="8542",
        query_type=QueryType.WORLD_TOTAL,
    )

    assert query.to_params()["partnerCode"] == 0


@pytest.mark.parametrize("period", ["2024", "202413", "20240101", "abcdef"])
def test_period_must_be_a_valid_year_month(period: str) -> None:
    with pytest.raises(ValidationError):
        ComtradeQuery(period=period, cmd_code="8542", query_type="partner_detail")


@pytest.mark.parametrize("cmd_code", ["8", "854", "85421", "ABCDEF"])
def test_cmd_code_must_be_two_four_or_six_digits(cmd_code: str) -> None:
    with pytest.raises(ValidationError):
        ComtradeQuery(period="202401", cmd_code=cmd_code, query_type="partner_detail")
```

- [ ] **Step 2: 執行 tests，確認因 package 尚未存在而正確失敗**

Run:

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest tests/unit/ingestion/test_queries.py -v
```

Expected: FAIL during import with `ModuleNotFoundError: No module named 'trade_analytics'` or missing `queries` module。

- [ ] **Step 3: 實作最小 query model 與 exceptions**

Create `queries.py` with:

```python
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator


class QueryType(StrEnum):
    PARTNER_DETAIL = "partner_detail"
    WORLD_TOTAL = "world_total"


class ComtradeQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    period: str = "202401"
    cmd_code: str = "8542"
    query_type: QueryType

    @field_validator("period")
    @classmethod
    def validate_period(cls, value: str) -> str:
        parsed = datetime.strptime(value, "%Y%m")
        if parsed.strftime("%Y%m") != value:
            raise ValueError("period must use YYYYMM")
        return value

    @field_validator("cmd_code")
    @classmethod
    def validate_cmd_code(cls, value: str) -> str:
        if not value.isdigit() or len(value) not in {2, 4, 6}:
            raise ValueError("cmd_code must contain 2, 4, or 6 digits")
        return value

    def to_params(self) -> dict[str, str | int]:
        params: dict[str, str | int] = {
            "reporterCode": 842,
            "period": self.period,
            "cmdCode": self.cmd_code,
            "flowCode": "M",
            "partner2Code": 0,
            "customsCode": "C00",
            "motCode": 0,
        }
        if self.query_type is QueryType.WORLD_TOTAL:
            params["partnerCode"] = 0
        return params
```

Create the exception hierarchy from the design in `exceptions.py` and export public types from `ingestion/__init__.py`。

- [ ] **Step 4: 執行 query tests，確認通過**

Run: `.venv/bin/pytest tests/unit/ingestion/test_queries.py -v`

Expected: all tests PASS。

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore src tests/unit/ingestion/test_queries.py
git commit -m "feat: define Comtrade query contract"
```

---

### Task 2: Preview Response Schema

**Files:**
- Create: `src/trade_analytics/ingestion/schemas.py`
- Create: `tests/fixtures/comtrade_preview_response.json`
- Test: `tests/unit/ingestion/test_schemas.py`

**Interfaces:**
- Consumes: `dict[str, object]` decoded from Preview API JSON。
- Produces: `ComtradeResponse(count: int, data: list[TradeRecord], error: str)` and `TradeRecord` aliased fields。

- [ ] **Step 1: 建立最小 response fixture 與 failing schema tests**

Fixture contains three import records for period `202401`: partner `156`, partner `410`, and World `0`; fields include the actual API names `period`、`reporterCode`、`flowCode`、`partnerCode`、`partner2Code`、`classificationCode`、`cmdCode`、`customsCode`、`motCode`、`qty`、`netWgt`、`primaryValue`、`isQtyEstimated`、`isNetWgtEstimated`、`isAggregate`。

Create tests:

```python
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from trade_analytics.ingestion.schemas import ComtradeResponse


FIXTURE = Path("tests/fixtures/comtrade_preview_response.json")


def test_preview_response_maps_camel_case_fields() -> None:
    payload = json.loads(FIXTURE.read_text())
    response = ComtradeResponse.model_validate(payload)

    assert response.count == 3
    assert response.data[0].reporter_code == 842
    assert response.data[0].primary_value == 100.0


def test_nullable_weight_and_descriptions_are_accepted() -> None:
    payload = json.loads(FIXTURE.read_text())
    payload["data"][0]["netWgt"] = None
    payload["data"][0]["partnerDesc"] = None

    response = ComtradeResponse.model_validate(payload)

    assert response.data[0].net_weight is None


def test_missing_required_trade_key_is_rejected() -> None:
    payload = json.loads(FIXTURE.read_text())
    del payload["data"][0]["partnerCode"]

    with pytest.raises(ValidationError):
        ComtradeResponse.model_validate(payload)
```

- [ ] **Step 2: 執行 tests，確認 missing module failure**

Run: `.venv/bin/pytest tests/unit/ingestion/test_schemas.py -v`

Expected: FAIL because `schemas.py` does not exist。

- [ ] **Step 3: 實作 aliased Pydantic models**

Use explicit aliases, `ConfigDict(populate_by_name=True, extra="allow")`, numeric nullable fields, and boolean estimation flags. Required contract fields must not have defaults; optional API description／measurement fields default to `None`。

Core model fields:

```python
class TradeRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    period: str
    reporter_code: int = Field(alias="reporterCode")
    flow_code: str = Field(alias="flowCode")
    partner_code: int = Field(alias="partnerCode")
    partner_2_code: int = Field(alias="partner2Code")
    classification_code: str = Field(alias="classificationCode")
    cmd_code: str = Field(alias="cmdCode")
    customs_code: str = Field(alias="customsCode")
    mot_code: int = Field(alias="motCode")
    quantity: float | None = Field(default=None, alias="qty")
    net_weight: float | None = Field(default=None, alias="netWgt")
    primary_value: float | None = Field(default=None, alias="primaryValue")
    is_quantity_estimated: bool | None = Field(default=None, alias="isQtyEstimated")
    is_net_weight_estimated: bool | None = Field(default=None, alias="isNetWgtEstimated")
    is_aggregate: bool | None = Field(default=None, alias="isAggregate")
```

- [ ] **Step 4: 執行 schema tests 與既有 tests**

Run: `.venv/bin/pytest tests/unit/ingestion/test_schemas.py tests/unit/ingestion/test_queries.py -v`

Expected: all tests PASS。

- [ ] **Step 5: Commit**

```bash
git add src/trade_analytics/ingestion/schemas.py tests/fixtures tests/unit/ingestion/test_schemas.py
git commit -m "feat: validate Comtrade preview responses"
```

---

### Task 3: HTTP Client and Retry Policy

**Files:**
- Create: `src/trade_analytics/ingestion/client.py`
- Test: `tests/unit/ingestion/test_client.py`

**Interfaces:**
- Consumes: `ComtradeQuery` and injected `httpx.Client`。
- Produces: `ComtradeClient.fetch(query: ComtradeQuery) -> ComtradeResponse`。

- [ ] **Step 1: 寫 HTTP success、retry、non-retry 與 truncation failing tests**

Use `respx` and `wait_none()` so Unit Tests do not sleep:

```python
import httpx
import pytest
import respx
from tenacity import wait_none

from trade_analytics.ingestion.client import ComtradeClient
from trade_analytics.ingestion.exceptions import (
    ComtradeAuthenticationError,
    ComtradeRequestError,
    ResponseTruncatedError,
)
from trade_analytics.ingestion.queries import ComtradeQuery, QueryType


QUERY = ComtradeQuery(period="202401", cmd_code="8542", query_type=QueryType.PARTNER_DETAIL)


@respx.mock
def test_fetch_parses_successful_response(preview_payload: dict[str, object]) -> None:
    route = respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(
        return_value=httpx.Response(200, json=preview_payload)
    )
    with httpx.Client() as http_client:
        response = ComtradeClient(http_client=http_client, wait=wait_none()).fetch(QUERY)

    assert response.count == 3
    assert route.call_count == 1


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
@respx.mock
def test_retryable_status_is_retried(status: int, preview_payload: dict[str, object]) -> None:
    route = respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(
        side_effect=[httpx.Response(status), httpx.Response(200, json=preview_payload)]
    )
    with httpx.Client() as http_client:
        response = ComtradeClient(http_client=http_client, wait=wait_none()).fetch(QUERY)

    assert response.count == 3
    assert route.call_count == 2


@respx.mock
def test_authentication_error_is_not_retried() -> None:
    route = respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(return_value=httpx.Response(401))
    with httpx.Client() as http_client:
        with pytest.raises(ComtradeAuthenticationError):
            ComtradeClient(http_client=http_client, wait=wait_none()).fetch(QUERY)
    assert route.call_count == 1


@respx.mock
def test_count_at_preview_limit_is_rejected(preview_payload: dict[str, object]) -> None:
    preview_payload["count"] = 500
    respx.get(ComtradeClient.DEFAULT_BASE_URL).mock(
        return_value=httpx.Response(200, json=preview_payload)
    )
    with httpx.Client() as http_client:
        with pytest.raises(ResponseTruncatedError):
            ComtradeClient(http_client=http_client, wait=wait_none()).fetch(QUERY)
```

Add timeout and 400 tests, plus a test proving request params contain `flowCode=M`。Provide `preview_payload` through a fixture in `tests/conftest.py`。

- [ ] **Step 2: 執行 client tests，確認正確失敗**

Run: `.venv/bin/pytest tests/unit/ingestion/test_client.py -v`

Expected: FAIL because `client.py` does not exist。

- [ ] **Step 3: 實作 client 與 Tenacity retry**

Implement:

- `DEFAULT_BASE_URL` constant。
- Constructor arguments `http_client`、`base_url`、`timeout`、`wait`。
- `Retrying(stop=stop_after_attempt(4), retry=retry_if_exception_type(_RetryableRequestError), wait=...)`。
- Translate 401／403 into `ComtradeAuthenticationError`。
- Translate retry exhaustion and 4xx into `ComtradeRequestError`。
- Parse JSON and top-level `error`; invalid JSON or non-empty error becomes `ComtradeResponseError`。
- Reject `count >= 500`。
- Retry timeout and `httpx.TransportError`。

Use a private retryable exception carrying optional `retry_after: float | None`; the default wait callable returns retry-after when present, otherwise exponential `min(2 ** (attempt - 1), 8)` seconds。

- [ ] **Step 4: 執行 client tests 與完整 Unit Tests**

Run: `.venv/bin/pytest tests/unit/ingestion -v`

Expected: all tests PASS with no real delay and no network request。

- [ ] **Step 5: Commit**

```bash
git add src/trade_analytics/ingestion/client.py tests/conftest.py tests/unit/ingestion/test_client.py
git commit -m "feat: add resilient Comtrade HTTP client"
```

---

### Task 4: Data Contract Service

**Files:**
- Create: `src/trade_analytics/ingestion/service.py`
- Test: `tests/unit/ingestion/test_service.py`

**Interfaces:**
- Consumes: `ComtradeClient.fetch()` and `ComtradeQuery`。
- Produces: `IngestionDataset(query: ComtradeQuery, rows: tuple[TradeRecord, ...])` via `fetch_dataset()`。

- [ ] **Step 1: 寫 query-type 與 data-contract failing tests**

Create a small fake client returning `ComtradeResponse`, not a mock call assertion. Tests must cover:

```python
def test_partner_detail_excludes_world_row(preview_response: ComtradeResponse) -> None:
    dataset = IngestionService(FakeClient(preview_response)).fetch_dataset(PARTNER_QUERY)
    assert {row.partner_code for row in dataset.rows} == {156, 410}


def test_world_total_contains_exactly_one_world_row(preview_response: ComtradeResponse) -> None:
    dataset = IngestionService(FakeClient(preview_response)).fetch_dataset(WORLD_QUERY)
    assert len(dataset.rows) == 1
    assert dataset.rows[0].partner_code == 0
```

Also test `EmptyDataError` and `DataContractError` for mismatched period、reporter、flow、cmd code、non-world row in a World-only response、duplicate grain and multiple World rows。

- [ ] **Step 2: 執行 service tests，確認 missing service failure**

Run: `.venv/bin/pytest tests/unit/ingestion/test_service.py -v`

Expected: FAIL because `service.py` does not exist。

- [ ] **Step 3: 實作最小 service**

Implement immutable `IngestionDataset` and validation helpers。For every record compare query contract, then branch on `QueryType`。Duplicate key is exactly `(row.period, row.partner_code, row.cmd_code)`。

`partner_detail` filters World before empty and duplicate validation。`world_total` rejects any non-world row and requires length exactly one；because the client request explicitly includes `partnerCode=0`, a mixed response is a contract failure rather than silently filtered。

- [ ] **Step 4: 執行 service tests 與完整 Unit Tests**

Run: `.venv/bin/pytest tests/unit/ingestion -v`

Expected: all tests PASS。

- [ ] **Step 5: Commit**

```bash
git add src/trade_analytics/ingestion/service.py tests/unit/ingestion/test_service.py
git commit -m "feat: enforce Comtrade ingestion contract"
```

---

### Task 5: Canonical NDJSON, Manifest, and Local Storage

**Files:**
- Create: `src/trade_analytics/ingestion/manifest.py`
- Create: `src/trade_analytics/ingestion/storage.py`
- Test: `tests/unit/ingestion/test_manifest.py`
- Test: `tests/unit/ingestion/test_storage.py`

**Interfaces:**
- Consumes: `IngestionDataset`。
- Produces: `serialize_ndjson(dataset) -> bytes`、`build_manifest(dataset, data, ingested_at) -> Manifest`、`LocalStorage.write(...) -> StoredIngestion`。

- [ ] **Step 1: 寫 deterministic serialization 與 checksum failing tests**

Tests must create the same two rows in reversed order and prove identical bytes／checksum。They must verify newline-delimited JSON, `sha256:` prefix, `row_count`, Decimal-based `primary_value_sum`, request parameters and `schema_version="1.0.0"`。

```python
def test_checksum_is_independent_of_input_row_order(dataset: IngestionDataset) -> None:
    reversed_dataset = replace(dataset, rows=tuple(reversed(dataset.rows)))
    first = serialize_ndjson(dataset)
    second = serialize_ndjson(reversed_dataset)
    assert first == second
    assert checksum(first) == checksum(second)
```

- [ ] **Step 2: 執行 manifest tests，確認 missing module failure**

Run: `.venv/bin/pytest tests/unit/ingestion/test_manifest.py -v`

Expected: FAIL because `manifest.py` does not exist。

- [ ] **Step 3: 實作 canonical serialization 與 manifest**

Serialize `TradeRecord.model_dump(by_alias=True, mode="json", exclude_none=False)` using `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)`。Sort by period、partnerCode、cmdCode and terminate every row with `\n`。Compute primary value sum as `sum(Decimal(str(value)) ...)` and serialize the total as a string。

- [ ] **Step 4: 執行 manifest tests，確認通過**

Run: `.venv/bin/pytest tests/unit/ingestion/test_manifest.py -v`

Expected: all tests PASS。

- [ ] **Step 5: 寫 local storage failing tests**

Use `tmp_path` and assert exact output paths, file bytes and parsed manifest。Patch `Path.replace` or inject a replace function to prove temporary files are used before final files。Also simulate a write error and assert no success result is returned。

- [ ] **Step 6: 執行 storage tests，確認 missing module failure**

Run: `.venv/bin/pytest tests/unit/ingestion/test_storage.py -v`

Expected: FAIL because `storage.py` does not exist。

- [ ] **Step 7: 實作 LocalStorage**

Output root defaults to `Path("data/preview")`。Build `period=<period>/query_type=<query_type>`。Create both temporary files in the target directory using `tempfile.NamedTemporaryFile(delete=False, dir=target_dir)`，flush and `os.fsync` each file, then `os.replace` data followed by manifest。On exception, unlink remaining temporary files and re-raise。

- [ ] **Step 8: 執行 storage、manifest 與完整 Unit Tests**

Run: `.venv/bin/pytest tests/unit/ingestion -v`

Expected: all tests PASS。

- [ ] **Step 9: Commit**

```bash
git add src/trade_analytics/ingestion/manifest.py src/trade_analytics/ingestion/storage.py tests/unit/ingestion/test_manifest.py tests/unit/ingestion/test_storage.py
git commit -m "feat: write deterministic Comtrade preview artifacts"
```

---

### Task 6: CLI Orchestration

**Files:**
- Create: `ingest.py`
- Test: `tests/unit/test_ingest_cli.py`
- Modify: `src/trade_analytics/ingestion/__init__.py`

**Interfaces:**
- Consumes: CLI arguments and the modules from Tasks 1–5。
- Produces: exit code `0` with JSON metadata on stdout or exit code `1／2` with concise error on stderr。

- [ ] **Step 1: 寫 CLI parse、success 與 failure tests**

Import `ingest.main` and inject a callable `runner(query, output_dir)` so tests do not use network。Cover defaults, invalid period argparse exit, success metadata, domain exception exit and no full rows in stdout。

Expected success output fields:

```json
{
  "status": "success",
  "period": "202401",
  "query_type": "partner_detail",
  "row_count": 2,
  "data_path": ".../data.ndjson",
  "manifest_path": ".../manifest.json",
  "checksum": "sha256:..."
}
```

- [ ] **Step 2: 執行 CLI tests，確認 missing module failure**

Run: `.venv/bin/pytest tests/unit/test_ingest_cli.py -v`

Expected: FAIL because `ingest.py` does not exist。

- [ ] **Step 3: 實作 CLI 與 default runner**

Use `argparse` with required `--query-type` choices from `QueryType` and defaults from the spec。The default runner opens `httpx.Client(timeout=httpx.Timeout(connect=10, read=30, write=30, pool=10))`, then constructs client → service → manifest → storage。Only the CLI owns stdout／stderr；library modules raise typed exceptions。

Catch `ValidationError` and `ComtradeError`，print concise error to stderr without headers or response body，return `1`。Argparse invalid options retain exit code `2`。

- [ ] **Step 4: 執行 CLI tests 與完整 Unit Tests**

Run: `.venv/bin/pytest tests/unit -v`

Expected: all tests PASS。

- [ ] **Step 5: Commit**

```bash
git add ingest.py src/trade_analytics/ingestion/__init__.py tests/unit/test_ingest_cli.py
git commit -m "feat: add Comtrade preview ingestion CLI"
```

---

### Task 7: Integration Test, Documentation, and Quality Gate

**Files:**
- Create: `tests/integration/test_preview_api.py`
- Modify: `tests/conftest.py`
- Modify: `README.md`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: public client／service interface and live Preview API。
- Produces: opt-in integration suite and complete user instructions。

- [ ] **Step 1: 寫 opt-in Integration Test 與 skip guard**

Add `--run-integration` in `pytest_addoption` and skip tests marked `integration` unless enabled。Integration test uses `period=202401`、`cmd_code=8542` and executes both query types。Assert partner rows are non-empty and non-world, World result is exactly one row, all flow codes are `M`, and response remains below 500。

- [ ] **Step 2: 驗證一般 Unit Test 不會呼叫網路**

Run: `.venv/bin/pytest -m 'not integration' -v`

Expected: Integration Test is skipped and all Unit Tests PASS。

- [ ] **Step 3: 更新 README**

Replace `demo` with:

- Python 3.11 prerequisite。
- `.venv` setup and `pip install -e '.[dev]'`。
- Partner Detail and World Total CLI examples。
- Output directory tree and manifest explanation。
- Unit、coverage、Ruff、mypy and opt-in Integration Test commands。
- Preview API limitations: no API key、500-row truncation guard、nullable descriptions and annual URL not used。
- Phase 1 scope boundary: no Lambda／S3／BigQuery。

- [ ] **Step 4: 執行真實 Integration Test**

Run: `.venv/bin/pytest tests/integration/test_preview_api.py --run-integration -v`

Expected: two query types PASS against the live Preview endpoint。

- [ ] **Step 5: 執行 CLI smoke test**

Run:

```bash
.venv/bin/python ingest.py --period 202401 --cmd-code 8542 --query-type partner_detail
.venv/bin/python ingest.py --period 202401 --cmd-code 8542 --query-type world_total
```

Expected: both commands return exit code 0 and create separate `data.ndjson`／`manifest.json` directories。Verify partner output has no `partnerCode=0`; World output has exactly one row。

- [ ] **Step 6: 執行完整品質閘門**

Run:

```bash
.venv/bin/ruff format --check src tests ingest.py
.venv/bin/ruff check src tests ingest.py
.venv/bin/mypy src ingest.py
.venv/bin/pytest tests/unit -q --cov=trade_analytics.ingestion --cov-report=term-missing --cov-fail-under=85
git diff --check
```

Expected: all commands exit 0, coverage at least 85%, no warnings or formatting errors。

- [ ] **Step 7: Commit**

```bash
git add README.md pyproject.toml tests/conftest.py tests/integration/test_preview_api.py
git commit -m "test: verify Comtrade preview ingestion end to end"
```

---

## Plan Self-Review

- Spec coverage：query、schema、retry、truncation、contract、NDJSON、manifest、storage、CLI、integration、README 與品質閘門均有對應 Task。
- Placeholder scan：無 TBD、TODO、`implement later` 或未定義的「適當處理」。
- Type consistency：Tasks 3–7 一致使用 `ComtradeQuery`、`ComtradeResponse`、`IngestionDataset`、`StoredIngestion` 與 typed domain exceptions。
- Scope：只完成 Phase 1；AWS Lambda、S3 與 BigQuery 保留給 Phase 2。

