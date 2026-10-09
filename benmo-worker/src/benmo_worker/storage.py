from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from benmo_worker.errors import AlreadyExistsWithDifferentContent, IntegrityError


def _safe_local_path(root: Path, key: str) -> Path:
    if not key or key.startswith(("/", "\\")) or "\x00" in key:
        raise IntegrityError("invalid object key")
    root_resolved = root.resolve()
    candidate = (root_resolved / key.replace("\\", "/")).resolve()
    if root_resolved != candidate and root_resolved not in candidate.parents:
        raise IntegrityError("object key escapes object-store root")
    return candidate


class LocalObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    async def put_immutable(
        self,
        key: str,
        body: bytes,
        content_type: str,
        metadata: dict[str, str] | None = None,
    ) -> str:
        return await asyncio.to_thread(self._put, key, body, content_type, metadata or {})

    def _put(self, key: str, body: bytes, content_type: str, metadata: dict[str, str]) -> str:
        target = _safe_local_path(self.root, key)
        digest = hashlib.sha256(body).hexdigest()
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            existing = target.read_bytes()
            if hashlib.sha256(existing).hexdigest() != digest:
                raise AlreadyExistsWithDifferentContent(f"immutable object already exists: {key}") from None
            return digest
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        meta_target = target.with_name(f"{target.name}.metadata.json")
        meta_payload = {
            "content_type": content_type,
            "sha256": digest,
            "metadata": metadata,
        }
        meta_temp = meta_target.with_name(f".{meta_target.name}.{os.getpid()}.tmp")
        meta_temp.write_text(json.dumps(meta_payload, sort_keys=True), encoding="utf-8")
        try:
            os.replace(meta_temp, meta_target)
        finally:
            meta_temp.unlink(missing_ok=True)
        return digest

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(_safe_local_path(self.root, key).read_bytes)


class S3ObjectStore:
    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        *,
        region: str = "us-east-1",
        client: Any | None = None,
    ) -> None:
        if not bucket:
            raise ValueError("bucket is required")
        if client is None:
            import boto3  # type: ignore[import-untyped]

            client = boto3.client("s3", region_name=region)
        self.client = client
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def _key(self, key: str) -> str:
        clean = key.strip("/")
        if not clean or ".." in clean.split("/"):
            raise IntegrityError("invalid S3 key")
        return f"{self.prefix}/{clean}" if self.prefix else clean

    async def put_immutable(
        self,
        key: str,
        body: bytes,
        content_type: str,
        metadata: dict[str, str] | None = None,
    ) -> str:
        return await asyncio.to_thread(self._put, key, body, content_type, metadata or {})

    def _put(self, key: str, body: bytes, content_type: str, metadata: dict[str, str]) -> str:
        object_key = self._key(key)
        digest = hashlib.sha256(body).hexdigest()
        try:
            head = self.client.head_object(Bucket=self.bucket, Key=object_key)
        except self.client.exceptions.ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code not in {"404", "NoSuchKey", "NotFound"}:
                raise
        else:
            existing_hash = head.get("Metadata", {}).get("sha256")
            if existing_hash != digest:
                raise AlreadyExistsWithDifferentContent(
                    f"immutable S3 object already exists: s3://{self.bucket}/{object_key}"
                )
            return digest
        object_metadata = {**metadata, "sha256": digest}
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=object_key,
                Body=body,
                ContentType=content_type,
                Metadata=object_metadata,
                IfNoneMatch="*",
            )
        except Exception as exc:
            response = getattr(exc, "response", {})
            code = str(response.get("Error", {}).get("Code", ""))
            status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code not in {"412", "PreconditionFailed", "ConditionalRequestConflict"} and status != 412:
                raise
            head = self.client.head_object(Bucket=self.bucket, Key=object_key)
            if head.get("Metadata", {}).get("sha256") != digest:
                raise AlreadyExistsWithDifferentContent(
                    f"immutable S3 object concurrently created with different content: s3://{self.bucket}/{object_key}"
                ) from exc
        return digest

    async def get(self, key: str) -> bytes:
        response = await asyncio.to_thread(self.client.get_object, Bucket=self.bucket, Key=self._key(key))
        return await asyncio.to_thread(response["Body"].read)


async def read_uri(uri: str, *, region: str = "us-east-1") -> bytes:
    if uri == "-":
        import sys

        return await asyncio.to_thread(sys.stdin.buffer.read)
    if uri.startswith("s3://"):
        bucket, separator, key = uri[5:].partition("/")
        if not separator or not bucket or not key:
            raise IntegrityError("S3 URI must be s3://bucket/key")
        import boto3

        client = boto3.client("s3", region_name=region)
        response = await asyncio.to_thread(client.get_object, Bucket=bucket, Key=key)
        return await asyncio.to_thread(response["Body"].read)
    return await asyncio.to_thread(Path(uri).read_bytes)


async def write_uri(uri: str, body: bytes, *, content_type: str = "application/json", region: str = "us-east-1") -> str:
    digest = hashlib.sha256(body).hexdigest()
    if uri == "-":
        import sys

        await asyncio.to_thread(sys.stdout.buffer.write, body)
        await asyncio.to_thread(sys.stdout.buffer.write, b"\n")
        return digest
    if uri.startswith("s3://"):
        bucket, separator, key = uri[5:].partition("/")
        if not separator or not bucket or not key:
            raise IntegrityError("S3 URI must be s3://bucket/key")
        import boto3

        client = boto3.client("s3", region_name=region)
        await asyncio.to_thread(
            client.put_object,
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            Metadata={"sha256": digest},
        )
        return digest
    target = Path(uri)
    await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(target.write_bytes, body)
    return digest
