"""Local filesystem storage for Phase 1 ingestion artifacts."""

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from trade_analytics.ingestion.manifest import build_manifest, serialize_ndjson
from trade_analytics.ingestion.service import IngestionDataset


@dataclass(frozen=True)
class StoredIngestion:
    """Metadata describing successfully written local artifacts."""

    data_path: Path
    manifest_path: Path
    row_count: int
    checksum: str


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
        """Serialize and atomically replace the data and manifest files."""
        target_dir = (
            self._root
            / f"period={dataset.query.period}"
            / f"query_type={dataset.query.query_type.value}"
        )
        target_dir.mkdir(parents=True, exist_ok=True)
        data_path = target_dir / "data.ndjson"
        manifest_path = target_dir / "manifest.json"

        data = serialize_ndjson(dataset)
        manifest = build_manifest(dataset, data=data, ingested_at=self._clock())
        manifest_data = (
            json.dumps(
                manifest.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode()

        data_temp = self._write_temporary(target_dir, data)
        manifest_temp = self._write_temporary(target_dir, manifest_data)
        try:
            os.replace(data_temp, data_path)
            os.replace(manifest_temp, manifest_path)
        except Exception:
            data_temp.unlink(missing_ok=True)
            manifest_temp.unlink(missing_ok=True)
            raise

        return StoredIngestion(
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
