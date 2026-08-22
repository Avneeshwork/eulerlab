"""Read a landing tree whether or not it is still on this disk.

### The problem pruning created

`make prune-local` deletes files that are verified present in B2, which is the
whole point — a 228 GB laptop cannot hold every archive at once. But everything
that reads a landing tree globs the local directory, so the moment a tree is
pruned those readers see nothing and report "no data" for an archive that is
sitting safely in the bucket.

It has already bitten twice: the capability matrix advertised crypto over an
emptied folder, and the instrument picker offered symbols the engine could not
open. Both were fixed by making them stricter about what "present" means, which
is correct and does not help anyone actually run a backtest.

This is the other half. B2 is the storage of record, so a reader asks for a
path and gets bytes — from disk if they are there, from the bucket if they are
not, cached on the way through so the second ask is free.

That is the same shape `intraday/store` already uses for NSE minute bars. This
generalises it to any landing tree rather than leaving each one to reinvent it.

### Listing is the part that is easy to get wrong

Fetching a known file is straightforward. Knowing *which* files exist when the
directory is empty is not — so the listing is the union of local and remote,
deduplicated. Local-only files matter because a tree may hold something not yet
uploaded; remote-only files are the pruned ones. Taking either alone silently
loses a set.
"""

from __future__ import annotations

import fnmatch
from functools import lru_cache
from pathlib import Path

LANDING_ROOT = Path("data/landing")
STORAGE_CONFIG = Path("config/storage.yaml")


class CloudUnavailable(RuntimeError):
    """The bucket could not be reached or is not configured.

    Raised rather than returning an empty listing, because "no files" and "I
    could not look" are different answers and only the second means the caller
    should stop rather than conclude.
    """


@lru_cache(maxsize=1)
def _store_and_prefix() -> tuple[object, str]:
    """The object store and key prefix, built once per process."""
    from eulerlab.ingest.cloud import S3ObjectStore, load_storage_config

    if not STORAGE_CONFIG.exists():
        msg = f"{STORAGE_CONFIG} is missing"
        raise CloudUnavailable(msg)
    try:
        config = load_storage_config(STORAGE_CONFIG)
        return S3ObjectStore(config), config.prefix
    except Exception as exc:
        raise CloudUnavailable(str(exc)) from exc


def remote_key(relative: str) -> str:
    """Where a landing-relative path lives in the bucket.

    Mirrors `sync_directory`, which uploads to `{prefix}{tree}/{path}`. The two
    must agree exactly: a mismatch here reads as "the file was never uploaded"
    rather than as a bug, which is the quietest possible failure.
    """
    _, prefix = _store_and_prefix()
    return f"{prefix}{relative}"


def available(tree: str, pattern: str = "**/*", *, allow_cloud: bool = True) -> list[str]:
    """Landing-relative paths under one tree, from disk and the bucket together.

    The union, deduplicated. Local-only files are ones not yet uploaded;
    remote-only files are the pruned ones. Either alone loses a set silently.
    """
    root = LANDING_ROOT / tree
    found: set[str] = set()
    if root.exists():
        found |= {p.relative_to(LANDING_ROOT).as_posix() for p in root.glob(pattern) if p.is_file()}

    if allow_cloud:
        try:
            store, prefix = _store_and_prefix()
            listed = store.list_sizes(f"{prefix}{tree}/")  # type: ignore[attr-defined]
            for key in listed:
                relative = key[len(prefix) :]
                if fnmatch.fnmatch(relative, f"{tree}/{pattern}") or fnmatch.fnmatch(
                    relative, f"{tree}/{pattern.replace('**/', '')}"
                ):
                    found.add(relative)
        except CloudUnavailable:
            # Local-only is a usable answer; an unreachable bucket is not a
            # reason to report an empty tree that exists on disk.
            pass
    return sorted(found)


def read(relative: str, *, allow_cloud: bool = True) -> bytes:
    """The file's bytes, fetching and caching from B2 when it is not local.

    Cached on the way through, so a backtest that reads a pruned archive pays
    the download once and then runs at local speed — and the next prune is free
    to remove it again.
    """
    local = LANDING_ROOT / relative
    if local.exists():
        return local.read_bytes()
    if not allow_cloud:
        msg = f"{relative} is not local and the cloud was not consulted"
        raise FileNotFoundError(msg)

    store, _ = _store_and_prefix()
    payload = store.get(remote_key(relative))  # type: ignore[attr-defined]
    local.parent.mkdir(parents=True, exist_ok=True)
    tmp = local.with_suffix(local.suffix + ".partial")
    tmp.write_bytes(payload)
    # Atomic, so an interrupted download cannot leave a truncated file that a
    # later read mistakes for the real thing.
    tmp.replace(local)
    return bytes(payload)


def is_local(relative: str) -> bool:
    return (LANDING_ROOT / relative).exists()
