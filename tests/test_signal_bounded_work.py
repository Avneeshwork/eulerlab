"""A signal must read a bounded tail, not the whole backtest.

`detect` is called once per bar and handed every bar so far. A signal that
touches the whole window is therefore O(n) per call and O(n**2) per run, which
does not fail — it just gets slower until a long request stops returning. That
is exactly what happened: a 1,244-session NIFTYBEES request passed the 900s job
cap and showed the operator nothing, while an 83-session one was fine.

Timing tests are flaky, so this asserts the contract directly: how far back the
signal actually reaches.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from eulerlab.intraday.papers import PaperRules, ou_mean_reversion
from eulerlab.intraday.tweezer import Candle


class Watched(Sequence[Candle]):
    """A candle list that remembers the earliest index anyone looked at."""

    def __init__(self, items: list[Candle]) -> None:
        self._items = items
        self.lowest = len(items)

    def __len__(self) -> int:
        return len(self._items)

    def __getitem__(self, index):  # type: ignore[no-untyped-def]
        if isinstance(index, slice):
            start, stop, step = index.indices(len(self._items))
            if stop > start:
                self.lowest = min(self.lowest, start)
            return self._items[start:stop:step]
        resolved = index + len(self._items) if index < 0 else index
        self.lowest = min(self.lowest, resolved)
        return self._items[index]


def _candles(count: int) -> list[Candle]:
    start = datetime(2026, 8, 20, 9, 15, tzinfo=UTC)
    out = []
    for step in range(count):
        price = 100.0 + (step % 17) * 0.1
        out.append(
            Candle(
                ts=start + timedelta(minutes=step),
                open=price,
                high=price + 0.05,
                low=price - 0.05,
                close=price,
                volume=1000,
            )
        )
    return out


def test_ou_reversion_reads_only_its_lookback() -> None:
    """It needs 61 bars. It must not touch the 4,000 before them."""
    rules = PaperRules()
    needed = rules.ou_lookback + 1
    window = Watched(_candles(4000))

    ou_mean_reversion(window, rules, 1_000_000.0)

    reached_back = len(window) - window.lowest
    assert reached_back <= needed, (
        f"reached {reached_back} bars back for a {needed}-bar lookback — "
        "that is O(n) per call and quadratic across a run"
    )


@pytest.mark.parametrize("size", [200, 4000])
def test_ou_reversion_is_unchanged_by_leading_history(size: int) -> None:
    """Bounding the window must not change the answer, only the work.

    The long and short forms are the same values — the last N closes of the
    whole window are the closes of the last N candles — and this is what makes
    the bound safe rather than an approximation.
    """
    rules = PaperRules()
    tail = _candles(size)[-(rules.ou_lookback + 1) :]
    long_form = ou_mean_reversion(_candles(size), rules, 1_000_000.0)
    short_form = ou_mean_reversion(tail, rules, 1_000_000.0)
    assert type(long_form) is type(short_form)
    assert repr(long_form) == repr(short_form)
