"""Immutable Amazon S3 storage for validated ingestion artifacts."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from pydantic import ValidationError

from trade_analytics.ingestion.exceptions import StorageConflictError
from trade_analytics.ingestion.manifest import (
    Manifest,
    build_manifest,
    checksum,
    serialize_manifest,
    serialize_ndjson,
)
from trade_analytics.ingestion.service import IngestionDataset


class S3ObjectClient(Protocol):
    """Subset of the boto3 S3 client used by ingestion storage."""

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        """Return one object response or raise ClientError when absent."""
        ...

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        """Write one complete object body."""
        ...


@dataclass(frozen=True)
class StoredS3Ingestion:
    """Metadata returned after S3 artifacts are safely persisted."""

    status: Literal["success", "already_exists"]
    data_uri: str
    manifest_uri: str
    row_count: int
    checksum: str


def _utc_now() -> datetime:
    return datetime.now(UTC)


class S3Storage:
    """Write deterministic data and manifest artifacts to S3."""

    def __init__(
        self,
        *,
        bucket: str,
        client: S3ObjectClient,
        prefix: str = "un_comtrade",
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        normalized_prefix = prefix.strip("/")
        if not bucket:
            raise ValueError("bucket must not be empty")
        if not normalized_prefix:
            raise ValueError("prefix must not be empty")
        self._bucket = bucket
        self._client = client
        self._prefix = normalized_prefix
        self._clock = clock

    def write(self, dataset: IngestionDataset) -> StoredS3Ingestion:
        """Serialize and write both artifacts to one stable S3 partition."""
        root = (
            f"{self._prefix}/period={dataset.query.period}/"
            f"query_type={dataset.query.query_type.value}"
        )
        data_key = f"{root}/data.ndjson"
        manifest_key = f"{root}/manifest.json"
        data = serialize_ndjson(dataset)
        manifest = build_manifest(dataset, data=data, ingested_at=self._clock())
        manifest_data = serialize_manifest(manifest)

        data_existing = self._read_object(data_key)
        manifest_existing = self._read_object(manifest_key)
        if data_existing is not None and manifest_existing is not None:
            self._validate_existing_artifacts(
                data=data_existing,
                manifest_data=manifest_existing,
                expected_checksum=manifest.checksum,
                root=root,
            )
            return self._stored_result(
                status="already_exists",
                data_key=data_key,
                manifest_key=manifest_key,
                row_count=manifest.row_count,
                checksum_value=manifest.checksum,
            )

        if data_existing is not None and checksum(data_existing) != manifest.checksum:
            raise self._conflict(root)
        if manifest_existing is not None:
            self._validate_existing_manifest(
                manifest_data=manifest_existing,
                expected_checksum=manifest.checksum,
                root=root,
            )

        if data_existing is None:
            self._client.put_object(
                Bucket=self._bucket,
                Key=data_key,
                Body=data,
                ContentType="application/x-ndjson",
            )
        if manifest_existing is None:
            self._client.put_object(
                Bucket=self._bucket,
                Key=manifest_key,
                Body=manifest_data,
                ContentType="application/json",
            )
        return self._stored_result(
            status="success",
            data_key=data_key,
            manifest_key=manifest_key,
            row_count=manifest.row_count,
            checksum_value=manifest.checksum,
        )

    def _validate_existing_artifacts(
        self,
        *,
        data: bytes,
        manifest_data: bytes,
        expected_checksum: str,
        root: str,
    ) -> None:
        self._validate_existing_manifest(
            manifest_data=manifest_data,
            expected_checksum=expected_checksum,
            root=root,
        )
        if checksum(data) != expected_checksum:
            raise self._conflict(root)

    def _validate_existing_manifest(
        self,
        *,
        manifest_data: bytes,
        expected_checksum: str,
        root: str,
    ) -> None:
        try:
            existing_manifest = Manifest.model_validate(json.loads(manifest_data))
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as error:
            raise StorageConflictError(
                f"S3 checksum conflict at s3://{self._bucket}/{root}: invalid manifest"
            ) from error
        if existing_manifest.checksum != expected_checksum:
            raise self._conflict(root)

    def _conflict(self, root: str) -> StorageConflictError:
        return StorageConflictError(f"S3 checksum conflict at s3://{self._bucket}/{root}")

    def _stored_result(
        self,
        *,
        status: Literal["success", "already_exists"],
        data_key: str,
        manifest_key: str,
        row_count: int,
        checksum_value: str,
    ) -> StoredS3Ingestion:
        return StoredS3Ingestion(
            status=status,
            data_uri=f"s3://{self._bucket}/{data_key}",
            manifest_uri=f"s3://{self._bucket}/{manifest_key}",
            row_count=row_count,
            checksum=checksum_value,
        )

    def _read_object(self, key: str) -> bytes | None:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code in {"NoSuchKey", "404", "NotFound"}:
                return None
            raise
        body = response["Body"]
        content = body.read()
        if not isinstance(content, bytes):
            raise TypeError(f"S3 object {key} did not return bytes")
        return content
