"""`sync-cloud --only`: one dataset uploaded as soon as it is downloaded.

`make daily` used to download everything and upload once at the end, behind a
step that can take ten hours; a run stopped before then had uploaded nothing
(2026-10-13).
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from eulerlab.ingest import sync_cloud
from eulerlab.ingest.cloud import StorageConfig
from eulerlab.ingest.landing import Landing

CONFIG = StorageConfig(
    endpoint_url="https://s3.us-west-004.backblazeb2.com",
    bucket="eulerlab-landing",
    prefix="nse/",
)


class ListingStore:
    """A bucket in memory that records every prefix it is asked to list."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.listed: list[str] = []

    def list_sizes(self, prefix: str) -> dict[str, int]:
        self.listed.append(prefix)
        return {k: len(v[0]) for k, v in self.objects.items() if k.startswith(prefix)}

    def head_sha256(self, key: str) -> str | None:
        found = self.objects.get(key)
        return found[1] if found else None

    def put(self, key: str, payload: bytes, sha256: str) -> None:
        self.objects[key] = (payload, sha256)


def _landing(root: Path) -> Landing:
    landing = Landing(root)
    for day in (1, 2):
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


def _root(tmp_path: Path) -> tuple[Path, Path]:
    """A landing root with the bhavcopy tree and two others."""
    root = tmp_path / "landing"
    _landing(root / "nse")
    for name, files in (("crypto", ("BTCUSDT/2026-10.jsonl.gz",)), ("mf", ("navall/a.jsonl.gz",))):
        for file in files:
            path = root / name / file
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"{name}:{file}".encode())
    return root, root / "nse"


def test_only_the_named_tree_is_uploaded_and_only_its_prefix_is_listed(tmp_path: Path) -> None:
    root, nse = _root(tmp_path)
    store = ListingStore()
    assert sync_cloud.mirror_trees(["crypto"], store, CONFIG, nse, root) == 0
    assert set(store.objects) == {f"{CONFIG.prefix}crypto/BTCUSDT/2026-10.jsonl.gz"}
    assert store.listed == [f"{CONFIG.prefix}crypto/"], "not the whole bucket"


def test_a_second_run_uploads_nothing(tmp_path: Path) -> None:
    root, nse = _root(tmp_path)
    store = ListingStore()
    sync_cloud.mirror_trees(["crypto", "mf"], store, CONFIG, nse, root)
    held = dict(store.objects)
    assert sync_cloud.mirror_trees(["crypto", "mf"], store, CONFIG, nse, root) == 0
    assert store.objects == held


def test_the_bhavcopy_tree_goes_by_its_manifest_and_lists_only_its_folders(tmp_path: Path) -> None:
    root, nse = _root(tmp_path)
    full = ListingStore()
    sync_cloud.mirror_trees(["nse", "crypto", "mf"], full, CONFIG, nse, root)

    store = ListingStore()
    assert sync_cloud.mirror_trees(["nse"], store, CONFIG, nse, root) == 0
    bhavcopy = {k for k in full.objects if "/crypto/" not in k and "/mf/" not in k}
    assert set(store.objects) == bhavcopy and bhavcopy
    assert all(p != CONFIG.prefix and p.startswith(CONFIG.prefix) for p in store.listed)
    assert not any("crypto" in p or "mf" in p for p in store.listed)

    # A file pruned from this machine but in the manifest is not sent again.
    for path in nse.rglob("*"):
        if path.is_file() and path.name != "manifest.jsonl":
            path.unlink()
    before = dict(store.objects)
    assert sync_cloud.mirror_trees(["nse"], store, CONFIG, nse, root) == 0
    assert store.objects == before


def test_a_tree_with_nothing_local_is_skipped_not_failed(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    root, nse = _root(tmp_path)
    store = ListingStore()
    assert sync_cloud.mirror_trees(["fundamentals", "mf"], store, CONFIG, nse, root) == 0
    assert "fundamentals: nothing on this machine" in capsys.readouterr().out
    assert any("/mf/" in key for key in store.objects)


def test_dry_run_sends_nothing(tmp_path: Path) -> None:
    root, nse = _root(tmp_path)
    store = ListingStore()
    assert sync_cloud.mirror_trees(["nse", "crypto"], store, CONFIG, nse, root, dry_run=True) == 0
    assert store.objects == {}


def test_a_name_that_is_not_a_folder_name_is_refused_before_any_request(tmp_path: Path) -> None:
    args = argparse.Namespace(landing=tmp_path / "nse", landing_root=tmp_path, dry_run=False)
    for bad in ("../secrets", "a/b", ".env", ""):
        assert sync_cloud.mirror_only([bad], args, CONFIG) == 2


def test_then_delete_removes_only_what_the_bucket_holds(tmp_path: Path) -> None:
    root, nse = _root(tmp_path)
    store = ListingStore()
    assert sync_cloud.mirror_trees(["crypto"], store, CONFIG, nse, root, then_delete=True) == 0
    assert not list((root / "crypto").rglob("*.gz")), "uploaded, so removed"
    assert any((root / "mf").rglob("*.gz")), "a tree that was not named is untouched"
    assert f"{CONFIG.prefix}crypto/BTCUSDT/2026-10.jsonl.gz" in store.objects


def test_then_delete_keeps_a_file_whose_upload_failed_or_differs(tmp_path: Path) -> None:
    root, nse = _root(tmp_path)

    class Refusing(ListingStore):
        def put(self, key: str, payload: bytes, sha256: str) -> None:
            raise RuntimeError("bucket said no")

    assert sync_cloud.mirror_trees(["crypto"], Refusing(), CONFIG, nse, root, then_delete=True) == 1
    assert any((root / "crypto").rglob("*.gz")), "not in the bucket, so kept"

    # In the bucket at a different size: kept as well.
    store = ListingStore()
    store.objects[f"{CONFIG.prefix}mf/navall/a.jsonl.gz"] = (b"x", "")
    file = root / "mf" / "navall" / "a.jsonl.gz"
    from eulerlab.ingest.prune_local import prune_tree

    kept = prune_tree(root, "mf", store, prefix=CONFIG.prefix, dry_run=False)
    assert file.exists() and kept.kept_size_mismatch == [file]


def test_then_delete_on_the_bhavcopy_tree_keeps_its_manifest(tmp_path: Path) -> None:
    root, nse = _root(tmp_path)
    store = ListingStore()
    assert sync_cloud.mirror_trees(["nse"], store, CONFIG, nse, root, then_delete=True) == 0
    left = [p.name for p in nse.rglob("*") if p.is_file()]
    assert left == ["manifest.jsonl"], "the record of what was landed is never deleted"
    assert not any("crypto" in p or "/mf/" in p for p in store.listed)
    # Nothing local now; a second run uploads nothing and deletes nothing.
    held = dict(store.objects)
    assert sync_cloud.mirror_trees(["nse"], store, CONFIG, nse, root, then_delete=True) == 0
    assert store.objects == held


def test_a_dry_run_with_delete_changes_nothing(tmp_path: Path) -> None:
    root, nse = _root(tmp_path)
    store = ListingStore()
    sync_cloud.mirror_trees(["crypto"], store, CONFIG, nse, root)
    sync_cloud.mirror_trees(["crypto"], store, CONFIG, nse, root, dry_run=True, then_delete=True)
    assert any((root / "crypto").rglob("*.gz"))


def _nightly() -> list[str]:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    return makefile.split("\ndaily-run:\n", 1)[1].split("\n\n", 1)[0].splitlines()


def _trees(lines: list[str], *, deleting: bool) -> set[str]:
    return {
        tree
        for line in lines
        if "upload-tree TREES=" in line and ("DELETE=1" in line) == deleting
        for tree in line.split('TREES="')[1].split('"')[0].split()
    }


def test_the_nightly_job_downloads_uploads_and_deletes_one_dataset_at_a_time() -> None:
    body = _nightly()
    assert _trees(body, deleting=True) >= {
        "nse",
        "mf",
        "calendar",
        "kite_minute",
        "crypto",
        "fx",
        "news",
        "names",
        "marketdata",
        "us",
    }
    # Each download is followed at once by its own upload.
    for module, tree in (
        ("eulerlab.ingest.nse_eod", "nse"),
        ("eulerlab.ingest.mf_backfill", "mf"),
        ("eulerlab.ingest.forexfactory", "calendar"),
        ("eulerlab.ingest.crypto_fill", "crypto"),
        ("eulerlab.ingest.fx_bulk_backfill", "fx"),
        ("eulerlab.ingest.news", "news"),
    ):
        at = next(i for i, line in enumerate(body) if f"-m {module}" in line)
        assert f'upload-tree TREES="{tree}' in body[at + 1], module


def test_files_a_build_reads_are_deleted_only_after_that_build() -> None:
    body = _nightly()

    def line_of(text: str) -> int:
        return next(i for i, line in enumerate(body) if text in line)

    assert line_of('TREES="nse" DELETE=1') > line_of("paper-daily")
    assert line_of('TREES="nse" DELETE=1') > line_of("build-panel")
    assert line_of('TREES="us" DELETE=1') > line_of("build-us-panel")
    # The full sweep and the prune still run last.
    assert line_of("sync-cloud") > line_of('TREES="us" DELETE=1')
    assert line_of("prune-local") > line_of("sync-cloud")
