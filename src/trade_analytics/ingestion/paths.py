"""Portable checkpoint paths shared by the host and existing Airflow containers."""

from pathlib import Path
from typing import Any


def relative_artifact_path(recorded: str | Path) -> Path:
    parts = Path(recorded).parts
    if ".." in parts:
        raise ValueError("artifact checkpoint must not traverse directories")
    positions = [index for index, part in enumerate(parts) if part == "v3"]
    if not positions:
        raise ValueError("artifact checkpoint has no v3 identity")
    relative = Path(*parts[positions[-1] :])
    if relative.name != "data.ndjson":
        raise ValueError("artifact checkpoint must identify data.ndjson")
    return relative


def resolve_artifact(root: Path, recorded: str | Path) -> Path:
    candidate = (root / relative_artifact_path(recorded)).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError("artifact checkpoint escaped the data root")
    return candidate


def portable_checkpoints(entries: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for recorded, evidence in entries.items():
        key = relative_artifact_path(recorded).as_posix()
        if key not in result or isinstance(evidence, dict):
            result[key] = evidence
    return result
