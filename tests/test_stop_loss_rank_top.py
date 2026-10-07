"""The stop-loss strategy's bookkeeping, on a two-stock view."""

from __future__ import annotations

from datetime import date, timedelta

from eulerlab.backtest.india_papers import StopLossRankTop
from eulerlab.backtest.strategy import MarketView


class _Row:
    def __init__(self, day: date, close: float) -> None:
        self.day = day
        self.close = close


def _view(day: date, closes: dict[str, list[float]], start: date) -> MarketView:
    history = {
        s: [_Row(start + timedelta(days=i), c) for i, c in enumerate(cs)]
        for s, cs in closes.items()
    }
    return MarketView(as_of=day, history=history)  # type: ignore[arg-type]


def test_a_stopped_name_goes_to_cash_and_the_rest_are_untouched() -> None:
    strategy = StopLossRankTop(
        "t",
        lambda rows: 0.0,
        rank_every=5,
        stop=0.05,
        reinvest=False,
        fraction=1.0,
        highest=True,
        lookback=1,
    )
    # Bypass the liquid-universe ranking: the first call holds A and B.
    strategy._set({"A": 0.5, "B": 0.5})
    strategy._calls = 1
    start = date(2020, 1, 1)
    day1 = start + timedelta(days=1)
    strategy._last_day = start
    # Day 1 is the fill day: entry prices are set, nothing is judged.
    out = strategy.target_weights(_view(day1, {"A": [100, 100], "B": [100, 100]}, start))
    assert out == {"A": 0.5, "B": 0.5}
    # Day 2: A falls 6%, B is flat.
    day2 = start + timedelta(days=2)
    out = strategy.target_weights(_view(day2, {"A": [100, 100, 94], "B": [100, 100, 100]}, start))
    assert out == {"B": 0.5}  # A sold, B keeps its exact weight, the rest is cash
    assert strategy.hold_unchanged
    assert strategy.stops_hit == 1
