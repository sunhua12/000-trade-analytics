"""Atomically load all verified market/product sources for one month in one job."""

import json
import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any

from trade_analytics.warehouse.loader import (
    KINDS,
    SOURCE_FIELDS,
    RawLoader,
    canonical,
    decision,
    expected_rows,
    snapshot_hash,
)


class BatchRawLoader(RawLoader):
    def load_month(self, period: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
        current: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for kind in KINDS:
            sql = f"""SELECT TO_JSON_STRING(r) payload FROM {self.table(kind)} r
            WHERE period_start_date=PARSE_DATE('%Y%m',@period)
              AND cmd_code IN ('854231','854232','854233','854239','854290')
              AND flow_code='M'"""
            for result in self.query(sql, {"period": period}):
                row = json.loads(result["payload"], parse_float=Decimal)
                current[(kind, row["reporter_code"], row["cmd_code"], row["hs_version"])].append(
                    row
                )
        rows: list[dict[str, Any]] = []
        metadata: list[dict[str, Any]] = []
        seen_sources = set()
        for source in sources:
            manifest = source["manifest"]
            reporter = str(manifest["request_parameters"]["reporterCode"])
            kind = manifest["query_type"]
            key = (kind, reporter, manifest["cmd_code"], manifest["hs_version"])
            if key in seen_sources:
                raise ValueError("duplicate source partition in batch")
            seen_sources.add(key)
            if manifest["period"] != period:
                raise ValueError("batch contains a different month")
            existing = current[key]
            action = decision(existing, manifest["revision"], manifest["checksum"])
            run_id = f"multi-{period}-{reporter}-{manifest['cmd_code']}-r{manifest['revision']}"
            expected = expected_rows(source, run_id)
            if action == "already_loaded":
                if len(existing) != len(expected) or {canonical(r) for r in existing} != {
                    canonical(r) for r in expected
                }:
                    raise ValueError("same-revision source differs from warehouse")
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
                    "old_revision": existing[0]["revision"] if existing else 0,
                    "old_checksum": existing[0]["checksum"] if existing else "",
                    "checksum": manifest["checksum"],
                    "row_count": len(expected),
                    "amount": manifest["primary_value_sum"],
                    "source_file": source["source_file"],
                    "manifest_file": source["manifest_file"],
                    "ingested_at": manifest["ingested_at"],
                    "fingerprint": source["contract_fingerprint"],
                    "snapshot_hash": snapshot_hash(expected),
                    "event_id": str(uuid.uuid4()),
                    "run_id": run_id,
                }
            )
        if not metadata:
            return {"period": period, "status": "already_loaded", "sources": len(sources)}
        fields = ",".join(SOURCE_FIELDS) + ",run_id"
        row_sql = []
        for field in (*SOURCE_FIELDS, "run_id", "kind"):
            value = f"JSON_VALUE(r,'$.{field}')"
            if field == "period_start_date":
                value = f"CAST({value} AS DATE)"
            elif field in ("primary_value", "net_weight", "quantity"):
                value = f"CAST({value} AS NUMERIC)"
            elif field == "revision":
                value = f"CAST({value} AS INT64)"
            elif field == "ingested_at":
                value = f"CAST({value} AS TIMESTAMP)"
            row_sql.append(f"{value} AS {field}")
        meta_sql = []
        for field in metadata[0]:
            value = f"JSON_VALUE(r,'$.{field}')"
            if field in ("revision", "old_revision", "row_count"):
                value = f"CAST({value} AS INT64)"
            elif field == "amount":
                value = f"CAST({value} AS NUMERIC)"
            meta_sql.append(f"{value} AS {field}")
        sql = (
            "CREATE TEMP TABLE incoming AS SELECT "
            + ",".join(row_sql)
            + " FROM UNNEST(JSON_QUERY_ARRAY(@rows)) r;\n"
            + "CREATE TEMP TABLE sources AS SELECT "
            + ",".join(meta_sql)
            + " FROM UNNEST(JSON_QUERY_ARRAY(@sources)) r;\nBEGIN TRANSACTION;\n"
        )
        identity = (
            "r.reporter_code=s.reporter_code AND r.cmd_code=s.cmd_code "
            "AND r.hs_version=s.hs_version AND r.flow_code='M'"
        )
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
 (SELECT COALESCE(MAX(revision),0) FROM {table} r WHERE {scope}) != s.old_revision OR
 (SELECT COUNT(DISTINCT checksum) FROM {table} r WHERE {scope}) != IF(s.old_revision=0,0,1) OR
 (SELECT COALESCE(MAX(checksum),'') FROM {table} r WHERE {scope}) != s.old_checksum
)) AS 'source changed during load';
DELETE FROM {table} r WHERE r.period_start_date=PARSE_DATE('%Y%m',@period)
 AND EXISTS(SELECT 1 FROM sources s WHERE s.kind='{kind}' AND {identity});
INSERT INTO {table} ({fields}) SELECT {fields} FROM incoming WHERE kind='{kind}';
ASSERT NOT EXISTS (
 (SELECT {fields} FROM incoming WHERE kind='{kind}' EXCEPT DISTINCT
  SELECT {",".join("r." + field for field in (*SOURCE_FIELDS, "run_id"))} FROM {table} r
  WHERE r.period_start_date=PARSE_DATE('%Y%m',@period)
    AND EXISTS(SELECT 1 FROM sources s WHERE s.kind='{kind}' AND {identity}))
 UNION ALL
 (SELECT {",".join("r." + field for field in (*SOURCE_FIELDS, "run_id"))} FROM {table} r
  WHERE r.period_start_date=PARSE_DATE('%Y%m',@period)
    AND EXISTS(SELECT 1 FROM sources s WHERE s.kind='{kind}' AND {identity})
  EXCEPT DISTINCT SELECT {fields} FROM incoming WHERE kind='{kind}')
) AS 'raw full snapshot mismatch';
"""
        sql += f"""
INSERT INTO `{self.project}.{self.raw_dataset}.audit_ingestion_runs`
 (event_id,run_id,attempt_id,period,query_type,cmd_code,hs_version,revision,
 source_file,manifest_file,checksum,expected_row_count,actual_row_count,
 expected_primary_value_sum,actual_primary_value_sum,status,source_ingested_at,event_at,
 contract_fingerprint,snapshot_hash)
SELECT event_id,run_id,event_id,@period,kind,cmd_code,hs_version,revision,
 source_file,manifest_file,checksum,row_count,row_count,CAST(amount AS STRING),amount,'success',
 TIMESTAMP(ingested_at),CURRENT_TIMESTAMP(),fingerprint,snapshot_hash FROM sources;
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
        return {"period": period, "status": "success", "sources": len(metadata), "rows": len(rows)}
