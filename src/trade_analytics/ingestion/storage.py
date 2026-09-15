"""Local filesystem storage for Phase 1 ingestion artifacts."""

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from trade_analytics.ingestion.manifest import (
    artifact_partition,
    build_manifest,
    serialize_manifest,
    serialize_ndjson,
    validate_existing_artifacts,
)
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
        """Preserve existing artifacts; atomically install each missing file (single writer)."""
        target_dir = self._root / artifact_partition(dataset.query)
        target_dir.mkdir(parents=True, exist_ok=True)
        data_path = target_dir / "data.ndjson"
        manifest_path = target_dir / "manifest.json"

        data = serialize_ndjson(dataset)
        manifest = build_manifest(dataset, data=data, ingested_at=self._clock())
        manifest_data = serialize_manifest(manifest)

        data_existing = data_path.read_bytes() if data_path.exists() else None
        manifest_existing = manifest_path.read_bytes() if manifest_path.exists() else None
        validate_existing_artifacts(
            data=data_existing,
            manifest_data=manifest_existing,
            expected=manifest,
            location=str(target_dir),
        )
        status: Literal["success", "already_exists"] = (
            "already_exists"
            if data_existing is not None and manifest_existing is not None
            else "success"
        )

        data_temp: Path | None = None
        manifest_temp: Path | None = None
        try:
            if data_existing is None:
                data_temp = self._write_temporary(target_dir, data)
            if manifest_existing is None:
                manifest_temp = self._write_temporary(target_dir, manifest_data)
            if data_temp is not None:
                os.replace(data_temp, data_path)
            if manifest_temp is not None:
                os.replace(manifest_temp, manifest_path)
        except Exception:
            if data_temp is not None:
                data_temp.unlink(missing_ok=True)
            if manifest_temp is not None:
                manifest_temp.unlink(missing_ok=True)
            raise

        return StoredIngestion(
            status=status,
            data_path=data_path,
            manifest_path=manifest_path,
            row_count=manifest.row_count,
            checksum=manifest.checksum,
        )

    @staticmethod
    def _write_temporary(directory: Path, content: bytes) -> Path:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=directory,
            prefix=".",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            return Path(temporary.name)
