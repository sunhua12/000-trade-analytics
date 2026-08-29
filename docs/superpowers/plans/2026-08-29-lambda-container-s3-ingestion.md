# Lambda Container Image and S3 Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tested AWS Lambda Python 3.11 container that reuses the Phase 1 ingestion package and writes deterministic Raw artifacts to an existing S3 bucket.

**Architecture:** Keep the Phase 1 query, HTTP and validation code unchanged. Add a reusable manifest serializer, an injected S3 adapter with immutable/idempotent writes, and a thin Lambda handler that translates events and environment variables into the existing ingestion service. Package the application with the official AWS Lambda Python base image; the user creates ECR, IAM, Lambda and S3 through AWS Console.

**Tech Stack:** Python 3.11, Pydantic 2, httpx, Tenacity, boto3, pytest, Ruff, mypy, Docker, AWS Lambda Runtime Interface Emulator

**Spec:** `docs/superpowers/specs/2026-08-29-lambda-container-s3-ingestion-design.md`

## Global Constraints

- Runtime and base image are Python 3.11 and `public.ecr.aws/lambda/python:3.11`.
- Default container platform is `linux/amd64`; Lambda must use `x86_64`.
- AWS resources are not created or modified by repository code.
- AWS credentials and API keys must not be stored in Git or the Image.
- Required environment variable is `RAW_BUCKET`; defaults are `RAW_PREFIX=un_comtrade` and the Phase 1 Preview endpoint.
- S3 Raw data is immutable: identical reruns return `already_exists`; conflicting content raises an error.
- Existing Phase 1 behavior and tests must remain green; total ingestion coverage must remain at least 85%.

---

### Task 1: Reusable Artifact Serialization

**Files:**
- Modify: `src/trade_analytics/ingestion/manifest.py`
- Modify: `src/trade_analytics/ingestion/storage.py`
- Modify: `tests/unit/ingestion/test_manifest.py`
- Test: `tests/unit/ingestion/test_storage.py`

**Interfaces:**
- Consumes: `Manifest`, `build_manifest(dataset, data, ingested_at)`, `serialize_ndjson(dataset)`.
- Produces: `serialize_manifest(manifest: Manifest) -> bytes` for local and S3 storage.

- [x] **Step 1: Write the failing manifest serialization test**

Add a test that builds a manifest at a fixed UTC timestamp and asserts `serialize_manifest()` returns UTF-8 JSON with sorted keys, two-space indentation, a trailing newline, string-preserved Decimal, and the expected checksum.

```python
serialized = serialize_manifest(manifest)
payload = json.loads(serialized)
assert serialized.endswith(b"\n")
assert payload["primary_value_sum"] == "300.0"
assert payload["checksum"].startswith("sha256:")
```

- [x] **Step 2: Run the focused test and verify RED**

Run: `.venv/bin/pytest tests/unit/ingestion/test_manifest.py -q`

Expected: collection or import failure because `serialize_manifest` does not exist.

- [x] **Step 3: Implement the serializer and reuse it locally**

Add to `manifest.py`:

```python
def serialize_manifest(manifest: Manifest) -> bytes:
    return (
        json.dumps(
            manifest.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode()
```

Replace the duplicated JSON block in `LocalStorage.write()` with `serialize_manifest(manifest)`.

- [x] **Step 4: Run focused manifest and local storage tests**

Run: `.venv/bin/pytest tests/unit/ingestion/test_manifest.py tests/unit/ingestion/test_storage.py -q`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/trade_analytics/ingestion/manifest.py src/trade_analytics/ingestion/storage.py tests/unit/ingestion/test_manifest.py
git commit -m "refactor: share ingestion artifact serialization"
```

### Task 2: S3 Storage Happy Path and Stable Keys

**Files:**
- Modify: `src/trade_analytics/ingestion/exceptions.py`
- Modify: `pyproject.toml`
- Create: `src/trade_analytics/ingestion/s3_storage.py`
- Create: `tests/unit/ingestion/test_s3_storage.py`

**Interfaces:**
- Consumes: `IngestionDataset`, `serialize_ndjson`, `build_manifest`, `serialize_manifest`.
- Produces:
  - `S3ObjectClient` protocol with `get_object(**kwargs)` and `put_object(**kwargs)`.
  - `StoredS3Ingestion(status, data_uri, manifest_uri, row_count, checksum)`.
  - `S3Storage(bucket: str, client: S3ObjectClient, prefix: str = "un_comtrade", clock=...)`.
  - `S3Storage.write(dataset: IngestionDataset) -> StoredS3Ingestion`.
  - `StorageConflictError(ComtradeError)`.

- [x] **Step 1: Write the failing happy-path test**

Add `boto3>=1.35,<2` to runtime dependencies and run `.venv/bin/pip install -e '.[dev]'` so the test can use the real botocore `ClientError` shape.

Create an in-memory fake client that records `put_object` calls and raises a botocore `ClientError` with code `NoSuchKey` from `get_object` when absent. Assert:

```python
stored = S3Storage(
    bucket="raw-bucket",
    prefix="un_comtrade",
    client=fake_s3,
    clock=lambda: FIXED_TIME,
).write(dataset)

assert stored.status == "success"
assert stored.data_uri == (
    "s3://raw-bucket/un_comtrade/period=202401/"
    "query_type=partner_detail/data.ndjson"
)
assert fake_s3.puts[0]["ContentType"] == "application/x-ndjson"
assert fake_s3.puts[1]["ContentType"] == "application/json"
```

- [x] **Step 2: Run the focused test and verify RED**

Run: `.venv/bin/pytest tests/unit/ingestion/test_s3_storage.py -q`

Expected: import failure because `s3_storage` does not exist.

- [x] **Step 3: Implement the minimal happy path**

Implement normalized prefixes with surrounding slashes removed, stable keys, missing-object detection for `NoSuchKey`, `404` and `NotFound`, and two `put_object` calls with bytes bodies and the required content types. Reject an empty bucket or an empty normalized prefix with `ValueError`.

Use:

```python
@dataclass(frozen=True)
class StoredS3Ingestion:
    status: Literal["success", "already_exists"]
    data_uri: str
    manifest_uri: str
    row_count: int
    checksum: str
```

- [x] **Step 4: Run the focused test**

Run: `.venv/bin/pytest tests/unit/ingestion/test_s3_storage.py -q`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/trade_analytics/ingestion/exceptions.py src/trade_analytics/ingestion/s3_storage.py tests/unit/ingestion/test_s3_storage.py
git commit -m "feat: write ingestion artifacts to S3"
```

### Task 3: S3 Idempotency, Partial Recovery, and Conflict Protection

**Files:**
- Modify: `src/trade_analytics/ingestion/s3_storage.py`
- Modify: `tests/unit/ingestion/test_s3_storage.py`

**Interfaces:**
- Consumes: `S3Storage.write()` and the exact serialized artifacts from Tasks 1–2.
- Produces: immutable rerun behavior and `StorageConflictError` messages containing bucket/key context but no credentials.

- [x] **Step 1: Write failing idempotency and conflict tests**

Add separate tests for:

```python
assert rerun.status == "already_exists"

with pytest.raises(StorageConflictError, match="checksum conflict"):
    storage_with_different_existing_data.write(dataset)
```

Assert that the identical rerun makes no `put_object` calls and a conflict does not mutate fake storage.

- [x] **Step 2: Run focused tests and verify RED**

Run: `.venv/bin/pytest tests/unit/ingestion/test_s3_storage.py -q`

Expected: tests fail because existing objects are overwritten or not compared.

- [x] **Step 3: Implement complete-object idempotency**

When both objects exist, parse the existing manifest as `Manifest`, verify its checksum equals the generated checksum, verify the existing data bytes also hash to that checksum, then return `already_exists`. Raise `StorageConflictError` for invalid JSON, invalid manifest schema, mismatched data or mismatched generated checksum.

- [x] **Step 4: Run focused tests and verify GREEN**

Run: `.venv/bin/pytest tests/unit/ingestion/test_s3_storage.py -q`

Expected: PASS for happy path, rerun and conflicts.

- [x] **Step 5: Write failing partial-object recovery tests**

Add independent tests for:

- Matching data exists and manifest is missing: only manifest is written.
- Matching manifest exists and data is missing: only data is written.
- A lone existing object conflicts: no object is overwritten and `StorageConflictError` is raised.

- [x] **Step 6: Run partial-object tests and verify RED**

Run: `.venv/bin/pytest tests/unit/ingestion/test_s3_storage.py -q`

Expected: at least one partial recovery assertion fails.

- [x] **Step 7: Implement safe partial recovery**

Compare a lone data object's calculated checksum with the generated checksum. Parse and compare a lone manifest's checksum with the generated checksum. Write only the missing object when the existing object matches; otherwise raise `StorageConflictError`.

- [x] **Step 8: Run focused tests and commit**

Run: `.venv/bin/pytest tests/unit/ingestion/test_s3_storage.py -q`

Expected: PASS.

```bash
git add src/trade_analytics/ingestion/s3_storage.py tests/unit/ingestion/test_s3_storage.py
git commit -m "feat: make S3 raw writes idempotent"
```

### Task 4: Lambda Event Adapter and Runtime Composition

**Files:**
- Create: `src/trade_analytics/lambda_handler.py`
- Create: `tests/unit/test_lambda_handler.py`

**Interfaces:**
- Consumes: `ComtradeClient`, `ComtradeQuery`, `IngestionService`, `S3Storage`, `StoredS3Ingestion`.
- Produces:
  - `LambdaEvent(BaseModel)` with `action: Literal["ingest"]`, `period`, `cmd_code="8542"`, `query_type`, optional `run_id`.
  - `run_ingestion(query, *, bucket, prefix, base_url) -> StoredS3Ingestion`.
  - AWS entry point `handler(event: dict[str, object], context: object) -> dict[str, object]`.

- [x] **Step 1: Write failing handler contract tests**

Inject a fake runner through a keyword-only default argument and assert a valid event produces the exact response fields. Add separate tests that reject unknown action, invalid period, unknown query type and missing `RAW_BUCKET` before the runner is called.

```python
result = handler(event, None, runner=fake_runner)
assert result == {
    "status": "success",
    "period": "202401",
    "query_type": "partner_detail",
    "row_count": 2,
    "checksum": "sha256:abc",
    "data_uri": "s3://raw/.../data.ndjson",
    "manifest_uri": "s3://raw/.../manifest.json",
}
```

- [x] **Step 2: Run handler tests and verify RED**

Run: `.venv/bin/pytest tests/unit/test_lambda_handler.py -q`

Expected: import failure because `lambda_handler` does not exist.

- [x] **Step 3: Implement event validation and response mapping**

Use Pydantic with `extra="forbid"`. Read `RAW_BUCKET`, `RAW_PREFIX` and `COMTRADE_BASE_URL` only after event validation. Let validation, Comtrade and storage exceptions propagate so AWS records a failed invocation. Emit one JSON structured log containing `run_id`, period, query type, status, row count and checksum.

- [x] **Step 4: Implement runtime composition**

`run_ingestion()` creates a bounded `httpx.Timeout`, an `httpx.Client`, `ComtradeClient(base_url=base_url)`, `IngestionService`, `boto3.client("s3")` and `S3Storage`. Do not instantiate network clients at module import time.

- [x] **Step 5: Run handler and regression tests**

Run: `.venv/bin/pytest tests/unit/test_lambda_handler.py tests/unit -q`

Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add src/trade_analytics/lambda_handler.py tests/unit/test_lambda_handler.py
git commit -m "feat: add Lambda ingestion handler"
```

### Task 5: Runtime Dependencies and Lambda Docker Image

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Modify: `README.md`

**Interfaces:**
- Consumes: `trade_analytics.lambda_handler.handler`.
- Produces: local Image `trade-analytics-ingestion:phase2` for `linux/amd64`.

- [x] **Step 1: Verify runtime dependency and handler imports**

With the S3 task's runtime dependencies installed, run:

```bash
.venv/bin/python -c "import boto3; from trade_analytics.lambda_handler import handler"
```

Expected: both imports succeed.

- [x] **Step 2: Refresh the project installation in the venv**

Run: `.venv/bin/pip install -e '.[dev]'`

Expected: boto3 and botocore are installed only inside `.venv`.

- [x] **Step 3: Create Dockerfile and build context exclusions**

Create:

```dockerfile
FROM public.ecr.aws/lambda/python:3.11

COPY pyproject.toml README.md ${LAMBDA_TASK_ROOT}/
COPY src ${LAMBDA_TASK_ROOT}/src
RUN python -m pip install --no-cache-dir . --target ${LAMBDA_TASK_ROOT}

CMD ["trade_analytics.lambda_handler.handler"]
```

`.dockerignore` must exclude `.git`, `.venv`, `.env*`, caches, coverage, `data`, tests, docs and user-owned project notes.

- [x] **Step 4: Document local build and smoke invocation**

Add commands using:

```bash
docker build --platform linux/amd64 -t trade-analytics-ingestion:phase2 .
docker run --platform linux/amd64 --rm -p 9000:8080 \
  -e RAW_BUCKET=local-smoke-only trade-analytics-ingestion:phase2
curl -sS -X POST \
  http://localhost:9000/2015-03-31/functions/function/invocations \
  -d '{"action":"unsupported","period":"202401","query_type":"partner_detail"}'
```

The expected response is a controlled Pydantic validation error and no Comtrade/S3 request.

- [x] **Step 5: Run static and unit verification**

Run:

```bash
.venv/bin/ruff format --check src tests ingest.py
.venv/bin/ruff check src tests ingest.py
.venv/bin/mypy src ingest.py
.venv/bin/pytest tests/unit -q --cov=trade_analytics.ingestion --cov-report=term-missing --cov-fail-under=85
```

Expected: all commands exit 0.

- [x] **Step 6: Build and inspect the Image**

Run:

```bash
docker build --platform linux/amd64 -t trade-analytics-ingestion:phase2 .
docker image inspect trade-analytics-ingestion:phase2
```

Expected: build exits 0 and inspection reports `Architecture=amd64` with Lambda handler command.

- [x] **Step 7: Run container smoke invocation and commit**

Start the container, invoke the invalid event, verify the expected function error, then stop the container. Commit:

```bash
git add pyproject.toml Dockerfile .dockerignore README.md
git commit -m "build: package ingestion as Lambda image"
```

### Task 6: AWS Console Deployment Guide

**Files:**
- Create: `docs/aws-console-lambda-deployment.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: Image `trade-analytics-ingestion:phase2`, handler event contract and S3 key policy.
- Produces: manual Console checklist plus only the Docker/ECR commands that cannot be performed inside Lambda/S3 Console setup.

- [x] **Step 1: Write the deployment guide**

Document exact Console fields and safe defaults:

- S3: Block Public Access on; default SSE-S3 encryption; versioning on; bucket name and region recorded.
- ECR: private repository; tag immutability on; scan on push on.
- IAM: CloudWatch Logs plus `s3:GetObject` and `s3:PutObject` restricted to `arn:aws:s3:::<bucket>/un_comtrade/*`.
- Lambda: container image, `x86_64`, 512 MB, 120-second timeout, reserved concurrency 1.
- Environment: `RAW_BUCKET`, `RAW_PREFIX=un_comtrade`; optionally `COMTRADE_BASE_URL`.
- Test events for both query types and expected S3 keys.
- ECR authentication/tag/push commands with placeholders that cannot be mistaken for real credentials.

- [x] **Step 2: Add README navigation and operational warnings**

Link the guide, explain that the current default still uses Preview API, and state that a successful local invalid-event smoke test does not verify AWS permissions or a real S3 write.

- [x] **Step 3: Verify documentation and repository hygiene**

Run:

```bash
rg -n "AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|BEGIN PRIVATE KEY" . \
  --glob '!trade-analytics.md' --glob '!trade-analytics-spec.md'
git diff --check
git status --short
```

Expected: no credential material, no whitespace errors, and only intended files plus the two pre-existing user notes.

- [x] **Step 4: Run final verification**

Run the complete Ruff, mypy and unit test commands again, rebuild the Image without cache, inspect it, and repeat the Runtime Interface Emulator invalid-event smoke test.

- [x] **Step 5: Commit**

```bash
git add docs/aws-console-lambda-deployment.md README.md
git commit -m "docs: add AWS Console Lambda deployment guide"
```

### Task 7: Final Review and Delivery

**Files:**
- Modify: `docs/superpowers/plans/2026-08-29-lambda-container-s3-ingestion.md` checkbox states only.

**Interfaces:**
- Consumes: all implementation and verification outputs.
- Produces: verified branch and exact artifact/Image information for the user.

- [x] **Step 1: Review the diff against every spec section**

Run: `git diff main...HEAD --stat` and `git diff main...HEAD`.

Confirm event contract, environment variables, S3 keys, idempotency, Docker architecture, no IaC and Console guide coverage.

- [x] **Step 2: Run fresh completion verification**

Run all unit tests, integration tests when network approval is available, Ruff, mypy, Docker no-cache build, Image inspection and container smoke invocation. Record exact pass counts, coverage and Image ID.

- [x] **Step 3: Mark plan checkboxes complete and commit**

Update only this plan's checkbox states and commit:

```bash
git add docs/superpowers/plans/2026-08-29-lambda-container-s3-ingestion.md
git commit -m "docs: complete Lambda container implementation plan"
```

- [x] **Step 4: Hand off without changing AWS state**

Report the branch name, Image tag/ID, commands for ECR push, Console guide path, verification evidence, and any steps requiring the user's AWS account. Do not push the Image, create resources, merge branches or alter AWS without a separate explicit request.
