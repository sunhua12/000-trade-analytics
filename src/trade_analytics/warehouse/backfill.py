"""Verified, single-writer S3 to BigQuery raw partition loading."""

import hashlib
import json
import re
import uuid
from datetime import datetime
from decimal import Decimal
from importlib import import_module
from typing import Any

from .gate import verify

BUCKET = "trade-analytics-prod-816079797958-ap-northeast-1-an"
PROJECT = "trade-analytics-508604"
RAW_DATASET = "trade_raw"
KINDS = ("partner_detail", "world_total")
SOURCE_FIELDS = (
    "period",
    "period_start_date",
    "reporter_code",
    "partner_code",
    "flow_code",
    "cmd_code",
    "hs_version",
    "primary_value",
    "net_weight",
    "quantity",
    "ingested_at",
    "source_file",
    "checksum",
    "revision",
)


def source_key(period: str, kind: str, revision: int = 1) -> str:
    if not re.fullmatch(r"20(?:23|24)(?:0[1-9]|1[0-2])", period):
        raise ValueError("period must be in 202301 through 202412")
    if kind not in KINDS or revision < 1:
        raise ValueError("invalid source identity")
    return (
        f"un_comtrade/v2/hs_version=H6/cmd_code=8542/period={period}/"
        f"query_type={kind}/revision={revision}"
    )


def decision(existing: list[dict[str, Any]], revision: int, checksum: str) -> str:
    if not existing:
        return "load"
    versions = {(int(row["revision"]), row["checksum"]) for row in existing}
    if len(versions) != 1:
        raise ValueError("raw partition mixes source versions")
    old_revision, old_checksum = versions.pop()
    if revision < old_revision:
        return "stale_revision"
    if revision == old_revision:
        return "already_loaded" if checksum == old_checksum else "conflict"
    return "load"


def canonical(row: dict[str, Any]) -> tuple[str | None, ...]:
    values = []
    for key in SOURCE_FIELDS:
        value = row.get(key)
        if key in ("primary_value", "net_weight", "quantity") and value is not None:
            value = format(Decimal(str(value)).normalize(), "f")
        if key == "ingested_at" and value is not None:
            value = datetime.fromisoformat(str(value).replace("Z", "+00:00")).isoformat()
        values.append(None if value is None else str(value))
    return tuple(values)


def snapshot_hash(rows: list[dict[str, Any]]) -> str:
    serialized = "\n".join(sorted(json.dumps(canonical(row)) for row in rows))
    return hashlib.sha256(serialized.encode()).hexdigest()


def expected_rows(attested: dict[str, Any], run_id: str) -> list[dict[str, Any]]:
    manifest = attested["manifest"]
    return [
        {
            **row,
            "ingested_at": manifest["ingested_at"],
            "source_file": attested["source_file"],
            "checksum": manifest["checksum"],
            "run_id": run_id,
            "revision": manifest["revision"],
        }
        for row in attested["expected"]
    ]


class RawLoader:
    def __init__(
        self,
        client: Any,
        s3: Any,
        *,
        project: str = PROJECT,
        raw_dataset: str = RAW_DATASET,
    ) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9-]+", project):
            raise ValueError("invalid project")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", raw_dataset):
            raise ValueError("invalid raw dataset")
        self.client, self.s3, self.project, self.raw_dataset = client, s3, project, raw_dataset
        self.jobs: list[dict[str, Any]] = []

    def table(self, kind: str) -> str:
        if kind not in KINDS:
            raise ValueError("invalid kind")
        return f"`{self.project}.{self.raw_dataset}.un_comtrade_{kind}`"

    def query(self, sql: str, params: dict[str, str]) -> list[dict[str, Any]]:
        bigquery = import_module("google.cloud.bigquery")

        job_id = "day11_" + uuid.uuid4().hex
        job = self.client.query(
            sql,
            job_id=job_id,
            job_retry=None,
            location="asia-northeast1",
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter(k, "STRING", v) for k, v in params.items()
                ],
                maximum_bytes_billed=10**9,
            ),
        )
        record = {"job_id": job_id, "params": {k: v for k, v in params.items() if k != "rows"}}
        self.jobs.append(record)
        try:
            result = [dict(row) for row in job.result(timeout=180)]
            record["status"] = "success"
            return result
        except Exception:
            record["status"] = "failed" if job.error_result else "unknown"
            raise

    def source(self, period: str, kind: str, revision: int) -> dict[str, Any]:
        prefix = source_key(period, kind, revision)
        data = self.s3.get_object(Bucket=BUCKET, Key=prefix + "/data.ndjson")["Body"].read()
        manifest = self.s3.get_object(Bucket=BUCKET, Key=prefix + "/manifest.json")["Body"].read()
        return verify(data, manifest, f"s3://{BUCKET}/{prefix}/data.ndjson")

    def existing(self, period: str, kind: str) -> list[dict[str, Any]]:
        sql = f"""
SELECT TO_JSON_STRING(r) payload FROM {self.table(kind)} r
WHERE period_start_date=PARSE_DATE('%Y%m',@period)
  AND cmd_code='8542' AND hs_version='H6'
"""
        return [
            json.loads(row["payload"], parse_float=Decimal)
            for row in self.query(sql, {"period": period})
        ]

    def load(
        self, period: str, kind: str, revision: int = 1, *, rollback_probe: bool = False
    ) -> dict[str, Any]:
        if rollback_probe and not self.raw_dataset.endswith("_fixture"):
            raise ValueError("rollback probe is restricted to fixture datasets")
        attested = self.source(period, kind, revision)
        manifest = attested["manifest"]
        current = self.existing(period, kind)
        action = decision(current, revision, manifest["checksum"])
        run_id = f"day11-{period}-{kind}-r{revision}"
        rows = expected_rows(attested, run_id)
        if action == "already_loaded":
            if {canonical(r) for r in current} != {canonical(r) for r in rows}:
                # Day 6 used a different run id; the source fields still must match.
                raise ValueError("raw snapshot differs from same-revision source")
            return {"period": period, "kind": kind, "status": action, "rows": len(rows)}
        if action != "load":
            raise ValueError(action)

        self.query(
            f"""
ALTER TABLE `{self.project}.{self.raw_dataset}.audit_ingestion_runs`
 ADD COLUMN IF NOT EXISTS contract_fingerprint STRING;
ALTER TABLE `{self.project}.{self.raw_dataset}.audit_ingestion_runs`
 ADD COLUMN IF NOT EXISTS snapshot_hash STRING;
""",
            {},
        )

        old_revision = str(current[0]["revision"]) if current else "0"
        old_checksum = current[0]["checksum"] if current else ""
        event_id = str(uuid.uuid4())
        # The source is already validated byte-for-byte. JSON is only a transport for
        # a single parameterized BigQuery transaction, never trusted as a new source.
        payload = json.dumps(rows, default=str, separators=(",", ":"))
        fields = ",".join(SOURCE_FIELDS) + ",run_id"
        sql = f"""
CREATE TEMP TABLE day11_rows AS
SELECT
 JSON_VALUE(r,'$.period') period,
 PARSE_DATE('%Y-%m-%d',JSON_VALUE(r,'$.period_start_date')) period_start_date,
 JSON_VALUE(r,'$.reporter_code') reporter_code,
 JSON_VALUE(r,'$.partner_code') partner_code,
 JSON_VALUE(r,'$.flow_code') flow_code,
 JSON_VALUE(r,'$.cmd_code') cmd_code,
 JSON_VALUE(r,'$.hs_version') hs_version,
 CAST(JSON_VALUE(r,'$.primary_value') AS NUMERIC) primary_value,
 CAST(JSON_VALUE(r,'$.net_weight') AS NUMERIC) net_weight,
 CAST(JSON_VALUE(r,'$.quantity') AS NUMERIC) quantity,
 TIMESTAMP(JSON_VALUE(r,'$.ingested_at')) ingested_at,
 JSON_VALUE(r,'$.source_file') source_file,
 JSON_VALUE(r,'$.checksum') checksum,
 JSON_VALUE(r,'$.run_id') run_id,
 CAST(JSON_VALUE(r,'$.revision') AS INT64) revision
FROM UNNEST(JSON_QUERY_ARRAY(@rows)) r;
ASSERT (SELECT COUNT(*) FROM day11_rows)=CAST(@row_count AS INT64)
 AS 'normalized row count mismatch';
ASSERT (SELECT SUM(primary_value) FROM day11_rows)=CAST(@amount AS NUMERIC)
 AS 'normalized amount mismatch';
ASSERT (SELECT COUNT(DISTINCT partner_code) FROM day11_rows)=CAST(@row_count AS INT64)
 AS 'duplicate partner grain';
BEGIN TRANSACTION;
ASSERT (SELECT COALESCE(MAX(revision),0) FROM {self.table(kind)}
 WHERE period_start_date=PARSE_DATE('%Y%m',@period) AND cmd_code='8542' AND hs_version='H6')
 =CAST(@old_revision AS INT64) AS 'revision changed during load';
ASSERT (SELECT COUNT(DISTINCT checksum) FROM {self.table(kind)}
 WHERE period_start_date=PARSE_DATE('%Y%m',@period) AND cmd_code='8542' AND hs_version='H6')
 =IF(@old_revision='0',0,1) AS 'checksum identity changed during load';
ASSERT (SELECT COALESCE(MAX(checksum),'') FROM {self.table(kind)}
 WHERE period_start_date=PARSE_DATE('%Y%m',@period) AND cmd_code='8542' AND hs_version='H6')
 =@old_checksum AS 'checksum changed during load';
DELETE FROM {self.table(kind)}
 WHERE period_start_date=PARSE_DATE('%Y%m',@period) AND cmd_code='8542' AND hs_version='H6';
{"ASSERT FALSE AS 'fixture_rollback_probe';" if rollback_probe else ""}
INSERT INTO {self.table(kind)}
 (period,period_start_date,reporter_code,partner_code,flow_code,cmd_code,hs_version,
 primary_value,net_weight,quantity,ingested_at,source_file,checksum,run_id,revision)
SELECT * FROM day11_rows;
ASSERT (SELECT COUNT(*) FROM {self.table(kind)}
 WHERE period_start_date=PARSE_DATE('%Y%m',@period) AND cmd_code='8542' AND hs_version='H6')
 =CAST(@row_count AS INT64) AS 'raw row count mismatch';
ASSERT NOT EXISTS(
 (SELECT {fields} FROM day11_rows EXCEPT DISTINCT
  SELECT {fields} FROM {self.table(kind)} WHERE period_start_date=PARSE_DATE('%Y%m',@period)
  AND cmd_code='8542' AND hs_version='H6')
 UNION ALL
 (SELECT {fields} FROM {self.table(kind)} WHERE period_start_date=PARSE_DATE('%Y%m',@period)
  AND cmd_code='8542' AND hs_version='H6' EXCEPT DISTINCT SELECT {fields} FROM day11_rows)
) AS 'raw full snapshot mismatch';
INSERT INTO `{self.project}.{self.raw_dataset}.audit_ingestion_runs`
 (event_id,run_id,attempt_id,period,query_type,cmd_code,hs_version,revision,
 source_file,manifest_file,checksum,expected_row_count,actual_row_count,
 expected_primary_value_sum,actual_primary_value_sum,status,source_ingested_at,event_at,
 contract_fingerprint,snapshot_hash)
VALUES(@event_id,@run_id,@event_id,@period,@kind,'8542','H6',CAST(@revision AS INT64),
 @source_file,@manifest_file,@checksum,CAST(@row_count AS INT64),CAST(@row_count AS INT64),
 @amount,CAST(@amount AS NUMERIC),'success',TIMESTAMP(@ingested_at),CURRENT_TIMESTAMP(),
 @fingerprint,@snapshot_hash);
COMMIT TRANSACTION;
"""
        params = {
            "rows": payload,
            "period": period,
            "row_count": str(len(rows)),
            "amount": manifest["primary_value_sum"],
            "old_revision": old_revision,
            "old_checksum": old_checksum,
            "event_id": event_id,
            "run_id": run_id,
            "kind": kind,
            "revision": str(revision),
            "source_file": attested["source_file"],
            "manifest_file": attested["manifest_file"],
            "checksum": manifest["checksum"],
            "ingested_at": manifest["ingested_at"],
            "fingerprint": attested["contract_fingerprint"],
            "snapshot_hash": snapshot_hash(rows),
        }
        self.query(sql, params)
        final = self.existing(period, kind)
        if {canonical(r) for r in final} != {canonical(r) for r in rows}:
            raise ValueError("post-commit source snapshot mismatch")
        return {"period": period, "kind": kind, "status": "success", "rows": len(rows)}
