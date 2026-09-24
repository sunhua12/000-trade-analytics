"""Read S3 bytes and compare every normalized source field with BigQuery raw.
Write an independent snapshot attestation, never fabricate or repair a load job.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from importlib import import_module
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from trade_analytics.warehouse.publish import Publisher
from trade_analytics.warehouse.quality import partition, source_digest


def verify(
    runner: Publisher, period: str, directory: Path, *, download: bool = True
) -> list[dict[str, Any]]:
    if not __debug__:
        raise RuntimeError("Source verification requires Python assertions enabled")
    scope = partition(period)
    report = []
    for kind in ("partner_detail", "world_total"):
        sql = f"""
SELECT TO_JSON_STRING(r) payload FROM {runner.table(runner.raw, "un_comtrade_" + kind)} r
 WHERE period_start_date=PARSE_DATE('%Y%m',@period) AND cmd_code='8542' AND hs_version='H6'
        """
        raw = [
            json.loads(r["payload"], parse_float=Decimal)
            for r in runner.query(sql, {"period": period})
        ]
        assert raw, "Source partition is empty"
        identities = {
            (r["source_file"], r["checksum"], r["revision"], r["run_id"], r["ingested_at"])
            for r in raw
        }
        assert len(identities) == 1, "Mixed source versions"
        uri, checksum, revision, source_run, ingested = identities.pop()
        manifest_uri = uri.removesuffix("data.ndjson") + "manifest.json"
        directory.mkdir(parents=True, exist_ok=True)
        data_path, manifest_path = directory / f"{kind}.ndjson", directory / f"{kind}.manifest.json"
        if download:
            for remote, local in ((uri, data_path), (manifest_uri, manifest_path)):
                subprocess.run(["aws", "s3", "cp", remote, str(local), "--no-progress"], check=True)
        data = data_path.read_bytes()
        manifest = json.loads(manifest_path.read_text())
        assert checksum == manifest["checksum"] == "sha256:" + hashlib.sha256(data).hexdigest()
        assert manifest["revision"] == revision and manifest["schema_version"] == "2.0.0"
        assert (
            manifest["period"] == period
            and manifest["cmd_code"] == "8542"
            and manifest["hs_version"] == "H6"
            and manifest["query_type"] == kind
        )
        assert datetime.fromisoformat(
            manifest["ingested_at"].replace("Z", "+00:00")
        ) == datetime.fromisoformat(ingested.replace("Z", "+00:00"))
        fixed = {
            "period": period,
            "cmdCode": "8542",
            "reporterCode": 842,
            "flowCode": "M",
            "partner2Code": 0,
            "customsCode": "C00",
            "motCode": 0,
        }
        assert all(manifest["request_parameters"].get(k) == v for k, v in fixed.items())
        if kind == "world_total":
            assert manifest["request_parameters"]["partnerCode"] == 0
        source = [json.loads(line) for line in data.splitlines() if line.strip()]
        assert 0 < len(source) < 500 and len(source) == len(raw) == manifest["row_count"]
        assert len({r["partnerCode"] for r in source}) == len(source)
        expected: dict[str, dict[str, Decimal | None]] = {}
        for r in source:
            assert all(
                r.get(k) == v
                for k, v in {**fixed, "classificationCode": "H6", "freqCode": "M"}.items()
            )
            assert (r["partnerCode"] == 0) == (kind == "world_total")
            amount = Decimal(r["primaryValue"])
            assert amount >= 0 and (kind != "world_total" or amount > 0)
            expected[str(r["partnerCode"])] = {
                "primary_value": amount,
                "net_weight": None if r.get("netWgt") is None else Decimal(r["netWgt"]),
                "quantity": None if r.get("qty") is None else Decimal(r["qty"]),
            }
        for r in raw:
            assert all(r[k] == v for k, v in scope.items())
            assert r["reporter_code"] == "842" and r["flow_code"] == "M"
            for key, value in expected[r["partner_code"]].items():
                assert (None if r[key] is None else Decimal(str(r[key]))) == value, (
                    kind,
                    r["partner_code"],
                    key,
                )
        amount_sum = sum((Decimal(str(v["primary_value"])) for v in expected.values()), Decimal(0))
        assert amount_sum == Decimal(manifest["primary_value_sum"])
        item = {
            **{k: scope[k] for k in ("period", "cmd_code", "hs_version")},
            "query_type": kind,
            "status": "snapshot_verified",
            "run_id": source_run,
            "revision": revision,
            "source_file": uri,
            "manifest_file": manifest_uri,
            "checksum": checksum,
            "expected_row_count": len(raw),
            "actual_row_count": len(raw),
            "expected_primary_value_sum": str(amount_sum),
            "actual_primary_value_sum": str(amount_sum),
            "source_verification_job_id": runner.jobs[-1]["job_id"],
            "snapshot_hash": source_digest(raw),
            "event_at": datetime.now(UTC).isoformat(),
            "manifest": manifest,
        }
        runner.query(
            f"""
INSERT INTO {runner.table(runner.release, "source_attestations")}
 VALUES(@attestation,CURRENT_TIMESTAMP())
            """,
            {"attestation": json.dumps(item)},
        )
        report.append(item)
    return report


def main() -> None:
    bigquery = import_module("google.cloud.bigquery")

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--period", required=True)
    p.add_argument("--project", default="trade-analytics-508604")
    p.add_argument("--models", default="trade_analytics_day10_dev")
    p.add_argument("--raw", default="trade_raw")
    p.add_argument("--release", default="trade_analytics_published")
    p.add_argument("--source-dir", type=Path, default=Path("data/day10-source"))
    p.add_argument("--evidence-dir", type=Path, default=Path("docs/evidence/day10"))
    p.add_argument("--use-downloaded-files", action="store_true")
    args = p.parse_args()
    runner = Publisher(
        bigquery.Client(project=args.project, location="asia-northeast1"),
        args.project,
        args.models,
        args.raw,
        args.release,
    )
    try:
        runner.initialize()
        report = verify(
            runner, args.period, args.source_dir, download=not args.use_downloaded_files
        )
        args.evidence_dir.mkdir(parents=True, exist_ok=True)
        (args.evidence_dir / "source-verification.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
        print("Source bytes, manifest and all raw source fields verified")
    finally:
        runner.save_evidence(args.evidence_dir / "source-verification-jobs.json")


if __name__ == "__main__":
    main()
