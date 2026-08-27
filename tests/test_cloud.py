"""Cloud mirroring: never overwrite blindly, never upload rot."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from eulerlab.ingest.cloud import (
    MissingCredentials,
    S3ObjectStore,
    StorageConfig,
    load_storage_config,
    object_key,
    plan_sync,
    sync,
)
from eulerlab.ingest.landing import Landing

CONFIG = StorageConfig(
    endpoint_url="https://s3.us-west-004.backblazeb2.com",
    bucket="eulerlab-landing",
    prefix="nse/",
)


@dataclass
class FakeStore:
    objects: dict[str, tuple[bytes, str]] = field(default_factory=dict)
    puts: list[str] = field(default_factory=list)
    heads: list[str] = field(default_factory=list)
    fail_on: set[str] = field(default_factory=set)

    def list_sizes(self, prefix: str) -> dict[str, int]:
        return {k: len(v[0]) for k, v in self.objects.items() if k.startswith(prefix)}

    def head_sha256(self, key: str) -> str | None:
        self.heads.append(key)
        found = self.objects.get(key)
        return found[1] if found else None

    def put(self, key: str, payload: bytes, sha256: str) -> None:
        if key in self.fail_on:
            raise RuntimeError("bucket said no")
        self.puts.append(key)
        self.objects[key] = (payload, sha256)


def _landing(tmp_path: Path, days: int = 2) -> Landing:
    landing = Landing(tmp_path)
    for day in range(1, days + 1):
        landing.write(
            trade_date=date(2026, 8, day),
            segment="cm",
            file_format="udiff",
            url="https://example.invalid/f.zip",
            payload=f"payload-{day}".encode(),
            rows=day,
            inner_name="f.csv",
        )
    return landing


def test_keys_mirror_the_local_layout(tmp_path: Path) -> None:
    landing = _landing(tmp_path, days=1)
    entry = next(iter(landing.entries().values()))
    # Diffable by eye against the local tree.
    assert object_key("nse/", entry) == "nse/cm/2026/08/2026-08-01_udiff.zip"


def test_empty_prefix_is_handled(tmp_path: Path) -> None:
    landing = _landing(tmp_path, days=1)
    entry = next(iter(landing.entries().values()))
    assert object_key("", entry) == "cm/2026/08/2026-08-01_udiff.zip"


def test_everything_uploads_to_an_empty_bucket(tmp_path: Path) -> None:
    landing = _landing(tmp_path, days=3)
    store = FakeStore()
    result = sync(landing, store, CONFIG)
    assert result.uploaded == 3
    assert result.ok


def test_a_second_sync_uploads_nothing(tmp_path: Path) -> None:
    landing = _landing(tmp_path, days=3)
    store = FakeStore()
    sync(landing, store, CONFIG)
    store.puts.clear()

    result = sync(landing, store, CONFIG)

    assert result.uploaded == 0
    assert result.skipped == 3
    assert store.puts == []


def test_a_hash_mismatch_is_reported_and_never_overwritten(tmp_path: Path) -> None:
    """Something else wrote to our key. Overwriting would destroy the evidence."""
    landing = _landing(tmp_path, days=1)
    entry = next(iter(landing.entries().values()))
    # Same length, different content: only the hash check can catch this.
    store = FakeStore({object_key(CONFIG.prefix, entry): (b"payload-X", "deadbeef")})

    result = sync(landing, store, CONFIG, verify=True)

    assert result.uploaded == 0
    assert result.mismatched == ["nse/cm/2026/08/2026-08-01_udiff.zip"]
    assert not result.ok
    assert store.puts == []


def test_a_locally_rotted_file_is_not_uploaded(tmp_path: Path) -> None:
    """The cloud copy exists to protect us from local damage, not to replicate it."""
    landing = _landing(tmp_path, days=1)
    entry = next(iter(landing.entries().values()))
    target = tmp_path / entry.path
    os.chmod(target, 0o644)
    target.write_bytes(b"corrupted on disk")

    result = sync(landing, FakeStore(), CONFIG)

    assert result.uploaded == 0
    assert len(result.failed) == 1
    assert "no longer matches the manifest" in result.failed[0]


def test_one_failed_object_does_not_abort_the_rest(tmp_path: Path) -> None:
    landing = _landing(tmp_path, days=3)
    entries = sorted(landing.entries().values(), key=lambda e: e.trade_date)
    store = FakeStore(fail_on={object_key(CONFIG.prefix, entries[1])})

    result = sync(landing, store, CONFIG)

    assert result.uploaded == 2
    assert len(result.failed) == 1
    assert not result.ok


def test_dry_run_sends_nothing(tmp_path: Path) -> None:
    landing = _landing(tmp_path, days=2)
    store = FakeStore()
    result = sync(landing, store, CONFIG, dry_run=True)
    assert result.uploaded == 0
    assert store.puts == []


def test_plan_separates_the_three_cases(tmp_path: Path) -> None:
    landing = _landing(tmp_path, days=3)
    entries = sorted(landing.entries().values(), key=lambda e: e.trade_date)
    store = FakeStore(
        {
            object_key(CONFIG.prefix, entries[0]): (b"payload-1", entries[0].sha256),
            object_key(CONFIG.prefix, entries[1]): (b"other", "wrong"),
        }
    )

    plan = plan_sync(landing, store, CONFIG)

    assert len(plan.already_present) == 1
    assert len(plan.mismatched) == 1
    assert len(plan.upload) == 1
    assert plan.total == 3


def test_missing_credentials_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deleting the variables is not enough on its own: `S3ObjectStore` now
    loads `.env` before reading them, and this developer machine has a real
    `.env`. The loader is stubbed so the test exercises what it claims to —
    the behaviour when no credentials exist anywhere — rather than passing or
    failing depending on whose machine it runs on.
    """
    monkeypatch.delenv("B2_KEY_ID", raising=False)
    monkeypatch.delenv("B2_APP_KEY", raising=False)
    monkeypatch.setattr("eulerlab.ingest.cloud.load_env", lambda: {})
    with pytest.raises(MissingCredentials, match="B2_KEY_ID"):
        S3ObjectStore(CONFIG)


def test_the_committed_storage_config_parses() -> None:
    config = load_storage_config(Path("config/storage.yaml"))
    assert config.provider == "b2"
    assert config.endpoint_url.startswith("https://")
    # Secrets must never appear in a committed config file.
    assert "key" not in config.model_dump_json().lower().replace("key_id", "")


# --- a key that cannot read back what it writes ---


@dataclass
class DeniedClient:
    """Mimics botocore raising AccessDenied, as a write-only B2 key does."""

    code: str = "AccessDenied"
    status: int = 403

    def head_object(self, **_: object) -> dict[str, object]:
        from botocore.exceptions import ClientError

        # botocore's real error payload carries more keys than this; boto3-stubs
        # types it as a TypedDict, so hand it over as a plain mapping.
        response: Any = {
            "Error": {"Code": self.code},
            "ResponseMetadata": {"HTTPStatusCode": self.status},
        }
        raise ClientError(response, "HeadObject")


def _store_with(client: object) -> S3ObjectStore:
    """Build the store without __init__, which would demand real credentials."""
    store = S3ObjectStore.__new__(S3ObjectStore)
    store._client = client
    store._bucket = "eulerdata"
    return store


def test_a_write_only_key_fails_loudly_instead_of_re_uploading_everything() -> None:
    """The bug this guards: AccessDenied read as 'absent' makes every sync a
    full re-upload that reports success."""
    from eulerlab.ingest.cloud import InsufficientCapabilities

    with pytest.raises(InsufficientCapabilities, match="readFiles"):
        _store_with(DeniedClient()).head_sha256("nse/x.zip")


def test_a_genuinely_missing_object_is_still_none() -> None:
    assert _store_with(DeniedClient(code="404", status=404)).head_sha256("nse/x.zip") is None


def test_nosuchkey_is_treated_as_missing() -> None:
    assert _store_with(DeniedClient(code="NoSuchKey", status=404)).head_sha256("k") is None


def test_an_unexpected_error_is_not_swallowed() -> None:
    from botocore.exceptions import ClientError

    with pytest.raises(ClientError):
        _store_with(DeniedClient(code="InternalError", status=500)).head_sha256("k")


# --- listing instead of one HEAD per object ---


def test_the_default_sync_does_not_head_every_object(tmp_path: Path) -> None:
    """One LIST for the bucket, not thousands of round trips."""
    landing = _landing(tmp_path, days=3)
    store = FakeStore()
    sync(landing, store, CONFIG)
    store.puts.clear()

    sync(landing, store, CONFIG)

    assert store.heads == []


def test_verify_mode_does_check_every_hash(tmp_path: Path) -> None:
    landing = _landing(tmp_path, days=3)
    store = FakeStore()
    sync(landing, store, CONFIG)
    store.heads.clear()

    result = sync(landing, store, CONFIG, verify=True)

    assert len(store.heads) == 3
    assert result.skipped == 3


def test_a_wrong_size_is_caught_without_verify(tmp_path: Path) -> None:
    landing = _landing(tmp_path, days=1)
    entry = next(iter(landing.entries().values()))
    store = FakeStore({object_key(CONFIG.prefix, entry): (b"cut", entry.sha256)})

    result = sync(landing, store, CONFIG)

    assert result.mismatched == ["nse/cm/2026/08/2026-08-01_udiff.zip"]


def test_a_same_size_corruption_needs_verify_to_catch(tmp_path: Path) -> None:
    """Honest about the default's limit: equal length, different bytes."""
    landing = _landing(tmp_path, days=1)
    entry = next(iter(landing.entries().values()))
    store = FakeStore({object_key(CONFIG.prefix, entry): (b"payload-X", "deadbeef")})

    assert sync(landing, store, CONFIG).mismatched == []
    assert sync(landing, store, CONFIG, verify=True).mismatched != []


# --- mirroring an arbitrary tree (the Kite minute bars) ---


def test_a_directory_tree_uploads_then_skips(tmp_path: Path) -> None:
    from eulerlab.ingest.cloud import sync_directory

    root = tmp_path / "minute"
    (root / "HDFCBANK").mkdir(parents=True)
    (root / "HDFCBANK" / "a.parquet").write_bytes(b"aaa")
    (root / "HDFCBANK" / "b.parquet").write_bytes(b"bbbb")
    store = FakeStore()

    first = sync_directory(root, store, prefix="nse/kite_minute/")
    second = sync_directory(root, store, prefix="nse/kite_minute/")

    assert first.uploaded == 2
    assert second.uploaded == 0
    assert second.skipped == 2
    assert "nse/kite_minute/HDFCBANK/a.parquet" in store.objects


def test_tree_sync_reuploads_when_size_differs(tmp_path: Path) -> None:
    from eulerlab.ingest.cloud import sync_directory

    root = tmp_path / "minute"
    root.mkdir()
    (root / "a.parquet").write_bytes(b"aaa")
    store = FakeStore({"p/a.parquet": (b"different-length", "x")})

    assert sync_directory(root, store, prefix="p/").uploaded == 1


def test_tree_sync_dry_run_sends_nothing(tmp_path: Path) -> None:
    from eulerlab.ingest.cloud import sync_directory

    root = tmp_path / "m"
    root.mkdir()
    (root / "a.parquet").write_bytes(b"aaa")
    store = FakeStore()

    result = sync_directory(root, store, prefix="p/", dry_run=True)

    assert result.uploaded == 1
    assert store.puts == []


def test_tree_sync_records_the_hash_as_metadata(tmp_path: Path) -> None:
    from eulerlab.ingest.cloud import sync_directory
    from eulerlab.ingest.landing import sha256_of

    root = tmp_path / "m"
    root.mkdir()
    (root / "a.parquet").write_bytes(b"payload")
    store = FakeStore()

    sync_directory(root, store, prefix="p/")

    # No manifest hash exists for these, so it is computed at upload time --
    # which still gives future runs something exact to verify against.
    assert store.objects["p/a.parquet"][1] == sha256_of(b"payload")


def test_one_unreadable_file_does_not_stop_the_tree(tmp_path: Path) -> None:
    from eulerlab.ingest.cloud import sync_directory

    root = tmp_path / "m"
    root.mkdir()
    (root / "good.parquet").write_bytes(b"ok")
    (root / "bad.parquet").write_bytes(b"nope")
    store = FakeStore(fail_on={"p/bad.parquet"})

    result = sync_directory(root, store, prefix="p/")

    assert result.uploaded == 1
    assert len(result.failed) == 1
    assert not result.ok


@dataclass
class CountingStore(FakeStore):
    """A FakeStore that records how many times the bucket was enumerated."""

    listings: list[str] = field(default_factory=list)

    def list_sizes(self, prefix: str) -> dict[str, int]:
        self.listings.append(prefix)
        return super().list_sizes(prefix)


def test_a_shared_listing_plans_the_same_uploads(tmp_path: Path) -> None:
    """Handing `plan_sync` a listing must not change what it decides.

    The whole point of sharing one enumeration between the sync and the census
    is that it is the *same* data. If the shared path could plan differently
    from the fetching path, the saving would be bought with correctness.
    """
    landing = _landing(tmp_path, days=4)
    store = CountingStore()
    entries = list(landing.entries().values())
    # Two of the four already in the bucket, so the plan is a real mixture.
    for entry in entries[:2]:
        payload = (landing.root / entry.path).read_bytes()
        store.objects[object_key(CONFIG.prefix, entry)] = (payload, entry.sha256)

    fetched = plan_sync(landing, store, CONFIG)
    shared = plan_sync(landing, store, CONFIG, remote_sizes=store.list_sizes(CONFIG.prefix))

    assert [e.path for e in shared.upload] == [e.path for e in fetched.upload]
    assert [e.path for e in shared.already_present] == [e.path for e in fetched.already_present]
    assert [e.path for e in shared.mismatched] == [e.path for e in fetched.mismatched]
    assert shared.upload, "the fixture should leave something to upload"


def test_a_shared_listing_means_the_bucket_is_not_enumerated_again(tmp_path: Path) -> None:
    landing = _landing(tmp_path, days=2)
    store = CountingStore()
    listing = store.list_sizes(CONFIG.prefix)
    store.listings.clear()

    plan_sync(landing, store, CONFIG, remote_sizes=listing)
    assert store.listings == [], "a caller supplying the listing must not trigger another"

    plan_sync(landing, store, CONFIG)
    assert store.listings == [CONFIG.prefix], "without one it must still fetch"


def test_sync_uploads_concurrently_without_losing_failures(tmp_path: Path) -> None:
    """Every entry is attempted, and one refusal does not take the rest down.

    The loop became a thread pool. A pool that swallowed an exception would
    report a clean sync while objects were missing, which is the failure this
    mirror exists to prevent.
    """
    landing = _landing(tmp_path, days=6)
    store = FakeStore()
    doomed = object_key(CONFIG.prefix, list(landing.entries().values())[2])
    store.fail_on = {doomed}

    result = sync(landing, store, CONFIG)

    assert len(result.failed) == 1
    assert doomed.split("/")[-1] in result.failed[0]
    assert result.uploaded == 5, "the other five must still be up"
    assert len(store.puts) == 5


def test_sync_reports_failures_in_landing_order(tmp_path: Path) -> None:
    """`pool.map` preserves input order, so a re-run reads the same way."""
    landing = _landing(tmp_path, days=6)
    store = FakeStore()
    keys = [object_key(CONFIG.prefix, e) for e in landing.entries().values()]
    store.fail_on = {keys[4], keys[1]}

    result = sync(landing, store, CONFIG)

    assert len(result.failed) == 2
    first, second = (p.split(":")[0] for p in result.failed)
    order = [e.path for e in landing.entries().values()]
    assert order.index(first) < order.index(second)
