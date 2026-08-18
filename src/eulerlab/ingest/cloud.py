"""Mirror the landing zone to S3-compatible object storage.

**Why a separate sync rather than writing straight to the cloud.** A backfill is
a multi-hour run; adding a network write to every file multiplies the ways it
can die halfway. Landing to local disk first and mirroring afterwards means the
download is fast and self-contained, and the upload is independently
resumable — re-running skips whatever is already there.

**Integrity is checked with our own hash, not the ETag.** S3's ETag is an MD5
for simple uploads but something else entirely for multipart ones, so it is not
a dependable equality check across providers. Every object is therefore
uploaded with its SHA-256 in user metadata, and verification compares that
against the manifest. The question being answered is "is the copy in the cloud
byte-identical to what the exchange served", and nothing weaker will do.

Backblaze B2 exposes an S3-compatible API, so this module works unchanged
against B2, Cloudflare R2, AWS S3 or Wasabi — only ``endpoint_url`` differs.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from eulerlab.ingest.landing import Landing, ManifestEntry, sha256_of

SHA_METADATA_KEY = "sha256"

KEY_ID_ENV = "B2_KEY_ID"
APP_KEY_ENV = "B2_APP_KEY"


class StorageConfig(BaseModel):
    """Non-secret half of the storage settings. Credentials come from env."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = "b2"
    endpoint_url: str
    bucket: str
    prefix: str = ""


class ObjectStore(Protocol):
    """The slice of S3 this module needs, so tests need no network."""

    def head_sha256(self, key: str) -> str | None:
        """Recorded SHA-256 for an object, or None when it is not there."""

    def put(self, key: str, payload: bytes, sha256: str) -> None: ...


class MissingCredentials(RuntimeError):
    """Set B2_KEY_ID and B2_APP_KEY in .env before syncing."""


class InsufficientCapabilities(RuntimeError):
    """The key cannot read back what it writes, so nothing can be verified.

    A write-only key sounds safer but breaks this sync in a way that hides
    itself: every existence check fails, every object looks absent, and the
    sync silently re-uploads the entire landing zone on every run while
    reporting success. Failing loudly is the only honest option.
    """


@dataclass(frozen=True)
class SyncPlan:
    """What a sync would do. Produced before anything is uploaded."""

    upload: list[ManifestEntry]
    already_present: list[ManifestEntry]
    mismatched: list[ManifestEntry]
    """Present in the bucket but with a different hash. Never silently overwritten."""

    @property
    def total(self) -> int:
        return len(self.upload) + len(self.already_present) + len(self.mismatched)


@dataclass(frozen=True)
class SyncResult:
    uploaded: int
    skipped: int
    mismatched: list[str]
    failed: list[str]

    @property
    def ok(self) -> bool:
        return not self.mismatched and not self.failed


def object_key(prefix: str, entry: ManifestEntry) -> str:
    """Mirror the local layout exactly, so the two copies are diffable by eye."""
    return f"{prefix}{entry.path}" if prefix else entry.path


def plan_sync(landing: Landing, store: ObjectStore, config: StorageConfig) -> SyncPlan:
    upload: list[ManifestEntry] = []
    present: list[ManifestEntry] = []
    mismatched: list[ManifestEntry] = []

    for entry in _sorted_entries(landing):
        remote = store.head_sha256(object_key(config.prefix, entry))
        if remote is None:
            upload.append(entry)
        elif remote == entry.sha256:
            present.append(entry)
        else:
            mismatched.append(entry)

    return SyncPlan(upload=upload, already_present=present, mismatched=mismatched)


def _sorted_entries(landing: Landing) -> Iterator[ManifestEntry]:
    yield from sorted(landing.entries().values(), key=lambda e: (e.trade_date, e.segment))


def sync(
    landing: Landing,
    store: ObjectStore,
    config: StorageConfig,
    *,
    dry_run: bool = False,
) -> SyncResult:
    """Upload anything the bucket does not already have, verified by hash."""
    plan = plan_sync(landing, store, config)
    mismatched = [object_key(config.prefix, e) for e in plan.mismatched]
    failed: list[str] = []

    if dry_run:
        return SyncResult(0, len(plan.already_present), mismatched, failed)

    uploaded = 0
    for entry in plan.upload:
        local = landing.root / entry.path
        payload = local.read_bytes()

        # Re-hash before sending. If the local file has rotted, uploading it
        # would propagate the damage into the copy meant to protect us from it.
        if sha256_of(payload) != entry.sha256:
            failed.append(f"{entry.path}: local file no longer matches the manifest")
            continue

        try:
            store.put(object_key(config.prefix, entry), payload, entry.sha256)
        except Exception as exc:  # one bad object must not abort the whole sync
            failed.append(f"{entry.path}: {exc}")
            continue
        uploaded += 1

    return SyncResult(uploaded, len(plan.already_present), mismatched, failed)


class S3ObjectStore:
    """boto3-backed store. Constructed only when credentials are present."""

    def __init__(self, config: StorageConfig) -> None:
        key_id = os.environ.get(KEY_ID_ENV, "").strip()
        app_key = os.environ.get(APP_KEY_ENV, "").strip()
        if not key_id or not app_key:
            msg = f"{KEY_ID_ENV} and {APP_KEY_ENV} must be set (see .env.example)"
            raise MissingCredentials(msg)

        import boto3  # imported lazily so the ingest path never pays for it

        self._client = boto3.client(
            "s3",
            endpoint_url=config.endpoint_url,
            aws_access_key_id=key_id,
            aws_secret_access_key=app_key,
        )
        self._bucket = config.bucket

    def head_sha256(self, key: str) -> str | None:
        """SHA-256 recorded for an object, or None when it genuinely is not there.

        "Not there" and "not allowed to look" are different answers and must
        never be conflated: treating a permission error as absence turns an
        idempotent sync into a full re-upload that reports success.
        """
        from botocore.exceptions import ClientError

        try:
            response = self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if status == 404 or code in {"404", "NoSuchKey", "NotFound"}:
                return None
            if status in {401, 403} or code in {"AccessDenied", "403", "unauthorized"}:
                msg = (
                    f"the B2 key cannot read {self._bucket!r} (got {code or status}). "
                    "It needs the readFiles and listFiles capabilities as well as "
                    "writeFiles, otherwise nothing can be verified and every sync "
                    "re-uploads everything. Recreate the application key with read "
                    "access to the bucket."
                )
                raise InsufficientCapabilities(msg) from exc
            raise

        metadata = response.get("Metadata") or {}
        value = metadata.get(SHA_METADATA_KEY)
        return value if isinstance(value, str) else None

    def put(self, key: str, payload: bytes, sha256: str) -> None:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=payload,
            Metadata={SHA_METADATA_KEY: sha256},
        )


def load_storage_config(path: Path) -> StorageConfig:
    import yaml

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        msg = f"{path} must contain a YAML mapping"
        raise TypeError(msg)
    return StorageConfig.model_validate(raw)
