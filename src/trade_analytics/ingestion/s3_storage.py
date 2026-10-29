"""Immutable Amazon S3 storage for validated ingestion artifacts."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from botocore.exceptions import ClientError

from trade_analytics.ingestion.exceptions import StorageConflictError
from trade_analytics.ingestion.manifest import (
    Manifest,
    validate_existing_artifacts,
)
from trade_analytics.ingestion.storage import validate_source


class S3ObjectClient(Protocol):
    """Subset of the boto3 S3 client used by ingestion storage."""

    def get_object(self, *, Bucket: str, Key: str) -> Mapping[str, Any]:
        """Return one object response or raise ClientError when absent."""
        ...

    def put_object(
        self, *, Bucket: str, Key: str, Body: bytes, ContentType: str, IfNoneMatch: str
    ) -> Mapping[str, Any]:
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


class S3Storage:
    """Write deterministic data and manifest artifacts to S3."""

    def __init__(
        self,
        *,
        bucket: str,
        client: S3ObjectClient,
        prefix: str = "un_comtrade",
    ) -> None:
        normalized_prefix = prefix.strip("/")
        if not bucket:
            raise ValueError("bucket must not be empty")
        if not normalized_prefix:
            raise ValueError("prefix must not be empty")
        self._bucket = bucket
        self._client = client
        self._prefix = normalized_prefix

    def write(self, path: Path) -> StoredS3Ingestion:
        """Upload the exact bytes of a validated committed local source."""
        data = path.read_bytes()
        manifest_data = path.with_name("manifest.json").read_bytes()
        source = validate_source(path.with_name("manifest.json"), data, manifest_data)
        manifest = Manifest.model_validate(source["manifest"])
        partition = (
            source["source_file"]
            .removeprefix("s3://local/un_comtrade/")
            .removesuffix("/data.ndjson")
        )
        root = f"{self._prefix}/{partition}"
        data_key = f"{root}/data.ndjson"
        manifest_key = f"{root}/manifest.json"

        data_existing = self._read_object(data_key)
        manifest_existing = self._read_object(manifest_key)
        if manifest_existing is not None and data_existing is None:
            raise StorageConflictError("committed S3 source is missing data")
        validate_existing_artifacts(
            data=data_existing,
            manifest_data=manifest_existing,
            expected=manifest,
            location=f"s3://{self._bucket}/{root}",
        )
        if data_existing is not None and manifest_existing is not None:
            return self._stored_result(
                status="already_exists",
                data_key=data_key,
                manifest_key=manifest_key,
                row_count=manifest.row_count,
                checksum_value=manifest.checksum,
            )

        if data_existing is None:
            self._client.put_object(
                Bucket=self._bucket,
                Key=data_key,
                Body=data,
                ContentType="application/x-ndjson",
                IfNoneMatch="*",
            )
        if manifest_existing is None:
            self._client.put_object(
                Bucket=self._bucket,
                Key=manifest_key,
                Body=manifest_data,
                ContentType="application/json",
                IfNoneMatch="*",
            )
        return self._stored_result(
            status="success",
            data_key=data_key,
            manifest_key=manifest_key,
            row_count=manifest.row_count,
            checksum_value=manifest.checksum,
        )

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
