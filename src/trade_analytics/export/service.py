"""Cross-check dbt output, then publish an immutable local snapshot."""

import json
import os
import shutil
import tempfile
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from trade_analytics.export.v2 import sha256
from trade_analytics.warehouse.read_settings import Settings


def json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()


def validate_build(artifacts: Path, settings: Settings) -> dict[str, str]:
    """Require a fresh successful build including both views and their data tests."""
    manifest_bytes = (artifacts / "manifest.json").read_bytes()
    results_bytes = (artifacts / "run_results.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    results = json.loads(results_bytes)
    invocation = results["metadata"]["invocation_id"]
    if invocation != manifest["metadata"]["invocation_id"]:
        raise ValueError("dbt artifacts must come from the same invocation")
    generated = datetime.fromisoformat(results["metadata"]["generated_at"].replace("Z", "+00:00"))
    if generated.tzinfo is None:
        raise ValueError("dbt build timestamp must include a timezone")
    age = datetime.now(UTC) - generated
    if not timedelta(0) <= age <= timedelta(hours=24):
        raise ValueError("dbt build evidence must be from the last 24 hours")
    if results.get("args", {}).get("which") != "build":
        raise ValueError("export requires dbt build evidence, not dbt run or compile")
    nodes = manifest["nodes"]
    models = {
        "model.trade_analytics.mart_multi_market_ic_monthly",
        "model.trade_analytics.mart_multi_market_ic_partners",
    }
    for key in models:
        node = nodes[key]
        if node["database"] != settings.project or node["schema"] != settings.dataset:
            raise ValueError("dbt build target differs from export target")
    tests = {
        key
        for key, node in nodes.items()
        if node["resource_type"] == "test"
        and models.intersection(node.get("depends_on", {}).get("nodes", []))
    }
    if "test.trade_analytics.assert_multi_market_presentation" not in tests:
        raise ValueError("missing multi-market presentation consistency test")
    statuses = {result["unique_id"]: result["status"] for result in results["results"]}
    if any(status not in ("success", "pass") for status in statuses.values()):
        raise ValueError("dbt invocation contains failed, warned, or skipped nodes")
    if any(statuses.get(key) != "success" for key in models) or any(
        statuses.get(key) != "pass" for key in tests
    ):
        raise ValueError("both presentation models and all their data tests must pass")
    return {
        "invocation_id": invocation,
        "manifest_sha256": sha256(manifest_bytes),
        "run_results_sha256": sha256(results_bytes),
    }


def publish_snapshot(
    raw: dict[str, Any],
    output: Path,
    start: date,
    end_exclusive: date,
    *,
    build: dict[str, str],
    jobs: list[dict[str, Any]],
) -> dict[str, Any]:
    from trade_analytics.export.v2 import validate_v2

    version = "2.0.0"
    monthly, partners = validate_v2(raw, start, end_exclusive)
    snapshot_id = uuid.uuid4().hex
    output.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".staging-", dir=output))
    pointer_temp: Path | None = None
    try:
        files = {}
        for name, rows in (("monthly.json", monthly), ("partners.json", partners)):
            document = {
                "schema_version": version,
                "snapshot_id": snapshot_id,
                "rows": [row.model_dump(mode="json") for row in rows],
            }
            payload = (
                json.dumps(
                    document,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                + "\n"
            ).encode()
            del document
            (stage / name).write_bytes(payload)
            files[name] = {"row_count": len(rows), "sha256": sha256(payload), "bytes": len(payload)}
        available = [row.month for row in monthly if row.has_world or row.has_countries]
        manifest = {
            "schema_version": version,
            "snapshot_id": snapshot_id,
            "generated_at": datetime.now(UTC).isoformat(),
            "start_month": start.isoformat(),
            "end_exclusive": end_exclusive.isoformat(),
            "latest_data_month": max(available).isoformat(),
            "currency": "USD",
            "decimal_encoding": "string",
            "hhi_coverage_tolerance": "0.005",
            "files": files,
        }
        from trade_analytics.export.schemas import SnapshotManifestV2
        from trade_analytics.export.v2 import scope_metadata

        manifest.update(scope_metadata(monthly, partners))
        manifest_payload = json_bytes(manifest)
        SnapshotManifestV2.model_validate_json(manifest_payload)
        (stage / "manifest.json").write_bytes(manifest_payload)
        # Internal evidence stays outside the directory consumed by the website.
        audit = output / "audit"
        audit.mkdir(exist_ok=True)
        (audit / f"{snapshot_id}.json").write_bytes(json_bytes({"dbt": build, "jobs": jobs}))
        destination = output / snapshot_id
        stage.rename(destination)
        pointer = {
            "schema_version": version,
            "snapshot_id": snapshot_id,
            "manifest": f"{snapshot_id}/manifest.json",
            "manifest_sha256": sha256(manifest_payload),
        }
        descriptor, temp_name = tempfile.mkstemp(prefix=".current-", dir=output)
        pointer_temp = Path(temp_name)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(json_bytes(pointer))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(pointer_temp, output / "current.json")
        return {
            "status": "success",
            "snapshot_id": snapshot_id,
            "path": str(destination.resolve()),
            "files": files,
        }
    finally:
        if stage.exists():
            shutil.rmtree(stage)
        if pointer_temp is not None:
            pointer_temp.unlink(missing_ok=True)
