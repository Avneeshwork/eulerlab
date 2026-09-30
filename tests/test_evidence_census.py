"""One reader that knows every place evidence lives.

Eight stores accumulated, each reasonable alone. The bug they produced was not
in any of them: the noise bar is computed from "how many configurations have
ever been evaluated", two files answer that, and the bar read one — understating
the denominator by an order of magnitude, so every result was judged against a
bar never charged for the search that found it.

Nothing was wrong with either file. What was missing was anyone whose job it was
to know both existed.
"""

from __future__ import annotations

from eulerlab import evidence


def test_the_two_denominators_agree() -> None:
    """The guard that would have caught the original bug.

    `research/budget.searches_run` computes the bar's denominator directly;
    `evidence.bar_denominator` sums the stores that declare they count. They
    must be the same number, and a new store that should count but is not
    wired into `budget` breaks this rather than quietly lowering the bar.
    """
    from eulerlab.research.budget import searches_run

    assert evidence.bar_denominator() == searches_run()


def test_every_store_declares_whether_it_counts() -> None:
    """No store may be ambiguous about the correction it feeds.

    Getting this wrong in either direction is a defect: too few flatters every
    result, too many blocks work that should pass.
    """
    for store in evidence.stores():
        assert isinstance(store.counts_toward_bar, bool)
        assert store.holds, f"{store.name} does not say what it holds"


def test_the_two_counted_stores_are_the_expected_ones() -> None:
    """Pinned by name, so adding a third is a decision rather than a drift.

    A new store that counts toward the bar changes every historical result's
    standing. That should require editing this test.
    """
    counted = {s.name for s in evidence.stores() if s.counts_toward_bar}
    assert counted == {"trial_ledger", "trials"}


def test_a_directory_store_counts_rows_not_files() -> None:
    """The bug this module committed against itself.

    Workspace runs are `.jsonl` with many rows per file; reports are `.json`,
    one per file. A `*.json` glob reported thirty-one strategies' runs as zero —
    a census missing a store, in the module written to stop exactly that.
    """
    runs = next(s for s in evidence.stores() if s.name == "workspace_runs")
    reports = next(s for s in evidence.stores() if s.name == "workspace_reports")
    # Both are directories; neither should read as empty while the other has data.
    assert runs.path.is_dir() or runs.rows == 0
    assert reports.path.is_dir() or reports.rows == 0
    if reports.rows > 0:
        assert runs.rows > 0, "reports exist but runs read as zero — the glob is wrong again"
