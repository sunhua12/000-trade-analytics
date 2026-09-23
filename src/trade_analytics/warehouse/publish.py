"""Single-writer BigQuery publisher: freeze -> persistent audit -> guarded transaction.
Only this program owns the release tables. Ordinary dbt builds never replace them.
"""

import json
import re
import uuid
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import Any

from .quality import assess, partition

CANDIDATE = "mart_us_semiconductor_supply_chain_candidate"
PUBLISHED = "mart_us_semiconductor_supply_chain"


def identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", value):
        raise ValueError("Invalid BigQuery identifier")
    return value


class Publisher:
    """Use one writer per release dataset; orchestration concurrency must remain one."""

    def __init__(self, client: Any, project: str, models: str, raw: str, release: str) -> None:
        self.client = client
        self.project, self.models, self.raw, self.release = map(
            identifier, (project, models, raw, release)
        )
        if release in (raw, models):
            raise ValueError("Release dataset must be separate from raw and models")
        self.jobs: list[dict[str, Any]] = []

    def table(self, dataset: str, name: str) -> str:
        return f"`{self.project}.{identifier(dataset)}.{identifier(name)}`"

    def query(self, sql: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        bigquery = import_module("google.cloud.bigquery")
        params = [
            bigquery.ScalarQueryParameter(k, "STRING", v) for k, v in (parameters or {}).items()
        ]
        job = self.client.query(
            sql,
            job_config=bigquery.QueryJobConfig(query_parameters=params, maximum_bytes_billed=10**9),
        )
        entry = {"job_id": job.job_id, "sql": sql, "parameters": parameters or {}}
        self.jobs.append(entry)
        try:
            result = [dict(r) for r in job.result(timeout=180)]
            entry["result"] = "success"
            return result
        except Exception:
            # A client timeout is not proof the warehouse transaction rolled back.
            entry["result"] = "failed" if job.error_result else "unknown"
            raise

    def initialize(self) -> None:
        def t(name: str) -> str:
            return self.table(self.release, name)

        self.query(f"""
CREATE SCHEMA IF NOT EXISTS `{self.project}.{self.release}` OPTIONS(location='asia-northeast1');
CREATE TABLE IF NOT EXISTS {t("candidate_batches")}
PARTITION BY period_start_date CLUSTER BY candidate_batch_id AS
SELECT c.*, CAST(NULL AS STRING) candidate_batch_id FROM {self.table(self.models, CANDIDATE)}
 c WHERE FALSE;
CREATE TABLE IF NOT EXISTS {t("source_attestations")} (attestation_json STRING, verified_at
 TIMESTAMP);
CREATE TABLE IF NOT EXISTS {t("batch_inputs")} (
 candidate_batch_id STRING, period STRING, cmd_code STRING, hs_version STRING,
 inputs_json STRING, candidate_hash STRING, frozen_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS {t("quality_audit_history")} (
 run_id STRING, candidate_batch_id STRING, period STRING, cmd_code STRING, hs_version STRING,
 status STRING, reason_codes ARRAY<STRING>, audit_json STRING, candidate_hash STRING,
 tested_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS {t("publication_attempts")} (
 attempt_id STRING, run_id STRING, period STRING, cmd_code STRING, hs_version STRING,
 publish_status STRING, attempted_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS {t(PUBLISHED)}
PARTITION BY period_start_date CLUSTER BY partner_code, cmd_code AS
SELECT c.*, CAST(NULL AS STRING) quality_status, CAST(NULL AS TIMESTAMP) published_at,
 CAST(NULL AS STRING) published_run_id FROM {t("candidate_batches")} c WHERE FALSE;
CREATE OR REPLACE VIEW {t("audit_world_reconciliation")} AS
SELECT a.* EXCEPT(audit_json),
 SAFE_CAST(JSON_VALUE(audit_json,'$.partner_sum') AS NUMERIC) partner_sum,
 SAFE_CAST(JSON_VALUE(audit_json,'$.country_sum') AS NUMERIC) country_sum,
 SAFE_CAST(JSON_VALUE(audit_json,'$.world_total') AS NUMERIC) world_total,
 SAFE_CAST(JSON_VALUE(audit_json,'$.difference') AS NUMERIC) difference,
 SAFE_CAST(JSON_VALUE(audit_json,'$.difference_rate') AS NUMERIC) difference_rate,
 SAFE_CAST(JSON_VALUE(audit_json,'$.country_coverage') AS NUMERIC) country_coverage,
 audit_json FROM {t("quality_audit_history")} a;
CREATE OR REPLACE VIEW {t("candidate_quality")} AS
SELECT c.*,a.status quality_status,a.reason_codes,a.tested_at
FROM {t("candidate_batches")} c JOIN {t("quality_audit_history")} a
 ON c.candidate_batch_id=a.candidate_batch_id;
CREATE OR REPLACE VIEW {t("publication_quality_summary")} AS
WITH latest AS (
 SELECT * FROM {t("quality_audit_history")}
 QUALIFY ROW_NUMBER() OVER(PARTITION BY period,cmd_code,hs_version ORDER BY tested_at
 DESC,run_id DESC)=1
), published AS (
 SELECT period,cmd_code,hs_version,ANY_VALUE(published_run_id) published_run_id,
 MAX(published_at) published_at,ANY_VALUE(quality_status) published_quality_status
 FROM {t(PUBLISHED)} GROUP BY 1,2,3
), attempts AS (
 SELECT * FROM {t("publication_attempts")}
 QUALIFY ROW_NUMBER() OVER(PARTITION BY period,cmd_code,hs_version ORDER BY attempted_at
 DESC,attempt_id DESC)=1
)
SELECT l.period,l.cmd_code,l.hs_version,l.run_id latest_run_id,l.status latest_quality_status,
 l.reason_codes,l.tested_at
 latest_tested_at,p.published_run_id,p.published_at,p.published_quality_status,
 a.run_id latest_publish_run_id,a.publish_status latest_publish_status,
 a.attempted_at latest_attempted_at
FROM latest l LEFT JOIN published p USING(period,cmd_code,hs_version)
LEFT JOIN attempts a USING(period,cmd_code,hs_version);
""")

    def freeze(self, run_id: str, scope: dict[str, str]) -> dict[str, Any]:
        def t(name: str) -> str:
            return self.table(self.release, name)

        match = (
            "period_start_date=PARSE_DATE('%Y%m',@period) "
            "AND cmd_code=@cmd_code AND hs_version=@hs_version"
        )
        params = {"run_id": run_id, **{k: scope[k] for k in ("period", "cmd_code", "hs_version")}}
        saved = self.query(
            f"""
BEGIN TRANSACTION;
IF NOT EXISTS(SELECT 1 FROM {t("batch_inputs")} WHERE candidate_batch_id=@run_id) THEN
 INSERT INTO {t("candidate_batches")}
 SELECT c.*,@run_id FROM {self.table(self.models, CANDIDATE)} c WHERE {match};
 INSERT INTO {t("batch_inputs")}
 SELECT @run_id,@period,@cmd_code,@hs_version,
 TO_JSON_STRING(STRUCT(
  ARRAY(SELECT AS STRUCT c.* EXCEPT(candidate_batch_id) FROM {t("candidate_batches")} c WHERE
 candidate_batch_id=@run_id) AS candidate,
  ARRAY(SELECT AS STRUCT * FROM {self.table(self.raw, "un_comtrade_partner_detail")} WHERE
 {match}) AS detail,
  ARRAY(SELECT AS STRUCT * FROM {self.table(self.raw, "un_comtrade_world_total")} WHERE
 {match}) AS world,
  ARRAY(SELECT PARSE_JSON(TO_JSON_STRING(a)) FROM {self.table(self.raw, "audit_ingestion_runs")} a
        WHERE period=@period AND cmd_code=@cmd_code AND hs_version=@hs_version
        UNION ALL SELECT PARSE_JSON(attestation_json) FROM {t("source_attestations")}
        WHERE JSON_VALUE(attestation_json,'$.period')=@period) AS loads
  )),
 (SELECT TO_HEX(SHA256(COALESCE(STRING_AGG(TO_JSON_STRING(c),'\\n' ORDER BY TO_JSON_STRING(c)),'')))
  FROM {t("candidate_batches")} c WHERE candidate_batch_id=@run_id),CURRENT_TIMESTAMP();
END IF;
COMMIT TRANSACTION;
SELECT * FROM {t("batch_inputs")} WHERE candidate_batch_id=@run_id;
""",
            params,
        )
        if len(saved) != 1 or any(
            saved[0][k] != scope[k] for k in ("period", "cmd_code", "hs_version")
        ):
            raise ValueError("Run id already belongs to another partition or duplicated")
        return saved[0]

    def audit(self, run_id: str, period: str) -> dict[str, Any]:
        scope = partition(period)
        audit_table = self.table(self.release, "quality_audit_history")
        existing = self.query(
            f"SELECT * FROM {audit_table} WHERE run_id=@run_id", {"run_id": run_id}
        )
        if existing:
            if len(existing) != 1 or existing[0]["period"] != period:
                raise ValueError("Run id reused for another partition")
            return existing[0]
        try:
            frozen = self.freeze(run_id, scope)
            # BigQuery serializes wide exact NUMERIC values as strings; parse others as Decimal.
            from decimal import Decimal

            result = assess(json.loads(frozen["inputs_json"], parse_float=Decimal), scope)
            candidate_hash = frozen["candidate_hash"]
        except Exception:
            # Persist a failure even when upstream candidate or source access is unavailable.
            result = assess({}, scope)
            result["reason_codes"] = ["upstream_snapshot_failed"]
            candidate_hash = None
            self._save_audit(run_id, result, candidate_hash)
            raise
        return self._save_audit(run_id, result, candidate_hash)

    def _save_audit(
        self, run_id: str, result: dict[str, Any], candidate_hash: str | None
    ) -> dict[str, Any]:
        saved = self.query(
            f"""
INSERT INTO {self.table(self.release, "quality_audit_history")}
SELECT @run_id,@run_id,@period,@cmd_code,@hs_version,@status,
 JSON_VALUE_ARRAY(@audit,'$.reason_codes'),@audit,@hash,CURRENT_TIMESTAMP()
FROM UNNEST([1])
WHERE NOT EXISTS(SELECT 1 FROM {self.table(self.release, "quality_audit_history")}
 WHERE run_id=@run_id);
SELECT * FROM {self.table(self.release, "quality_audit_history")} WHERE run_id=@run_id;
""",
            {
                "run_id": run_id,
                "period": result["period"],
                "cmd_code": result["cmd_code"],
                "hs_version": result["hs_version"],
                "status": result["status"],
                "audit": json.dumps(result, default=str, sort_keys=True),
                "hash": candidate_hash,
            },
        )

        return saved[0]

    def publish(self, run_id: str, period: str, *, rollback_probe: bool = False) -> str:
        scope = partition(period)

        def t(name: str) -> str:
            return self.table(self.release, name)

        if rollback_probe and not self.release.endswith("_fixture"):
            raise ValueError("Fault injection is restricted to fixture datasets")
        params = {
            "run_id": run_id,
            "attempt_id": str(uuid.uuid4()),
            **{k: scope[k] for k in ("period", "cmd_code", "hs_version")},
        }
        match = "period=@period AND cmd_code=@cmd_code AND hs_version=@hs_version"
        sql = f"""
BEGIN TRANSACTION;
ASSERT (SELECT COUNT(*)=1 FROM {t("quality_audit_history")} WHERE run_id=@run_id AND {match}
 AND candidate_batch_id=@run_id AND status IN ('PASS','WARN')) AS 'gate_missing_or_failed';
ASSERT (SELECT COUNT(*)=1 FROM {t("batch_inputs")} WHERE candidate_batch_id=@run_id AND
 {match}) AS 'batch_mismatch';
ASSERT (SELECT candidate_hash FROM {t("quality_audit_history")} WHERE run_id=@run_id) =
 (SELECT TO_HEX(SHA256(COALESCE(STRING_AGG(TO_JSON_STRING(c),'\\n' ORDER BY TO_JSON_STRING(c)),'')))
 FROM {t("candidate_batches")} c WHERE candidate_batch_id=@run_id) AS 'candidate_changed';
ASSERT (SELECT COUNT(*)>0 AND COUNT(*)=COUNT(DISTINCT partner_code)
 AND COUNTIF(NOT ({match}))=0
 FROM {t("candidate_batches")} WHERE candidate_batch_id=@run_id) AS 'candidate_grain';
IF NOT EXISTS(SELECT 1 FROM {t("publication_attempts")} WHERE run_id=@run_id AND
 publish_status='published') THEN
 ASSERT NOT EXISTS(
 SELECT 1 FROM {t("quality_audit_history")} a JOIN {t("publication_attempts")} p USING(run_id)
 WHERE a.period=@period AND a.cmd_code=@cmd_code AND a.hs_version=@hs_version AND
 p.publish_status='published'
 AND a.tested_at>(SELECT tested_at FROM {t("quality_audit_history")} WHERE run_id=@run_id)
 ) AS 'superseded_batch';
 DELETE FROM {t(PUBLISHED)} WHERE {match};
 {"ASSERT FALSE AS 'fixture_rollback_probe';" if rollback_probe else ""}
 INSERT INTO {t(PUBLISHED)}
 SELECT c.*,a.status,CURRENT_TIMESTAMP(),@run_id FROM {t("candidate_batches")} c
 JOIN {t("quality_audit_history")} a ON c.candidate_batch_id=a.run_id
 WHERE c.candidate_batch_id=@run_id;
 INSERT INTO {t("publication_attempts")}
 VALUES(@attempt_id,@run_id,@period,@cmd_code,@hs_version,'published',CURRENT_TIMESTAMP());
ELSE
 INSERT INTO {t("publication_attempts")}
 VALUES(@attempt_id,@run_id,@period,@cmd_code,@hs_version,'already_published',CURRENT_TIMESTAMP());
END IF;
COMMIT TRANSACTION;
"""
        try:
            self.query(sql, params)
            return "published"
        except Exception:
            outcome = (
                "failed" if self.jobs and self.jobs[-1].get("result") == "failed" else "unknown"
            )
            self.query(
                f"""
INSERT INTO {t("publication_attempts")}
 VALUES(@attempt_id,@run_id,@period,@cmd_code,@hs_version,@outcome,CURRENT_TIMESTAMP())
                """,
                {**params, "outcome": outcome},
            )
            raise

    def save_evidence(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"observed_at": datetime.now(UTC).isoformat(), "jobs": self.jobs},
                default=str,
                indent=2,
            )
            + "\n"
        )
