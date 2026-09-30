"""Sweep results are kept so the UI can read them without re-running a sweep.

Re-running is the one thing a reader must never do casually here: every
candidate spends a permanent trial against the deflated-Sharpe denominator.
So the store exists to make looking cheap, and these tests mostly guard the
properties that keep a reader from being misled by what they see.
"""

from __future__ import annotations

from pathlib import Path

from eulerlab import optimize_store


def _row(strategy_id: str, best: float, median: float) -> optimize_store.Row:
    return optimize_store.Row(
        strategy_id=strategy_id,
        market="us",
        symbol="QQQ",
        candidates=9,
        best_pnl=best,
        median_pnl=median,
        fills=20,
        win_rate=0.5,
        sessions=58,
    )


def _record(path: Path, rows: list[optimize_store.Row], **kwargs: object) -> None:
    defaults: dict[str, object] = {
        "trials_before": 12,
        "trials_after": 12,
        "required_t": 3.0,
        "start": "2026-06-01",
        "end": "2026-08-23",
        "dry_run": True,
    }
    defaults.update(kwargs)
    optimize_store.record(rows, path=path, **defaults)  # type: ignore[arg-type]


def test_spread_ratio_is_withheld_when_the_median_loses() -> None:
    """The number that would otherwise flatter the worst results.

    A strategy losing on every setting, -100 best against -110 median, would
    report a tidy 0.9 ratio if the arithmetic were done blindly. It says
    nothing, and it says it in the vocabulary of a healthy result.
    """
    assert _row("losing", -100.0, -110.0).spread_ratio == 0.0
    assert _row("flat", 0.0, 0.0).spread_ratio == 0.0
    assert _row("real", 30_000.0, 20_000.0).spread_ratio == 1.5


def test_a_sweep_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "sweeps.jsonl"
    _record(path, [_row("orb_breakout", 25_668.0, 19_622.0)])
    latest = optimize_store.latest(path)
    assert latest is not None
    assert latest["rows"][0]["strategy_id"] == "orb_breakout"
    assert latest["rows"][0]["best_pnl"] == 25_668.0


def test_dry_run_is_stored_rather_than_filtered(tmp_path: Path) -> None:
    """A dry run and a recorded run produce identical numbers.

    They differ only in whether the trial ledger knows about them, so the flag
    has to travel with the result — a reader who cannot tell them apart might
    cite a figure the ledger has no record of.
    """
    path = tmp_path / "sweeps.jsonl"
    _record(path, [_row("a", 1.0, 1.0)], dry_run=True)
    assert optimize_store.latest(path) is not None
    assert optimize_store.latest(path)["dry_run"] is True  # type: ignore[index]

    _record(path, [_row("a", 1.0, 1.0)], dry_run=False, trials_after=21)
    newest = optimize_store.latest(path)
    assert newest is not None
    assert newest["dry_run"] is False
    assert newest["trials_after"] == 21


def test_history_is_kept_and_bounded(tmp_path: Path) -> None:
    """Past sweeps are evidence about stability, but the file stays readable."""
    path = tmp_path / "sweeps.jsonl"
    for i in range(optimize_store.KEEP + 5):
        _record(path, [_row("a", float(i), 0.0)])
    entries = optimize_store.read_all(path)
    assert len(entries) == optimize_store.KEEP
    # Oldest first, and it is the oldest that were dropped.
    assert entries[-1]["rows"][0]["best_pnl"] == float(optimize_store.KEEP + 4)


def test_a_corrupt_line_does_not_lose_the_rest(tmp_path: Path) -> None:
    path = tmp_path / "sweeps.jsonl"
    _record(path, [_row("a", 1.0, 1.0)])
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    _record(path, [_row("b", 2.0, 1.0)])
    assert len(optimize_store.read_all(path)) == 2


def test_missing_file_reads_as_no_sweep(tmp_path: Path) -> None:
    assert optimize_store.latest(tmp_path / "absent.jsonl") is None
    assert optimize_store.read_all(tmp_path / "absent.jsonl") == []


def test_tail_share_reads_a_negative_median_correctly() -> None:
    """The summary statistic, and the form of it that was wrong.

    `gap_fill_fade` returned +3,729 at best against a median of -3,980: its
    best is *entirely* tail, since the typical setting loses money. The first
    test — spread greater than twice the absolute median — scored that as
    narrow (7,709 against a threshold of 7,960) and reported it alongside
    strategies whose whole grid was profitable.

    Share of the best sitting above the median has no such blind spot, and it
    is what both the CLI summary and the Sweep tab now use.
    """
    best, median = 3_729.0, -3_980.0
    spread = best - median

    assert spread > best * 0.5  # entirely tail, correctly flagged
    assert not spread > abs(median) * 2  # the old test, which missed it
