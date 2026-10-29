"""One multi-market loader with transactional full-source replacement."""

import json
import re
import uuid
from collections.abc import Iterable
from importlib import import_module
from typing import Any

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


def sql_projection(fields: Iterable[str], types: dict[str, str]) -> list[str]:
    columns = []
    for field in fields:
        value = f"JSON_VALUE(r,'$.{field}')"
        if field in types:
            value = f"CAST({value} AS {types[field]})"
        columns.append(f"{value} AS {field}")
    return columns


def decision(existing: dict[str, Any] | None, revision: int, checksum: str) -> str:
    if existing is None:
        return "load"
    old_revision, old_checksum = int(existing["revision"]), existing["checksum"]
    if revision < old_revision:
        return "stale_revision"
    if revision == old_revision:
        return "already_loaded" if checksum == old_checksum else "conflict"
    return "load"


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
        *,
        project: str,
        raw_dataset: str,
        location: str = "asia-northeast1",
        maximum_bytes_billed: int = 10**9,
    ) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9-]+", project):
            raise ValueError("invalid project")
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", raw_dataset):
            raise ValueError("invalid raw dataset")
        self.client, self.project, self.raw_dataset = client, project, raw_dataset
        self.location = location
        self.maximum_bytes_billed = maximum_bytes_billed
        self.jobs: list[dict[str, Any]] = []

    def table(self, kind: str) -> str:
        return f"`{self.project}.{self.raw_dataset}.un_comtrade_{kind}`"

    def query(self, sql: str, params: dict[str, str]) -> list[dict[str, Any]]:
        bigquery = import_module("google.cloud.bigquery")

        job_id = "trade_" + uuid.uuid4().hex
        job = self.client.query(
            sql,
            job_id=job_id,
            job_retry=None,
            location=self.location,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter(k, "STRING", v) for k, v in params.items()
                ],
                maximum_bytes_billed=self.maximum_bytes_billed,
            ),
        )
        record = {"job_id": job_id, "period": params.get("period")}
        self.jobs.append(record)
        try:
            result = [dict(row) for row in job.result(timeout=180)]
            record["status"] = "success"
            return result
        except Exception:
            record["status"] = "failed" if job.error_result else "unknown"
            raise

    def load_month(self, period: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
        current: dict[tuple[str, str, str], dict[str, Any]] = {}
        for kind in KINDS:
            sql = f"""SELECT reporter_code,cmd_code,
                MAX(revision) revision, MAX(checksum) checksum, COUNT(*) row_count,
                COUNT(DISTINCT revision) revisions, COUNT(DISTINCT checksum) checksums
                FROM {self.table(kind)} WHERE period_start_date=PARSE_DATE('%Y%m',@period)
                AND flow_code='M'
                AND cmd_code IN ('854231','854232','854233','854239','854290')
                GROUP BY reporter_code,cmd_code"""
            for row in self.query(sql, {"period": period}):
                if row["revisions"] != 1 or row["checksums"] != 1:
                    raise ValueError("raw partition mixes source versions")
                current[(kind, row["reporter_code"], row["cmd_code"])] = row
        rows: list[dict[str, Any]] = []
        metadata: list[dict[str, Any]] = []
        seen_sources = set()
        for source in sources:
            manifest = source["manifest"]
            reporter = str(manifest["request_parameters"]["reporterCode"])
            kind = manifest["query_type"]
            key = (kind, reporter, manifest["cmd_code"])
            if key in seen_sources:
                raise ValueError("duplicate source partition in batch")
            seen_sources.add(key)
            if manifest["period"] != period:
                raise ValueError("batch contains a different month")
            existing = current.get(key)
            action = decision(existing, manifest["revision"], manifest["checksum"])
            run_id = f"multi-{period}-{reporter}-{manifest['cmd_code']}-r{manifest['revision']}"
            expected = expected_rows(source, run_id)
            if action == "already_loaded":
                if existing is None or existing["row_count"] != len(expected):
                    raise ValueError("same-revision row count differs from warehouse")
                continue
            if action != "load":
                raise ValueError(action)
            rows.extend({**row, "kind": kind} for row in expected)
            metadata.append(
                {
                    "kind": kind,
                    "reporter_code": reporter,
                    "cmd_code": manifest["cmd_code"],
                    "hs_version": manifest["hs_version"],
                    "revision": manifest["revision"],
                    "old_count": existing["row_count"] if existing else 0,
                    "old_revision": existing["revision"] if existing else 0,
                    "old_checksum": existing["checksum"] if existing else "",
                    "checksum": manifest["checksum"],
                    "row_count": len(expected),
                    "amount": manifest["primary_value_sum"],
                    "source_file": source["source_file"],
                    "manifest_file": source["manifest_file"],
                    "ingested_at": manifest["ingested_at"],
                    "event_id": str(uuid.uuid4()),
                    "run_id": run_id,
                }
            )
        if not metadata:
            return {"period": period, "status": "already_loaded", "sources": len(sources)}
        fields = ",".join(SOURCE_FIELDS) + ",run_id"
        row_sql = sql_projection(
            (*SOURCE_FIELDS, "run_id", "kind"),
            {
                "period_start_date": "DATE",
                "primary_value": "NUMERIC",
                "net_weight": "NUMERIC",
                "quantity": "NUMERIC",
                "revision": "INT64",
                "ingested_at": "TIMESTAMP",
            },
        )
        meta_sql = sql_projection(
            metadata[0],
            {
                "revision": "INT64",
                "old_revision": "INT64",
                "row_count": "INT64",
                "old_count": "INT64",
                "amount": "NUMERIC",
            },
        )
        sql = (
            "CREATE TEMP TABLE incoming AS SELECT "
            + ",".join(row_sql)
            + " FROM UNNEST(JSON_QUERY_ARRAY(@rows)) r;\n"
            + "CREATE TEMP TABLE sources AS SELECT "
            + ",".join(meta_sql)
            + " FROM UNNEST(JSON_QUERY_ARRAY(@sources)) r;\nBEGIN TRANSACTION;\n"
        )
        identity = "r.reporter_code=s.reporter_code AND r.cmd_code=s.cmd_code AND r.flow_code='M'"
        sql += """
ASSERT NOT EXISTS(SELECT 1 FROM sources s WHERE
 (SELECT COUNT(*) FROM incoming r WHERE r.kind=s.kind AND r.reporter_code=s.reporter_code
  AND r.cmd_code=s.cmd_code AND r.hs_version=s.hs_version) != s.row_count OR
 (SELECT SUM(primary_value) FROM incoming r WHERE r.kind=s.kind
  AND r.reporter_code=s.reporter_code AND r.cmd_code=s.cmd_code
  AND r.hs_version=s.hs_version) != s.amount OR
 (SELECT COUNT(DISTINCT partner_code) FROM incoming r WHERE r.kind=s.kind
  AND r.reporter_code=s.reporter_code AND r.cmd_code=s.cmd_code
  AND r.hs_version=s.hs_version) != s.row_count
) AS 'normalized source grain, count or sum mismatch';
"""
        for kind in KINDS:
            table = self.table(kind)
            scope = f"r.period_start_date=PARSE_DATE('%Y%m',@period) AND {identity}"
            sql += f"""
ASSERT NOT EXISTS (SELECT 1 FROM sources s WHERE s.kind='{kind}' AND (
 (SELECT COUNT(*) FROM {table} r WHERE {scope}) != s.old_count OR
 (SELECT COUNT(DISTINCT revision) FROM {table} r WHERE {scope}) != IF(s.old_revision=0,0,1) OR
 (SELECT COALESCE(MAX(revision),0) FROM {table} r WHERE {scope}) != s.old_revision OR
 (SELECT COUNT(DISTINCT checksum) FROM {table} r WHERE {scope}) != IF(s.old_revision=0,0,1) OR
 (SELECT COALESCE(MAX(checksum),'') FROM {table} r WHERE {scope}) != s.old_checksum
)) AS 'source changed during load';
DELETE FROM {table} r WHERE r.period_start_date=PARSE_DATE('%Y%m',@period)
 AND EXISTS(SELECT 1 FROM sources s WHERE s.kind='{kind}' AND {identity});
INSERT INTO {table} ({fields}) SELECT {fields} FROM incoming WHERE kind='{kind}';
"""
        sql += f"""
INSERT INTO `{self.project}.{self.raw_dataset}.audit_ingestion_runs`
 (event_id,run_id,attempt_id,period,query_type,cmd_code,hs_version,revision,
 source_file,manifest_file,checksum,expected_row_count,actual_row_count,
 expected_primary_value_sum,actual_primary_value_sum,status,source_ingested_at,event_at)
SELECT event_id,run_id,event_id,@period,kind,cmd_code,hs_version,revision,
 source_file,manifest_file,checksum,row_count,row_count,CAST(amount AS STRING),amount,'success',
 TIMESTAMP(ingested_at),CURRENT_TIMESTAMP() FROM sources;
COMMIT TRANSACTION;
"""
        self.query(
            sql,
            {
                "period": period,
                "rows": json.dumps(rows, default=str),
                "sources": json.dumps(metadata, default=str),
            },
        )
        return {
            "period": period,
            "status": "success",
            "sources": len(metadata),
            "rows": len(rows),
            "loaded": [
                {k: m[k] for k in ("reporter_code", "cmd_code", "revision", "row_count")}
                for m in metadata
            ],
        }
