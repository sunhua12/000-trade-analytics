"""Prepare one verified JSON v2 release for the existing Pages build."""

import shutil
import tempfile
from pathlib import Path
from typing import Any

from trade_analytics.export.v2 import verify_v2 as verify_snapshot


def stage_snapshot(snapshot_root: Path, destination: Path) -> dict[str, Any]:
    result = verify_snapshot(snapshot_root)
    source = snapshot_root / result["snapshot_id"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".data-", dir=destination.parent))
    backup = stage.with_name(stage.name + "-backup")
    try:
        for name in ("monthly.json", "partners.json", "manifest.json"):
            shutil.copyfile(source / name, stage / name)
        if destination.exists():
            destination.rename(backup)
        try:
            stage.rename(destination)
        except Exception:
            if backup.exists():
                backup.rename(destination)
            raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        # Keep a backup if restoring it failed.
        if destination.exists():
            shutil.rmtree(backup, ignore_errors=True)
    return result
