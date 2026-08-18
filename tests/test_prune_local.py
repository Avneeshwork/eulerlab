"""prune-local's one job: never delete a file that isn't confirmed uploaded."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from eulerlab.ingest.prune_local import plan_and_prune


@dataclass
class FakeStore:
    """Implements ObjectStore. head_sha256/put are unused by prune-local but
    required to satisfy the protocol."""

    sizes: dict[str, int] = field(default_factory=dict)

    def list_sizes(self, prefix: str) -> dict[str, int]:
        return {k: v for k, v in self.sizes.items() if k.startswith(prefix)}

    def head_sha256(self, key: str) -> str | None:
        raise NotImplementedError

    def put(self, key: str, payload: bytes, sha256: str) -> None:
        raise NotImplementedError


def _tree(root: Path) -> None:
    (root / "nse" / "cm" / "2026" / "08").mkdir(parents=True)
    (root / "nse" / "cm" / "2026" / "08" / "2026-08-14_udiff.zip").write_bytes(b"aaaaa")
    (root / "kite_minute" / "HDFCBANK").mkdir(parents=True)
    (root / "kite_minute" / "HDFCBANK" / "a.parquet").write_bytes(b"bbbbbbb")
    (root / "nse" / "manifest.jsonl").write_text('{"trade_date":"x"}\n')
    (root / "kite_minute" / "manifest.jsonl").write_text('{"symbol":"x"}\n')


def test_a_confirmed_file_is_deleted(tmp_path: Path) -> None:
    _tree(tmp_path)
    store = FakeStore({"nse/cm/2026/08/2026-08-14_udiff.zip": 5})

    result = plan_and_prune(tmp_path, store, prefix="nse/", dry_run=False)

    assert len(result.deleted) == 1
    assert not (tmp_path / "nse" / "cm" / "2026" / "08" / "2026-08-14_udiff.zip").exists()


def test_an_unconfirmed_file_is_kept(tmp_path: Path) -> None:
    _tree(tmp_path)
    store = FakeStore()  # bucket empty

    result = plan_and_prune(tmp_path, store, prefix="nse/", dry_run=False)

    assert result.deleted == []
    assert result.kept_not_uploaded == 2
    assert (tmp_path / "nse" / "cm" / "2026" / "08" / "2026-08-14_udiff.zip").exists()


def test_a_size_mismatch_is_kept_not_force_deleted(tmp_path: Path) -> None:
    """Same trap as the cloud sync: never trust a name match alone."""
    _tree(tmp_path)
    store = FakeStore({"nse/cm/2026/08/2026-08-14_udiff.zip": 999})  # wrong size

    result = plan_and_prune(tmp_path, store, prefix="nse/", dry_run=False)

    assert result.deleted == []
    assert len(result.kept_size_mismatch) == 1
    assert (tmp_path / "nse" / "cm" / "2026" / "08" / "2026-08-14_udiff.zip").exists()


def test_kite_minute_files_use_the_right_key(tmp_path: Path) -> None:
    _tree(tmp_path)
    store = FakeStore({"nse/kite_minute/HDFCBANK/a.parquet": 7})

    result = plan_and_prune(tmp_path, store, prefix="nse/", dry_run=False)

    assert len(result.deleted) == 1
    assert not (tmp_path / "kite_minute" / "HDFCBANK" / "a.parquet").exists()


def test_dry_run_deletes_nothing(tmp_path: Path) -> None:
    _tree(tmp_path)
    store = FakeStore({"nse/cm/2026/08/2026-08-14_udiff.zip": 5})

    result = plan_and_prune(tmp_path, store, prefix="nse/", dry_run=True)

    assert len(result.deleted) == 1  # reported...
    assert (
        tmp_path / "nse" / "cm" / "2026" / "08" / "2026-08-14_udiff.zip"
    ).exists()  # ...not touched


def test_manifests_are_never_candidates_for_deletion(tmp_path: Path) -> None:
    _tree(tmp_path)
    # Even if something in the bucket happened to share the manifest's size.
    manifest_size = (tmp_path / "nse" / "manifest.jsonl").stat().st_size
    store = FakeStore({"nse/manifest.jsonl": manifest_size})

    result = plan_and_prune(tmp_path, store, prefix="nse/", dry_run=False)

    assert (tmp_path / "nse" / "manifest.jsonl").exists()
    assert all(p.name != "manifest.jsonl" for p in result.deleted)


def test_bytes_freed_matches_deleted_file_sizes(tmp_path: Path) -> None:
    _tree(tmp_path)
    store = FakeStore(
        {"nse/cm/2026/08/2026-08-14_udiff.zip": 5, "nse/kite_minute/HDFCBANK/a.parquet": 7}
    )

    result = plan_and_prune(tmp_path, store, prefix="nse/", dry_run=False)

    assert result.bytes_freed == 12
