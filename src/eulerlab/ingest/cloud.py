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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from eulerlab.env import load_env
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

    def list_sizes(self, prefix: str) -> dict[str, int]:
        """Every key under prefix, mapped to its size in bytes."""

    def head_sha256(self, key: str) -> str | None:
        """Recorded SHA-256 for an object, or None when it is not there."""

    def put(self, key: str, payload: bytes, sha256: str) -> None: ...


class ReadableStore(ObjectStore, Protocol):
    """An ObjectStore that can also be read back.

    Separate from `ObjectStore` because the upload paths — the landing-zone
    sync, the pruner — genuinely never download, and widening the protocol they
    depend on would force every fake in their tests to grow a method none of
    them uses.
    """

    def get(self, key: str) -> bytes:
        """The object's bytes. Raises if it is not there."""


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


def plan_sync(
    landing: Landing,
    store: ObjectStore,
    config: StorageConfig,
    *,
    verify: bool = False,
) -> SyncPlan:
    """Decide what to upload.

    Two modes, because they answer different questions at very different costs.

    Default: one paginated LIST for the whole bucket, then compare sizes. A key
    that is absent, or present at the wrong size, needs uploading. This is a few
    requests for thousands of objects.

    ``verify=True``: additionally fetch each object's recorded SHA-256, which is
    one HEAD per object — thousands of round trips. Size equality is a weak
    check; it would not notice a same-length corruption. So the strong check
    exists and is exact, but it is an occasional audit rather than something
    every sync pays for. Same split as `make check-landing` locally.
    """
    remote_sizes = store.list_sizes(config.prefix)

    upload: list[ManifestEntry] = []
    present: list[ManifestEntry] = []
    mismatched: list[ManifestEntry] = []

    for entry in _sorted_entries(landing):
        key = object_key(config.prefix, entry)
        size = remote_sizes.get(key)

        if size is None:
            upload.append(entry)
            continue
        if size != entry.size_bytes:
            mismatched.append(entry)
            continue
        if not verify:
            present.append(entry)
            continue

        remote_sha = store.head_sha256(key)
        if remote_sha == entry.sha256:
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
    verify: bool = False,
) -> SyncResult:
    """Upload anything the bucket does not already have."""
    plan = plan_sync(landing, store, config, verify=verify)
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
        load_env()
        key_id = os.environ.get(KEY_ID_ENV, "").strip()
        app_key = os.environ.get(APP_KEY_ENV, "").strip()
        if not key_id or not app_key:
            msg = f"{KEY_ID_ENV} and {APP_KEY_ENV} must be set (see .env.example)"
            raise MissingCredentials(msg)

        import boto3  # imported lazily so the ingest path never pays for it
        from botocore.config import Config as BotoConfig

        # Bounded, because unbounded is not a default this project can wear.
        # boto3 ships a 60s connect timeout and five attempts, so one stalled
        # TCP handshake costs five minutes per call and a pruned tree needs
        # many. That is exactly what happened: a test run sat in SYN_SENT
        # against B2 for **33 minutes**, hanging every commit behind it,
        # burning five seconds of CPU the whole time.
        #
        # A short connect timeout is the one that matters — a handshake that
        # has not completed in ten seconds is not going to. The read timeout is
        # longer because a large object legitimately takes a while.
        self._client = boto3.client(
            "s3",
            endpoint_url=config.endpoint_url,
            aws_access_key_id=key_id,
            aws_secret_access_key=app_key,
            config=BotoConfig(
                connect_timeout=10,
                read_timeout=30,
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )
        self._bucket = config.bucket

    def list_sizes(self, prefix: str) -> dict[str, int]:
        """One paginated LIST instead of one HEAD per object."""
        sizes: dict[str, int] = {}
        token: str | None = None
        while True:
            kwargs = {"Bucket": self._bucket, "Prefix": prefix, "MaxKeys": 1000}
            if token is not None:
                kwargs["ContinuationToken"] = token
            response = self._client.list_objects_v2(**kwargs)
            for item in response.get("Contents", []):
                key = item.get("Key")
                size = item.get("Size")
                if isinstance(key, str) and isinstance(size, int):
                    sizes[key] = size
            if not response.get("IsTruncated"):
                return sizes
            token = response.get("NextContinuationToken")

    def any_under(self, prefix: str) -> bool:
        """Whether *any* object exists under a prefix, in one request.

        Deliberately on the concrete store and on **neither protocol**. Adding
        it to `ObjectStore` broke 37 sync tests and adding it to
        `ReadableStore` broke 9 results-mirror tests - in both cases forcing
        fakes to implement a method that path never calls. Only the landing
        reader asks this, and it already reaches the store dynamically, so a
        protocol entry would buy nothing and cost every fake in the suite.

        `list_sizes` paginates the whole tree, which is the right shape for a
        sync and absurd for a yes/no question. Asking "does the fx tree hold
        data" enumerated 34,051 keys across 35 round trips, and the capability
        matrix asked it on every call — 62 seconds, every time, for a boolean.
        MaxKeys=1 answers the same question with one request.
        """
        response = self._client.list_objects_v2(Bucket=self._bucket, Prefix=prefix, MaxKeys=1)
        return bool(response.get("Contents"))

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

    def get(self, key: str) -> bytes:
        """Download one object's bytes. Used by restore-local."""
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        body: bytes = response["Body"].read()
        return body

    def put(self, key: str, payload: bytes, sha256: str) -> None:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=payload,
            Metadata={SHA_METADATA_KEY: sha256},
        )


UPLOAD_WORKERS = 12
"""Concurrent uploads for a directory tree.

Twelve rather than more for the reason the FX ingest found: past a dozen
simultaneous connections the local resolver, not the remote service, becomes
the failure point — and a DNS error looks nothing like a rate limit while
being just as fatal to the file it was fetching.
"""


@dataclass(frozen=True)
class TreeSyncResult:
    uploaded: int
    skipped: int
    failed: list[str]

    @property
    def ok(self) -> bool:
        return not self.failed


def sync_directory(
    root: Path,
    store: ObjectStore,
    *,
    prefix: str,
    pattern: str = "**/*",
    dry_run: bool = False,
) -> TreeSyncResult:
    """Mirror an arbitrary directory tree, comparing by size.

    The bhavcopy landing zone records a SHA-256 per file in its manifest, so
    `sync()` can verify against it. Other trees — the Kite minute bars, written
    as Parquet per chunk — have no such record, so the hash is computed at
    upload time and stored as object metadata. That still gives future runs
    something exact to verify against, it just cannot verify retrospectively.

    Comparison for *what to upload* is by size, which is one LIST call for the
    whole tree rather than one HEAD per file.
    """
    remote = store.list_sizes(prefix)
    local = sorted(p for p in root.glob(pattern) if p.is_file())

    pending: list[tuple[Path, str]] = []
    skipped = 0
    for path in local:
        key = f"{prefix}{path.relative_to(root).as_posix()}"
        if remote.get(key) == path.stat().st_size:
            skipped += 1
            continue
        pending.append((path, key))

    if dry_run:
        return TreeSyncResult(uploaded=len(pending), skipped=skipped, failed=[])

    uploaded = 0
    failed: list[str] = []
    lock = Lock()

    def send(job: tuple[Path, str]) -> None:
        nonlocal uploaded
        path, key = job
        try:
            payload = path.read_bytes()
            store.put(key, payload, sha256_of(payload))
        except Exception as exc:  # one bad object must not stop the tree
            with lock:
                failed.append(f"{path.relative_to(root)}: {exc}")
            return
        with lock:
            uploaded += 1

    # Uploaded concurrently, and the reason is the same one the Dukascopy
    # backfill taught: the throttle is per-connection, not per-account. Serially
    # this managed 58 objects a minute, which is eight hours for the 34,773
    # FX pair-days — a tree of many small files is bound by round trips rather
    # than by bandwidth.
    #
    # The counter and the failure list are guarded because they are the only
    # shared state; each upload is otherwise independent.
    with ThreadPoolExecutor(max_workers=UPLOAD_WORKERS) as pool:
        list(pool.map(send, pending))

    return TreeSyncResult(uploaded=uploaded, skipped=skipped, failed=failed)


def load_storage_config(path: Path) -> StorageConfig:
    import yaml

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        msg = f"{path} must contain a YAML mapping"
        raise TypeError(msg)
    return StorageConfig.model_validate(raw)
