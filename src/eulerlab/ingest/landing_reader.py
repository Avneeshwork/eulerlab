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
import threading
import time
from collections.abc import Iterable
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
_REFRESHING: set[tuple[str, str]] = set()
_REFRESH_LOCK = threading.Lock()


def _remote_listing(tree: str, pattern: str, *, stale_ok: bool = False) -> tuple[str, ...]:
    """Remote paths under a tree matching a pattern, memoised briefly.

    `stale_ok` is for a screen. When the listing is older than the limit it is
    returned as it is, at once, and brought up to date in the background, so
    the next request has the new one. Without it the request that happened to
    arrive after the five minutes waited for the whole enumeration: 5 s for
    the F&O tree and 57 s for crypto (measured 2026-10-12).

    Never for a backtest or an ingest. Those need the listing to be current,
    because a file pruned from disk a minute ago is only in the new one.
    """
    import time

    key = (tree, pattern)
    cached = _LISTED.get(key)
    now = time.monotonic()
    if cached is not None and now - cached[0] < _LISTING_TTL:
        return cached[1]
    if cached is not None and stale_ok:
        with _REFRESH_LOCK:
            start = key not in _REFRESHING
            _REFRESHING.add(key)
        if start:
            threading.Thread(
                target=_refresh_listing, args=(tree, pattern), daemon=True, name="listing"
            ).start()
        return cached[1]
    return _fetch_listing(tree, pattern)


def _refresh_listing(tree: str, pattern: str) -> None:
    try:
        _fetch_listing(tree, pattern)
    except Exception:  # the stale listing stays; the next request tries again
        pass
    finally:
        with _REFRESH_LOCK:
            _REFRESHING.discard((tree, pattern))


def _fetch_listing(tree: str, pattern: str) -> tuple[str, ...]:
    import time

    key = (tree, pattern)
    found: list[str] = []
    store, prefix = _store_and_prefix()
    # Narrowed by the pattern's literal prefix before asking the bucket.
    #
    # This listed the *whole tree* and filtered in Python. For
    # `us/minute/QQQ/*.jsonl.gz` that is 52,000 objects enumerated to find four,
    # and it sat in the hot path of every intraday backtest: loading QQQ's bars
    # took 58 seconds, of which 42 were this listing and 0.7 were the scan the
    # operator was waiting for.
    #
    # `_literal_prefix` already existed for `has_any` and was not used here. It
    # narrows only as far as the glob genuinely allows — `*/*/*.jsonl.gz` still
    # yields nothing and still lists the tree — so this changes how much is
    # asked for, never which paths match.
    scoped = f"{prefix}{tree}/{_literal_prefix(pattern)}"
    for remote in store.list_sizes(scoped):  # type: ignore[attr-defined]
        relative = remote[len(prefix) :]
        if _matches(relative, tree, pattern):
            found.append(relative)
    out = tuple(found)
    _LISTED[key] = (time.monotonic(), out)
    return out


def _matches(relative: str, tree: str, pattern: str) -> bool:
    """Whether a landing-relative path is what `tree`/`pattern` asked for."""
    return fnmatch.fnmatch(relative, f"{tree}/{pattern}") or fnmatch.fnmatch(
        relative, f"{tree}/{pattern.replace('**/', '')}"
    )


def prime_listing(keys: Iterable[str], prefix: str, wanted: Iterable[tuple[str, str]]) -> int:
    """Fill the listing cache from an enumeration of the bucket already held.

    The mirror lists the whole bucket to decide what to upload and then the
    census lists it again, tree by tree, to count what is now there — twelve
    more round trips for keys the first listing already returned. Handing that
    result here answers all twelve from memory.

    Only ever *adds* what a real listing would have produced, through the same
    `_matches` test the network path uses, so a primed entry and a fetched one
    cannot disagree. Returns how many pairs were filled.
    """
    import time

    relatives = [k[len(prefix) :] for k in keys if k.startswith(prefix)]
    now = time.monotonic()
    filled = 0
    for tree, pattern in wanted:
        found = tuple(sorted(r for r in relatives if _matches(r, tree, pattern)))
        _LISTED[(tree, pattern)] = (now, found)
        filled += 1
    return filled


def available(
    tree: str, pattern: str = "**/*", *, allow_cloud: bool = True, stale_ok: bool = False
) -> list[str]:
    """Landing-relative paths under one tree, from disk and the bucket together.

    The union, deduplicated. Local-only files are ones not yet uploaded;
    remote-only files are the pruned ones. Either alone loses a set silently.

    `stale_ok`: see `_remote_listing`. For screens only.
    """
    root = LANDING_ROOT / tree
    found: set[str] = set()
    if root.exists():
        found |= {p.relative_to(LANDING_ROOT).as_posix() for p in root.glob(pattern) if p.is_file()}

    if allow_cloud and cloud_enabled():
        # Local-only is a usable answer; an unreachable bucket is not a reason
        # to report an empty tree that exists on disk.
        with contextlib.suppress(CloudUnavailable):
            found |= set(_remote_listing(tree, pattern, stale_ok=stale_ok))
    return sorted(found)


def _literal_prefix(pattern: str) -> str:
    """The part of a glob before its first wildcard.

    `history/*.jsonl.gz` gives `history/`; `*/*/*.jsonl.gz` gives `""`. Used to
    narrow an existence probe as far as the pattern allows without pretending
    to evaluate the glob remotely.
    """
    out: list[str] = []
    segments = pattern.split("/")
    for segment in segments:
        if any(ch in segment for ch in "*?["):
            break
        out.append(segment)
    if len(out) == len(segments):
        # No wildcard at all: the pattern names one file. Its prefix is the
        # file itself, with no trailing slash. With one, a lookup for
        # `2026/10/2026-10-13_udiff.zip` asked the bucket for a folder of that
        # name, found nothing, and a file that had been pruned from this
        # machine read as missing everywhere: the overnight deployment's order
        # of 2026-10-13 was rejected for "lot size not found" on that account.
        return pattern
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


DOWNLOAD_ATTEMPTS = 5
DOWNLOAD_PAUSE_S = 5.0
"""Doubled after each failure: 5, 10, 20, 40 s. botocore's own three quick
retries were not enough on 2026-10-17, when one read timeout ended a scan of
418 stocks an hour in."""


def _get_with_retries(store: object, key: str) -> bytes:
    """`store.get`, retried with growing pauses on network failures only.

    A missing or forbidden object (`ClientError`) fails at once: waiting does
    not change it.
    """
    from botocore.exceptions import BotoCoreError

    pause = DOWNLOAD_PAUSE_S
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            payload: bytes = store.get(key)  # type: ignore[attr-defined]
            return payload
        except (BotoCoreError, ConnectionError, TimeoutError):
            if attempt == DOWNLOAD_ATTEMPTS:
                raise
            time.sleep(pause)
            pause *= 2
    raise AssertionError("unreachable")


def read(relative: str, *, allow_cloud: bool = True, cache: bool = True) -> bytes:
    """The file's bytes, fetching and caching from B2 when it is not local.

    Cached on the way through, so a backtest that reads a pruned archive pays
    the download once and then runs at local speed — and the next prune is free
    to remove it again. `cache=False` returns the bytes without keeping them: a
    pass over every stock's minute history is gigabytes, and on 2026-10-16 the
    first such pass filled the disk.
    """
    local = LANDING_ROOT / relative
    if local.exists():
        return local.read_bytes()
    if not allow_cloud or not cloud_enabled():
        msg = f"{relative} is not local and the cloud was not consulted"
        raise FileNotFoundError(msg)

    store, _ = _store_and_prefix()
    payload = _get_with_retries(store, remote_key(relative))
    if not cache:
        return bytes(payload)
    local.parent.mkdir(parents=True, exist_ok=True)
    tmp = local.with_suffix(local.suffix + ".partial")
    tmp.write_bytes(payload)
    # Atomic, so an interrupted download cannot leave a truncated file that a
    # later read mistakes for the real thing.
    tmp.replace(local)
    return bytes(payload)


def is_local(relative: str) -> bool:
    return (LANDING_ROOT / relative).exists()
