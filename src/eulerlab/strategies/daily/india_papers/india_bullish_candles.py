"""Bullish candles, held 5 days (India).

Source: Manoharan & Srinivasan (2019), candlestick patterns on Nifty 50 stocks.

One daily strategy from a paper on Indian equities. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from collections.abc import Sequence

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.features.panel import PanelRow
from eulerlab.strategies.daily.india_papers.common import (
    LIQUIDITY_WINDOW,
    PaperStrategy,
    liquid_universe,
)


def _real_bar(row: PanelRow) -> bool:
    return (
        row.has_range()
        and row.low <= min(row.open, row.close)
        and row.high >= max(row.open, row.close)
        and row.open > 0
    )


def _fell(rows: Sequence[PanelRow], i: int, days: int = 5) -> bool:
    """The close before bar `i` is below the close `days` bars earlier."""
    return i - 1 - days >= 0 and rows[i - 1].close < rows[i - 1 - days].close


def hammer(rows: Sequence[PanelRow], i: int) -> bool:
    """After a fall, a bar whose lower shadow is at least twice its body and
    half its range, with almost no upper shadow (Nison 1991)."""
    bar = rows[i]
    if not _real_bar(bar) or not _fell(rows, i):
        return False
    span = bar.high - bar.low
    body = abs(bar.close - bar.open)
    lower = min(bar.open, bar.close) - bar.low
    upper = bar.high - max(bar.open, bar.close)
    return lower >= 2 * body and lower >= 0.5 * span and upper <= 0.1 * span


def bullish_engulfing(rows: Sequence[PanelRow], i: int) -> bool:
    """After a fall, a rising bar whose body covers the previous falling bar's."""
    if i < 1:
        return False
    before, bar = rows[i - 1], rows[i]
    if not (_real_bar(before) and _real_bar(bar)) or not _fell(rows, i - 1):
        return False
    return (
        before.close < before.open
        and bar.close > bar.open
        and bar.open <= before.close
        and bar.close >= before.open
        and bar.close - bar.open > before.open - before.close
    )


def rising_window(rows: Sequence[PanelRow], i: int) -> bool:
    """A gap up: the bar's low is above the previous bar's high."""
    if i < 1:
        return False
    before, bar = rows[i - 1], rows[i]
    return _real_bar(before) and _real_bar(bar) and bar.low > before.high


BULLISH_CANDLES = (hammer, bullish_engulfing, rising_window)


class CandleHold(Strategy):
    """Hold a stock for `hold` days after a bullish candle (Manoharan 2019).

    Among the `top` most-traded stocks at each date. A stock is held while
    any of its last `hold` bars shows a pattern, so a candle on day d is held
    from the close of d+1 (when the engine fills) for `hold` closes. Each
    holding gets 1/`slots` of capital, or an equal share when more than
    `slots` qualify, so one signal never puts everything in one stock.
    """

    rebalance_every = 1

    def __init__(self, name: str, *, top: int = 50, hold: int = 5, slots: int = 10) -> None:
        self.name = name
        self.top = top
        self.hold = hold
        self.slots = slots
        self.lookback = LIQUIDITY_WINDOW + 10
        self.hold_unchanged = True

    def target_weights(self, view: MarketView) -> dict[str, float]:
        held: list[str] = []
        for symbol in liquid_universe(view, self.top):
            rows = view.history[symbol]
            n = len(rows)
            if n <= self.hold + 6:
                continue
            if any(
                pattern(rows, i) for i in range(n - self.hold, n) for pattern in BULLISH_CANDLES
            ):
                held.append(symbol)
        if not held:
            return {}
        return dict.fromkeys(held, 1.0 / max(len(held), self.slots))


STRATEGIES = (
    PaperStrategy(
        "india_bullish_candles",
        "Bullish candles, held 5 days (India)",
        "manoharan-2019-candlestick-india",
        "Manoharan & Srinivasan (2019), candlestick patterns on Nifty 50 stocks",
        "Buy a liquid stock after a hammer, a bullish engulfing bar or a rising window, and hold it five days.",
        (
            "Point-in-time 50 most-traded stocks; hammer and bullish engulfing after a "
            "five-day fall, or any gap up; at most 10% in each holding.",
            "The paper's pattern definitions are its software's and unstated; these are Nison's.",
        ),
        70,
        lambda: CandleHold("india_bullish_candles"),
    ),
)
