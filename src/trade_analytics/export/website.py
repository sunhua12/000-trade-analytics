"""Build a complete static release from a validated snapshot; no Node runtime needed."""

import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from trade_analytics.export.service import json_bytes, sha256, verify_snapshot


def build_website(snapshot_root: Path, frontend: Path, output: Path) -> dict[str, Any]:
    verified = verify_snapshot(snapshot_root)
    snapshot_id = verified["snapshot_id"]
    source = snapshot_root / snapshot_id
    release_id = snapshot_id + "-" + uuid.uuid4().hex[:8]
    output.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".website-", dir=output))
    pointer_path: Path | None = None
    try:
        shutil.copytree(frontend / "src", stage, dirs_exist_ok=True)
        shutil.copytree(frontend / "assets", stage / "assets")
        (stage / "data").mkdir()
        for name in ("manifest.json", "monthly.json", "partners.json"):
            shutil.copyfile(source / name, stage / "data" / name)
        for name in ("index.html", "style.css", "app.mjs", "analytics.mjs", "charts.mjs"):
            if not (stage / name).is_file():
                raise ValueError(f"missing required frontend asset: {name}")
        # Validate the copied bytes too, not just the original snapshot paths.
        manifest = json.loads((stage / "data/manifest.json").read_bytes())
        for name, metadata in manifest["files"].items():
            payload = (stage / "data" / name).read_bytes()
            if sha256(payload) != metadata["sha256"] or len(payload) != metadata["bytes"]:
                raise ValueError("copied website data checksum mismatch")
        release = output / release_id
        stage.rename(release)
        descriptor, pointer = tempfile.mkstemp(prefix=".current-", dir=output)
        pointer_path = Path(pointer)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(
                json_bytes(
                    {"release_id": release_id, "snapshot_id": snapshot_id, "directory": release_id}
                )
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(pointer_path, output / "current.json")
        return {"status": "built", "snapshot_id": snapshot_id, "directory": str(release.resolve())}
    finally:
        if stage.exists():
            shutil.rmtree(stage)
        if pointer_path is not None:
            pointer_path.unlink(missing_ok=True)
