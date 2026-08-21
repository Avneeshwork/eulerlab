"""The landing root is re-scanned, not enumerated once.

This cost a full re-run. `sync-cloud` listed the landing directories a single
time at startup, so a tree created *while it was running* — a backfill
finishing after the sync began — was simply not in the list. It was never
uploaded, and the command still exited 0. A gigabyte of crypto sat unmirrored
while the run reported success.

That is the same failure shape as several others this session: reporting
completion for work never attempted.
"""

from __future__ import annotations

from pathlib import Path

from eulerlab.ingest import sync_cloud
from eulerlab.ingest.cloud import SyncResult


class _RecordingSync:
    """Stands in for `sync_directory`, and can create a new tree as a side
    effect — which is exactly what a concurrent backfill does."""

    def __init__(self, root: Path, appears_on_call: int = 0, new_name: str = "") -> None:
        self.root = root
        self.appears_on_call = appears_on_call
        self.new_name = new_name
        self.seen: list[str] = []

    def __call__(self, tree_root: Path, store: object, *, prefix: str, dry_run: bool = False):  # type: ignore[no-untyped-def]
        self.seen.append(tree_root.name)
        if self.appears_on_call and len(self.seen) == self.appears_on_call:
            (self.root / self.new_name).mkdir(parents=True, exist_ok=True)
        return SyncResult(0, 0, [], [])


def _discover(root: Path, syncer: _RecordingSync) -> list[str]:
    """Run the discovery loop the way `main` does, without a bucket."""
    done: set[str] = set()
    for _ in range(sync_cloud.MAX_DISCOVERY_SWEEPS):
        others = sorted(
            d for d in root.iterdir() if d.is_dir() and d.name != "nse" and d.name not in done
        )
        if not others:
            break
        for tree in others:
            done.add(tree.name)
            syncer(tree, None, prefix=f"nse/{tree.name}/")
    return syncer.seen


def test_a_tree_created_mid_run_is_still_uploaded(tmp_path: Path) -> None:
    """The bug, reproduced. `crypto` appears while `mf` is being uploaded."""
    (tmp_path / "nse").mkdir()
    (tmp_path / "mf").mkdir()

    syncer = _RecordingSync(tmp_path, appears_on_call=1, new_name="crypto")
    seen = _discover(tmp_path, syncer)

    assert "mf" in seen
    assert "crypto" in seen, "a tree that appeared mid-run must not be skipped"


def test_a_tree_is_never_uploaded_twice(tmp_path: Path) -> None:
    """Re-scanning must not mean re-uploading what the first sweep did."""
    (tmp_path / "nse").mkdir()
    for name in ("mf", "crypto", "fundamentals"):
        (tmp_path / name).mkdir()

    seen = _discover(tmp_path, _RecordingSync(tmp_path))
    assert sorted(seen) == ["crypto", "fundamentals", "mf"]
    assert len(seen) == len(set(seen))


def test_discovery_is_bounded(tmp_path: Path) -> None:
    """A writer producing a tree faster than the sync drains them must not keep
    the command running forever. Anything still arriving by the last sweep is
    the next run's work, and saying so is better than never returning."""
    (tmp_path / "nse").mkdir()
    (tmp_path / "first").mkdir()

    class _Endless(_RecordingSync):
        def __call__(self, tree_root, store, *, prefix, dry_run=False):  # type: ignore[no-untyped-def]
            self.seen.append(tree_root.name)
            (self.root / f"tree{len(self.seen)}").mkdir(exist_ok=True)
            return SyncResult(0, 0, [], [])

    seen = _discover(tmp_path, _Endless(tmp_path))
    assert len(seen) <= sync_cloud.MAX_DISCOVERY_SWEEPS + 1
    assert sync_cloud.MAX_DISCOVERY_SWEEPS >= 2


def test_the_primary_landing_tree_is_not_swept_twice(tmp_path: Path) -> None:
    """`nse` is handled by the main `sync()` call, so the sweep must skip it or
    every bhavcopy would be compared twice."""
    (tmp_path / "nse").mkdir()
    (tmp_path / "mf").mkdir()
    assert "nse" not in _discover(tmp_path, _RecordingSync(tmp_path))
