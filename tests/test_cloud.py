"""Cloud mirroring: never overwrite blindly, never upload rot."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

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
    fail_on: set[str] = field(default_factory=set)

    def head_sha256(self, key: str) -> str | None:
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
    store = FakeStore({object_key(CONFIG.prefix, entry): (b"different", "deadbeef")})

    result = sync(landing, store, CONFIG)

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
    monkeypatch.delenv("B2_KEY_ID", raising=False)
    monkeypatch.delenv("B2_APP_KEY", raising=False)
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

        raise ClientError(
            {"Error": {"Code": self.code}, "ResponseMetadata": {"HTTPStatusCode": self.status}},
            "HeadObject",
        )


def _store_with(client: object) -> S3ObjectStore:
    store = S3ObjectStore.__new__(S3ObjectStore)
    store._client = client  # type: ignore[attr-defined]
    store._bucket = "eulerdata"  # type: ignore[attr-defined]
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
