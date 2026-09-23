"""One-time, guarded repair of the legacy 202301 World lineage, backed up first."""

import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from google.cloud import bigquery  # noqa: E402

from trade_analytics.warehouse.publish import Publisher  # noqa: E402


def main():
    data = (ROOT / "data/day10-source/world_total.ndjson").read_bytes()
    manifest = json.loads((ROOT / "data/day10-source/world_total.manifest.json").read_text())
    rows = [json.loads(line) for line in data.splitlines() if line.strip()]
    assert len(rows) == manifest["row_count"] == 1
    row = rows[0]
    assert "sha256:" + hashlib.sha256(data).hexdigest() == manifest["checksum"]
    assert row["period"] == manifest["period"] == "202301" and row["partnerCode"] == 0
    assert (
        row["cmdCode"] == manifest["cmd_code"] == "8542"
        and row["classificationCode"] == manifest["hs_version"] == "H6"
    )
    assert Decimal(row["primaryValue"]) == Decimal(manifest["primary_value_sum"])
    c = bigquery.Client(project="trade-analytics-508604", location="asia-northeast1")
    runner = Publisher(
        c,
        "trade-analytics-508604",
        "trade_analytics_day10_dev",
        "trade_raw",
        "trade_analytics_published",
    )
    table = runner.table("trade_raw", "un_comtrade_world_total")
    backup = runner.table("trade_analytics_published", "legacy_world_lineage_backup")
    before = runner.query(
        f"SELECT TO_JSON_STRING(w) payload FROM {table} w WHERE period_start_date=DATE '2023-01-01'"
    )
    assert len(before) == 1
    old = json.loads(before[0]["payload"])
    expected = {
        "period": "202301",
        "period_start_date": "2023-01-01",
        "reporter_code": "842",
        "partner_code": "0",
        "flow_code": "M",
        "cmd_code": "8542",
        "hs_version": "H6",
        "revision": 1,
        "run_id": "day06-world-202301",
    }
    assert all(old[k] == v for k, v in expected.items())
    assert Decimal(str(old["primary_value"])) == Decimal(row["primaryValue"])
    for name, key in [("net_weight", "netWgt"), ("quantity", "qty")]:
        assert (None if old[name] is None else Decimal(str(old[name]))) == (
            None if row[key] is None else Decimal(row[key])
        ), (name, old[name], row[key])
    assert old["source_file"].endswith(
        "/period=202301/query_type=world_total/revision=1/data.ndjson"
    )
    assert old["checksum"] == "e3b0c442...", "Only the documented legacy placeholder is repairable"
    runner.query(f"""CREATE TABLE IF NOT EXISTS {backup} AS
SELECT w.*,CURRENT_TIMESTAMP() backed_up_at FROM {table} w
WHERE period_start_date=DATE '2023-01-01';""")
    runner.query(
        f"""BEGIN TRANSACTION;
ASSERT (SELECT COUNT(*)=1 FROM {table} WHERE period_start_date=DATE '2023-01-01') AS 'world_count';
ASSERT (SELECT TO_JSON_STRING(w) FROM {table} w WHERE period_start_date=DATE
 '2023-01-01')=@before AS 'raw_changed_since_read';
UPDATE {table} SET checksum=@checksum,ingested_at=TIMESTAMP(@ingested)
WHERE period_start_date=DATE '2023-01-01' AND partner_code='0' AND cmd_code='8542' AND
 hs_version='H6' AND revision=1;
COMMIT TRANSACTION;""",
        {
            "before": before[0]["payload"],
            "checksum": manifest["checksum"],
            "ingested": manifest["ingested_at"],
        },
    )
    after = runner.query(
        f"SELECT TO_JSON_STRING(w) payload FROM {table} w WHERE period_start_date=DATE '2023-01-01'"
    )
    report = {
        "before": json.loads(before[0]["payload"]),
        "after": json.loads(after[0]["payload"]),
        "manifest": manifest,
        "backup_table": backup,
        "changed_columns": ["checksum", "ingested_at"],
        "result": "passed",
    }
    (ROOT / "docs/evidence/day10/world-lineage-repair.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    runner.save_evidence(ROOT / "docs/evidence/day10/world-lineage-repair-jobs.json")
    print("Repaired World checksum and source timestamp; all other columns matched and preserved.")


if __name__ == "__main__":
    main()
