"""S3 handoff records and files; success records are always written last."""

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import boto3
from botocore.exceptions import ClientError


class Artifacts:
    def __init__(self, bucket: str, prefix: str, client: Any = None) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.client = client or boto3.client("s3")

    def uri(self, name: str) -> str:
        return f"s3://{self.bucket}/{self.prefix}/{name}"

    def get(self, uri: str) -> bytes:
        location = urlsplit(uri)
        if location.scheme != "s3" or location.netloc != self.bucket:
            raise ValueError("artifact must belong to configured S3 bucket")
        return bytes(
            self.client.get_object(Bucket=self.bucket, Key=location.path.lstrip("/"))["Body"].read()
        )

    def read(self, uri: str) -> dict[str, Any]:
        return dict(json.loads(self.get(uri)))

    def optional(self, name: str) -> dict[str, Any] | None:
        try:
            return self.read(self.uri(name))
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in {"NoSuchKey", "404", "NotFound"}:
                return None
            raise

    def put(self, name: str, data: bytes) -> str:
        self.client.put_object(Bucket=self.bucket, Key=f"{self.prefix}/{name}", Body=data)
        return self.uri(name)

    def write(self, name: str, value: dict[str, Any]) -> str:
        return self.put(name, json.dumps(value, allow_nan=False).encode())

    def upload_tree(self, folder: Path, prefix: str) -> None:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                self.put(f"{prefix}/{path.relative_to(folder).as_posix()}", path.read_bytes())
