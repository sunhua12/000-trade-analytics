"""Exercise raw revision, conflict, deletion and rollback in an isolated Dataset."""

import hashlib
import io
import json
import sys
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from importlib import import_module
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from trade_analytics.warehouse.backfill import BUCKET, PROJECT, RawLoader, source_key

PERIOD = "202312"
KIND = "partner_detail"
ROOT = Path(__file__).resolve().parents[1]


class MemoryS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, io.BytesIO]:
        if Bucket != BUCKET:
            raise ValueError("fixture bucket mismatch")
        return {"Body": io.BytesIO(self.objects[Key])}

    def put(self, revision: int, amounts: dict[int, str]) -> None:
        rows = [
            {
                "period": PERIOD,
                "reporterCode": 842,
                "flowCode": "M",
                "cmdCode": "8542",
                "partner2Code": 0,
                "customsCode": "C00",
                "motCode": 0,
                "partnerCode": code,
                "freqCode": "M",
                "classificationCode": "H6",
                "primaryValue": amount,
                "netWgt": None,
                "qty": None,
            }
            for code, amount in sorted(amounts.items())
        ]
        data = ("\n".join(json.dumps(row, separators=(",", ":")) for row in rows) + "\n").encode()
        checksum = "sha256:" + hashlib.sha256(data).hexdigest()
        amount_sum = sum((Decimal(value) for value in amounts.values()), Decimal(0))
        manifest = {
            "schema_version": "2.0.0",
            "hs_version": "H6",
            "period": PERIOD,
            "query_type": KIND,
            "cmd_code": "8542",
            "revision": revision,
            "row_count": len(rows),
            "primary_value_sum": str(amount_sum),
            "checksum": checksum,
            "ingested_at": datetime.now(UTC).isoformat(),
            "request_parameters": {
                "period": PERIOD,
                "reporterCode": 842,
                "flowCode": "M",
                "cmdCode": "8542",
                "partner2Code": 0,
                "customsCode": "C00",
                "motCode": 0,
            },
        }
        prefix = source_key(PERIOD, KIND, revision)
        self.objects[prefix + "/data.ndjson"] = data
        self.objects[prefix + "/manifest.json"] = json.dumps(manifest).encode()


def main() -> None:
    bigquery = import_module("google.cloud.bigquery")
    dataset = "trade_raw_day11_" + uuid.uuid4().hex[:8] + "_fixture"
    client = bigquery.Client(project=PROJECT, location="asia-northeast1")
    created = bigquery.Dataset(f"{PROJECT}.{dataset}")
    created.location = "asia-northeast1"
    client.create_dataset(created)
    memory = MemoryS3()
    loader = RawLoader(client, memory, raw_dataset=dataset)
    checks: list[dict[str, Any]] = []
    try:
        for name in ("un_comtrade_partner_detail", "audit_ingestion_runs"):
            source = client.get_table(f"{PROJECT}.trade_raw.{name}")
            target = bigquery.Table(f"{PROJECT}.{dataset}.{name}", schema=source.schema)
            target.time_partitioning = source.time_partitioning
            target.clustering_fields = source.clustering_fields
            client.create_table(target)

        def current() -> list[dict[str, Any]]:
            return loader.existing(PERIOD, KIND)

        memory.put(1, {36: "10", 124: "20"})
        checks.append({"case": "initial", "result": loader.load(PERIOD, KIND, 1)})
        before = current()
        assert len(before) == 2
        checks.append({"case": "same_revision", "result": loader.load(PERIOD, KIND, 1)})
        assert current() == before

        memory.put(1, {36: "11", 124: "20"})
        try:
            loader.load(PERIOD, KIND, 1)
        except ValueError as error:
            assert str(error) == "conflict"
            checks.append({"case": "same_revision_conflict", "result": "blocked"})
        else:
            raise AssertionError("same revision conflict was not blocked")
        assert current() == before

        memory.put(2, {36: "15"})
        try:
            loader.load(PERIOD, KIND, 2, rollback_probe=True)
        except Exception as error:
            assert "fixture_rollback_probe" in str(error)
            checks.append({"case": "transaction_rollback", "result": "rolled_back"})
        else:
            raise AssertionError("rollback probe did not fail")
        assert current() == before

        checks.append({"case": "revised_snapshot", "result": loader.load(PERIOD, KIND, 2)})
        after = current()
        assert len(after) == 1 and after[0]["partner_code"] == "36"
        assert Decimal(str(after[0]["primary_value"])) == 15
        memory.put(1, {36: "10", 124: "20"})
        try:
            loader.load(PERIOD, KIND, 1)
        except ValueError as error:
            assert str(error) == "stale_revision"
            checks.append({"case": "stale_revision", "result": "blocked"})
        else:
            raise AssertionError("stale revision was not blocked")
        assert current() == after

        audit_table = f"`{PROJECT}.{dataset}.audit_ingestion_runs`"
        audit = loader.query(
            f"SELECT revision,status,actual_row_count FROM {audit_table} "
            "WHERE period=@period ORDER BY revision",
            {"period": PERIOD},
        )
        assert [(row["revision"], row["actual_row_count"]) for row in audit] == [(1, 2), (2, 1)]
        report = {
            "status": "passed",
            "dataset": dataset,
            "checks": checks,
            "audit": audit,
            "final_partner_codes": [row["partner_code"] for row in after],
            "jobs": loader.jobs,
        }
        path = ROOT / "docs/evidence/day11/revision-fixture.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, default=str) + "\n")
        print("PASS: revision conflict, stale replay, deletion and rollback")
    finally:
        client.delete_dataset(f"{PROJECT}.{dataset}", delete_contents=True, not_found_ok=True)


if __name__ == "__main__":
    main()
