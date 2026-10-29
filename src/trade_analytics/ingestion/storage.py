"""Atomic local source storage and Manifest-based discovery."""

import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from trade_analytics.ingestion.exceptions import StorageConflictError
from trade_analytics.ingestion.manifest import (
    Manifest,
    artifact_partition,
    build_manifest,
    serialize_manifest,
    serialize_ndjson,
    validate_existing_artifacts,
)
from trade_analytics.ingestion.queries import ComtradeQuery
from trade_analytics.ingestion.service import IngestionDataset


@dataclass(frozen=True)
class StoredIngestion:
    """Metadata describing successfully written local artifacts."""

    data_path: Path
    manifest_path: Path
    row_count: int
    checksum: str
    status: Literal["success", "already_exists"] = "success"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class LocalStorage:
    """Write one ingestion dataset and its manifest to partitioned local paths."""

    def __init__(
        self,
        root: Path = Path("data/preview"),
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._root = root
        self._clock = clock

    def write(self, dataset: IngestionDataset) -> StoredIngestion:
        """Install a complete source directory; never silently repair committed data."""
        target_dir = self._root / artifact_partition(dataset.query)
        data_path = target_dir / "data.ndjson"
        manifest_path = target_dir / "manifest.json"
        data = serialize_ndjson(dataset)
        manifest = build_manifest(dataset, data=data, ingested_at=self._clock())
        manifest_data = serialize_manifest(manifest)
        if target_dir.exists():
            if not data_path.exists() or not manifest_path.exists():
                raise StorageConflictError(f"incomplete source at {target_dir}")
            validate_existing_artifacts(
                data=data_path.read_bytes(),
                manifest_data=manifest_path.read_bytes(),
                expected=manifest,
                location=str(target_dir),
            )
            status: Literal["success", "already_exists"] = "already_exists"
        else:
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            stage = Path(tempfile.mkdtemp(prefix=".source-", dir=target_dir.parent))
            try:
                for name, content in (("data.ndjson", data), ("manifest.json", manifest_data)):
                    with (stage / name).open("wb") as handle:
                        handle.write(content)
                        handle.flush()
                        os.fsync(handle.fileno())
                stage.rename(target_dir)
            finally:
                shutil.rmtree(stage, ignore_errors=True)
            status = "success"

        return StoredIngestion(
            status=status,
            data_path=data_path,
            manifest_path=manifest_path,
            row_count=manifest.row_count,
            checksum=manifest.checksum,
        )


def read_source(path: Path) -> dict[str, Any]:
    """Validate one committed local source without retaining decoded rows."""
    return validate_source(path, path.with_name("data.ndjson").read_bytes(), path.read_bytes())


def validate_source(path: Path, data: bytes, payload: bytes) -> dict[str, Any]:
    from trade_analytics.warehouse.source_validation import verify

    manifest = Manifest.model_validate_json(payload)
    query = ComtradeQuery.model_validate(
        {
            "period": manifest.period,
            "reporter_code": manifest.request_parameters["reporterCode"],
            "cmd_code": manifest.cmd_code,
            "query_type": manifest.query_type,
            "revision": manifest.revision,
            "expected_hs_version": manifest.hs_version,
        }
    )
    if not path.parent.as_posix().endswith("/" + artifact_partition(query)):
        raise StorageConflictError(f"manifest path identity mismatch: {path}")
    source = verify(
        data,
        payload,
        f"s3://local/un_comtrade/{artifact_partition(query)}/data.ndjson",
    )
    source.pop("expected")
    source["path"] = path.with_name("data.ndjson")
    return source


def scan_sources(root: Path) -> dict[str, dict[str, Any]]:
    """Validate committed v3 sources and select a whole latest revision per identity."""
    selected: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("v3/**/manifest.json")):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        source = read_source(path)
        manifest = source["manifest"]
        reporter = manifest["request_parameters"]["reporterCode"]
        identity = (
            f"{reporter}/{manifest['cmd_code']}/{manifest['period']}/{manifest['query_type']}"
        )
        old = selected.get(identity)
        if old and old["manifest"]["revision"] == manifest["revision"]:
            raise StorageConflictError(f"ambiguous source revision: {identity}")
        if old is None or manifest["revision"] > old["manifest"]["revision"]:
            selected[identity] = source
    # A final source directory without its commit manifest is not safe to resume.
    for data in root.glob("v3/**/data.ndjson"):
        if any(part.startswith(".") for part in data.relative_to(root).parts):
            continue
        if not data.with_name("manifest.json").exists():
            raise StorageConflictError(f"uncommitted source: {data}")
    return selected
