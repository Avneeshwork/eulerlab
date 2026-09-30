"""`_session_bars` was rewritten for speed; this proves it returns the same list.

The old form filtered the whole window (`[c for c in window if c.ts.date() ==
day]`); the new one walks back from the tail. They agree for any input whose
bars are in time order, which is what every store in this platform returns —
and a backtest engine silently changing its answers to go faster would be a
much worse bug than the slowness it fixed.
"""

from __future__ import annotations

import datetime as dt

from eulerlab.intraday.papers import _session_bars
from eulerlab.intraday.tweezer import Candle


def _old_session_bars(window: list[Candle]) -> list[Candle]:
    """The implementation this replaced, kept here as the oracle."""
    day = window[-1].ts.date()
    return [c for c in window if c.ts.date() == day]


def _bars(start: dt.datetime, count: int, step_minutes: int = 1) -> list[Candle]:
    return [
        Candle(
            ts=start + dt.timedelta(minutes=i * step_minutes),
            open=100.0 + i,
            high=101.0 + i,
            low=99.0 + i,
            close=100.5 + i,
            volume=float(i),
        )
        for i in range(count)
    ]


def test_agrees_on_a_us_style_multi_session_window() -> None:
    """Six-and-a-half-hour sessions with an overnight gap between them."""
    window: list[Candle] = []
    for day in range(5):
        open_at = dt.datetime(2026, 6, 1 + day, 13, 30, tzinfo=dt.UTC)
        window += _bars(open_at, 390)
    assert _session_bars(window) == _old_session_bars(window)
    assert len(_session_bars(window)) == 390


def test_agrees_on_a_continuous_crypto_window() -> None:
    """No session at all — the whole UTC day, which is what crypto returns."""
    window = _bars(dt.datetime(2026, 6, 1, 0, 0, tzinfo=dt.UTC), 4320)
    assert _session_bars(window) == _old_session_bars(window)
    assert len(_session_bars(window)) == 1440


def test_agrees_when_the_last_session_has_a_single_bar() -> None:
    """The boundary the backwards walk is most likely to get wrong."""
    window = _bars(dt.datetime(2026, 6, 1, 13, 30, tzinfo=dt.UTC), 390)
    window += _bars(dt.datetime(2026, 6, 2, 13, 30, tzinfo=dt.UTC), 1)
    assert _session_bars(window) == _old_session_bars(window)
    assert len(_session_bars(window)) == 1


def test_agrees_when_the_window_is_one_session() -> None:
    """Nothing to walk back past — the loop must stop at index 0, not underflow."""
    window = _bars(dt.datetime(2026, 6, 1, 13, 30, tzinfo=dt.UTC), 12)
    assert _session_bars(window) == _old_session_bars(window)
    assert len(_session_bars(window)) == 12


def test_agrees_across_a_dst_boundary() -> None:
    """UTC dates do not shift with New York's clock, but the test is cheap."""
    window: list[Candle] = []
    for day in (
        dt.datetime(2026, 3, 7, 14, 30, tzinfo=dt.UTC),
        dt.datetime(2026, 3, 9, 13, 30, tzinfo=dt.UTC),
    ):
        window += _bars(day, 390)
    assert _session_bars(window) == _old_session_bars(window)


def test_agrees_on_a_session_spanning_a_utc_midnight() -> None:
    """Where the two forms *could* differ, and do not, because bars stay sorted.

    A window whose final bars cross midnight UTC has its last date split into a
    short trailing run. Both implementations key off `window[-1]`, so both
    return only that trailing run — the old one by filtering, the new one by
    stopping at the boundary.
    """
    window = _bars(dt.datetime(2026, 6, 1, 23, 55, tzinfo=dt.UTC), 20)
    assert _session_bars(window) == _old_session_bars(window)
    assert len(_session_bars(window)) == 15
