"""`list_sizes_fanned` must return exactly what a plain listing would.

It is a speed optimisation over `list_sizes`, and the only thing that makes it
safe is that the answer is identical. A fanned listing that quietly dropped
keys would read as "not in the bucket": the sync would re-upload them and the
census would undercount, both without complaining.
"""

from __future__ import annotations

from typing import Any

from eulerlab.ingest.cloud import S3ObjectStore


class FakeS3Client:
    """A boto3 client stub that paginates the way S3 does, 1,000 at a time."""

    def __init__(self, keys: dict[str, int]) -> None:
        self.keys = keys
        self.calls = 0

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        prefix = kwargs.get("Prefix", "")
        delimiter = kwargs.get("Delimiter")
        matching = sorted(k for k in self.keys if k.startswith(prefix))

        contents, groups = [], set()
        for key in matching:
            rest = key[len(prefix) :]
            if delimiter and delimiter in rest:
                groups.add(prefix + rest.split(delimiter)[0] + delimiter)
            else:
                contents.append(key)

        page = sorted(contents) + sorted(groups)
        start = int(kwargs.get("ContinuationToken") or 0)
        window = page[start : start + kwargs.get("MaxKeys", 1000)]
        truncated = start + len(window) < len(page)
        return {
            "Contents": [{"Key": k, "Size": self.keys[k]} for k in window if k in self.keys],
            "CommonPrefixes": [{"Prefix": k} for k in window if k not in self.keys],
            "IsTruncated": truncated,
            "NextContinuationToken": str(start + len(window)) if truncated else None,
        }


def _store(keys: dict[str, int]) -> tuple[S3ObjectStore, FakeS3Client]:
    store = object.__new__(S3ObjectStore)
    client = FakeS3Client(keys)
    store._client = client
    store._bucket = "bucket"
    return store, client


def test_fanned_matches_serial_across_many_trees() -> None:
    keys = {f"root/{tree}/{n:05d}.gz": n for tree in ("cm", "fo", "us", "fx") for n in range(1500)}
    store, _ = _store(keys)
    assert store.list_sizes_fanned("root/") == store.list_sizes("root/")
    assert len(store.list_sizes_fanned("root/")) == 6000


def test_loose_keys_past_the_first_page_are_not_dropped() -> None:
    """The delimited request was a single call, so key 1,001 vanished.

    Everything in this bucket lives inside a tree today, which is the only
    reason the bug was invisible.
    """
    keys = {f"root/loose-{n:05d}.gz": n for n in range(2500)}
    keys.update({f"root/{tree}/{n:03d}.gz": n for tree in ("cm", "fo") for n in range(10)})
    store, _ = _store(keys)

    fanned = store.list_sizes_fanned("root/")

    assert len(fanned) == len(keys) == 2520
    assert fanned == store.list_sizes("root/")
    assert "root/loose-02499.gz" in fanned, "a key past the first page was dropped"


def test_a_single_group_takes_the_plain_path() -> None:
    """Fanning out over one prefix buys nothing and costs a request."""
    keys = {f"root/only/{n:03d}.gz": n for n in range(50)}
    store, client = _store(keys)
    before = client.calls
    assert store.list_sizes_fanned("root/") == keys
    assert client.calls - before <= 3


def test_an_empty_prefix_is_empty_not_an_error() -> None:
    store, _ = _store({})
    assert store.list_sizes_fanned("root/") == {}
