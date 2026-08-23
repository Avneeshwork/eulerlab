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

import contextlib
import fnmatch
import os
from functools import lru_cache
from pathlib import Path

LANDING_ROOT = Path("data/landing")

OFFLINE_ENV = "EULERLAB_NO_CLOUD"
"""Set to 1 to answer from disk alone.

Exists because the test suite had no business talking to Backblaze. Tests that
called `catalog.search` were transitively listing 34,000 remote keys, and when
one connection stalled the whole suite hung rather than failed — a hang and a
failure look identical from the outside, which is the worst property a test can
have. The timeouts in `cloud.py` bound the damage; this removes the reason.
"""


def cloud_enabled() -> bool:
    """Whether the bucket may be consulted at all."""
    return os.environ.get(OFFLINE_ENV, "").strip().lower() not in ("1", "true", "yes")


STORAGE_CONFIG = Path("config/storage.yaml")


class CloudUnavailable(RuntimeError):
    """The bucket could not be reached or is not configured.

    Raised rather than returning an empty listing, because "no files" and "I
    could not look" are different answers and only the second means the caller
    should stop rather than conclude.
    """


@lru_cache(maxsize=1)
@lru_cache(maxsize=1)
def _store_and_prefix() -> tuple[object, str]:
    """The object store and key prefix, built once per process.

    The docstring claimed "once per process" long before it was true — without
    the cache this built a fresh boto3 client on every call, and the capability
    matrix calls it repeatedly.
    """
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


_LISTING_TTL = 300.0
"""Seconds a remote tree listing is reused.

The listings exist to produce counts — "10 pairs, 34,051 pair-days" on the
capability matrix — and a count of an archive that only changes when `make
daily` runs does not need to be recomputed per request. Without this, rendering
the snapshot enumerated roughly **50,000 remote keys every time**: 34,051 for
fx, 14,280 for mutual funds and 1,200 for crypto, all to build description
strings. Measured at 51 to 189 seconds per call.

Five minutes, not indefinite: an ingest that lands data mid-session should show
up without restarting the API.
"""

_LISTED: dict[tuple[str, str], tuple[float, tuple[str, ...]]] = {}


def _remote_listing(tree: str, pattern: str) -> tuple[str, ...]:
    """Remote paths under a tree matching a pattern, memoised briefly."""
    import time

    key = (tree, pattern)
    cached = _LISTED.get(key)
    now = time.monotonic()
    if cached is not None and now - cached[0] < _LISTING_TTL:
        return cached[1]

    found: list[str] = []
    store, prefix = _store_and_prefix()
    for remote in store.list_sizes(f"{prefix}{tree}/"):  # type: ignore[attr-defined]
        relative = remote[len(prefix) :]
        if fnmatch.fnmatch(relative, f"{tree}/{pattern}") or fnmatch.fnmatch(
            relative, f"{tree}/{pattern.replace('**/', '')}"
        ):
            found.append(relative)
    out = tuple(found)
    _LISTED[key] = (now, out)
    return out


def available(tree: str, pattern: str = "**/*", *, allow_cloud: bool = True) -> list[str]:
    """Landing-relative paths under one tree, from disk and the bucket together.

    The union, deduplicated. Local-only files are ones not yet uploaded;
    remote-only files are the pruned ones. Either alone loses a set silently.
    """
    root = LANDING_ROOT / tree
    found: set[str] = set()
    if root.exists():
        found |= {p.relative_to(LANDING_ROOT).as_posix() for p in root.glob(pattern) if p.is_file()}

    if allow_cloud and cloud_enabled():
        # Local-only is a usable answer; an unreachable bucket is not a reason
        # to report an empty tree that exists on disk.
        with contextlib.suppress(CloudUnavailable):
            found |= set(_remote_listing(tree, pattern))
    return sorted(found)


def _literal_prefix(pattern: str) -> str:
    """The part of a glob before its first wildcard.

    `history/*.jsonl.gz` gives `history/`; `*/*/*.jsonl.gz` gives `""`. Used to
    narrow an existence probe as far as the pattern allows without pretending
    to evaluate the glob remotely.
    """
    out: list[str] = []
    for segment in pattern.split("/"):
        if any(ch in segment for ch in "*?["):
            break
        out.append(segment)
    return "/".join(out) + "/" if out else ""


def has_any(tree: str, pattern: str = "**/*", *, allow_cloud: bool = True) -> bool:
    """Whether a tree holds anything matching, without enumerating it.

    A boolean question that cost 35 paginated requests and 62 seconds, because
    the only tool available was "list every key and see". Disk is checked
    first because it is free, and the bucket is asked with a single MaxKeys=1
    probe narrowed to the pattern's literal prefix.

    The probe is deliberately **weaker than the glob**: it answers "objects
    exist under this prefix", not "objects match this pattern". For a
    capability check that is the right granularity — a tree with data at an
    unexpected depth is a different problem, and one worth failing loudly on
    rather than reporting as absent.
    """
    root = LANDING_ROOT / tree
    if root.exists() and next(root.glob(pattern), None) is not None:
        return True
    if not allow_cloud or not cloud_enabled():
        return False
    try:
        store, prefix = _store_and_prefix()
        return bool(store.any_under(f"{prefix}{tree}/{_literal_prefix(pattern)}"))  # type: ignore[attr-defined]
    except CloudUnavailable:
        return False


def read(relative: str, *, allow_cloud: bool = True) -> bytes:
    """The file's bytes, fetching and caching from B2 when it is not local.

    Cached on the way through, so a backtest that reads a pruned archive pays
    the download once and then runs at local speed — and the next prune is free
    to remove it again.
    """
    local = LANDING_ROOT / relative
    if local.exists():
        return local.read_bytes()
    if not allow_cloud or not cloud_enabled():
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
