"""Sequentially fetch missing immutable Day 11 sources with the deployed Lambda."""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from trade_analytics.warehouse.backfill import BUCKET, KINDS, source_key

FUNCTION = "trade-analytics-ingestion"


def existing_keys() -> set[str]:
    result = subprocess.run(
        [
            "aws",
            "s3api",
            "list-objects-v2",
            "--bucket",
            BUCKET,
            "--prefix",
            "un_comtrade/v2/hs_version=H6/cmd_code=8542/",
            "--query",
            "Contents[].Key",
            "--output",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return set(json.loads(result.stdout) or [])


def invoke(period: str, kind: str, output: Path) -> dict[str, object]:
    payload = json.dumps(
        {
            "action": "ingest",
            "period": period,
            "cmd_code": "8542",
            "query_type": kind,
            "revision": 1,
            "run_id": f"day11-{period}-{kind}-r1",
        }
    )
    result = subprocess.run(
        [
            "aws",
            "lambda",
            "invoke",
            "--function-name",
            FUNCTION,
            "--region",
            "ap-northeast-1",
            "--cli-binary-format",
            "raw-in-base64-out",
            "--payload",
            payload,
            str(output),
            "--query",
            "{StatusCode:StatusCode,FunctionError:FunctionError,ExecutedVersion:ExecutedVersion}",
            "--output",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    invocation = json.loads(result.stdout)
    body = json.loads(output.read_text())
    if invocation.get("FunctionError") or invocation.get("StatusCode") != 200:
        return {"status": "failed", "invocation": invocation, "body": body}
    if body.get("period") != period or body.get("query_type") != kind:
        raise ValueError("Lambda response identity mismatch")
    if body.get("status") not in ("success", "already_exists"):
        raise ValueError("Lambda response status was not accepted")
    return {"status": body["status"], "invocation": invocation, "body": body}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="202301")
    parser.add_argument("--end", default="202412")
    parser.add_argument("--delay-seconds", type=float, default=1.0)
    parser.add_argument("--evidence-dir", type=Path, default=Path("docs/evidence/day11/ingest"))
    args = parser.parse_args()
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    keys = existing_keys()
    results = []
    for year in (2023, 2024):
        for month in range(1, 13):
            period = f"{year}{month:02d}"
            if not args.start <= period <= args.end:
                continue
            for kind in KINDS:
                prefix = source_key(period, kind)
                data_key, manifest_key = prefix + "/data.ndjson", prefix + "/manifest.json"
                if data_key in keys and manifest_key in keys:
                    item: dict[str, object] = {"period": period, "kind": kind, "status": "present"}
                else:
                    output = args.evidence_dir / f"{period}-{kind}-response.json"
                    try:
                        item = {"period": period, "kind": kind, **invoke(period, kind, output)}
                    except Exception as error:
                        item = {
                            "period": period,
                            "kind": kind,
                            "status": "failed",
                            "error": f"{type(error).__name__}: {error}",
                        }
                    if item["status"] in ("success", "already_exists"):
                        keys.update((data_key, manifest_key))
                    time.sleep(args.delay_seconds)
                results.append(item)
                (args.evidence_dir / "results.json").write_text(
                    json.dumps(results, indent=2, default=str) + "\n"
                )
                print(f"{period} {kind}: {item['status']}", flush=True)


if __name__ == "__main__":
    main()
