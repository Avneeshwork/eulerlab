"""The shared panel cache, and the key that stops it serving the wrong index.

`_Panel` holds one copy of a 540 MB panel and a cache of back-adjusted price
indices. The index cache was keyed by the day-window alone, which was safe only
while every run saw every symbol. Once runs can be restricted to a universe,
that key is a silent correctness bug.
"""

from __future__ import annotations

from datetime import date

from eulerlab.api.server import _Panel, _universe_rows
from eulerlab.features.panel import PanelRow


def _row(symbol: str, day: date, close: float) -> PanelRow:
    return PanelRow(day=day, symbol=symbol, close=close, volume=1000.0, turnover=close * 1000.0)


def test_the_index_cache_is_keyed_by_universe_not_only_by_window() -> None:
    """The bug this pins: a nifty50 run at 800 days would hand its index to the
    next 800-day run over every symbol, which then has no adjusted prices for
    the symbols nifty50 never contained. Same window, different row set, and
    the second run reads the first run's prices."""
    panel = _Panel()
    day = date(2026, 1, 2)
    narrow = [_row("AAA", day, 100.0)]
    wide = [_row("AAA", day, 100.0), _row("BBB", day, 200.0)]

    first = panel.index(800, narrow, "nifty50")
    second = panel.index(800, wide, "all")

    assert set(first) == {"AAA"}
    assert set(second) == {"AAA", "BBB"}, "the wide run must not be served the narrow index"


def test_the_same_window_and_universe_is_still_cached() -> None:
    """The fix must not turn the cache off."""
    panel = _Panel()
    rows = [_row("AAA", date(2026, 1, 2), 100.0)]
    assert panel.index(800, rows, "all") is panel.index(800, rows, "all")


def test_all_means_every_symbol_in_the_panel() -> None:
    rows = [_row("AAA", date(2026, 1, 2), 1.0), _row("BBB", date(2026, 1, 2), 2.0)]
    kept, size = _universe_rows(rows, "all")
    assert kept == rows
    assert size == 2
