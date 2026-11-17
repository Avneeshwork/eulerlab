"""The relative-volume screen: its baseline, its cache, and its cost.

`orb_stock_in_play` is the one signal whose selection step *is* the strategy —
Zarattini's own summary says the plain breakout is weak and the screen does
almost all the work. So the baseline being right matters more here than the
entry rule does.
"""

from __future__ import annotations

import datetime as dt

from eulerlab.intraday.tweezer import Candle
from eulerlab.strategies.intraday import papers
from eulerlab.strategies.intraday.papers import PaperRules


def _session(day: dt.date, *, volume: float, bars: int = 12) -> list[Candle]:
    """One flat session at a given volume per bar."""
    base = dt.datetime.combine(day, dt.time(13, 30), tzinfo=dt.UTC)
    return [
        Candle(
            ts=base + dt.timedelta(minutes=i),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=volume,
        )
        for i in range(bars)
    ]


def test_baseline_is_bounded_to_the_papers_window() -> None:
    """14 prior sessions, not every session in the backtest.

    Built so the two answers differ: twenty quiet days, then fourteen loud
    ones, then today. Averaging all 34 gives a much lower baseline than
    averaging the last 14, so a screen that fires on one will not on the other.
    """
    window: list[Candle] = []
    for i in range(20):
        window += _session(dt.date(2026, 6, 1) + dt.timedelta(days=i), volume=10.0)
    for i in range(14):
        window += _session(dt.date(2026, 7, 1) + dt.timedelta(days=i), volume=100.0)
    window += _session(dt.date(2026, 8, 3), volume=100.0)

    papers._RELATIVE_VOLUME_CACHE.clear()
    rules = PaperRules(orb_relative_volume_min=1.0)
    outcome = papers.orb_stock_in_play(window, rules, 1_000_000.0)

    # Against the correct 14-day baseline today is merely average (ratio 1.0),
    # so it clears a 1.0 screen only just. Against all 34 sessions the baseline
    # would be ~63 and the ratio ~1.6 — a different, easier screen.
    key = next(iter(papers._RELATIVE_VOLUME_CACHE))
    history = papers._RELATIVE_VOLUME_CACHE[key]
    assert len(history) == 14
    assert set(history) == {100.0 * 5}
    assert outcome is not None


def test_cache_does_not_confuse_two_series() -> None:
    """The bug the key was widened to prevent.

    Every US series here starts at the same instant, so a timestamp-only key
    served one symbol's volume baseline to another's scan — changing which days
    passed the screen with no error and no visible symptom.
    """
    papers._RELATIVE_VOLUME_CACHE.clear()
    rules = PaperRules()

    quiet: list[Candle] = []
    loud: list[Candle] = []
    for i in range(16):
        day = dt.date(2026, 6, 1) + dt.timedelta(days=i)
        quiet += _session(day, volume=10.0)
        loud += _session(day, volume=1000.0)

    papers.orb_stock_in_play(quiet, rules, 1_000_000.0)
    papers.orb_stock_in_play(loud, rules, 1_000_000.0)

    baselines = {tuple(v) for v in papers._RELATIVE_VOLUME_CACHE.values()}
    assert len(baselines) == 2, "two different series collapsed to one cache entry"


def test_cache_returns_the_same_answer_it_computed() -> None:
    """A memo that changes the result is not a memo."""
    window: list[Candle] = []
    for i in range(16):
        window += _session(dt.date(2026, 6, 1) + dt.timedelta(days=i), volume=50.0)

    rules = PaperRules()
    papers._RELATIVE_VOLUME_CACHE.clear()
    cold = papers.orb_stock_in_play(window, rules, 1_000_000.0)
    warm = papers.orb_stock_in_play(window, rules, 1_000_000.0)
    assert type(cold) is type(warm)
    assert repr(cold) == repr(warm)
