"""Turtle 20/10 breakout, liquid NSE stocks (GitHub rule).

Source: Harvey-Sun/TurtleTrading (GitHub, 2017).

One daily rule from a public GitHub repository. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence

from eulerlab.features import indicators
from eulerlab.features.panel import PanelRow
from eulerlab.strategies.daily.github.common import STATE_WINDOW, Age, PositionRule, _age, in_trade
from eulerlab.strategies.daily.india_papers import PaperStrategy


def prior_extreme(values: Sequence[float], window: int, *, highest: bool) -> list[float | None]:
    """At each i, the max (or min) of `values[i-window:i]`, the bars before i.

    Linear time with a monotonic deque: slicing a window at every bar made the
    Turtle rule cost ~5,000 operations per stock per day.
    """
    out: list[float | None] = [None] * len(values)
    kept: deque[int] = deque()
    for i, value in enumerate(values):
        if i >= window:
            out[i] = values[kept[0]]
        while kept and (values[kept[-1]] <= value if highest else values[kept[-1]] >= value):
            kept.pop()
        kept.append(i)
        if kept[0] <= i - window:
            kept.popleft()
    return out


def turtle_rule(rows: Sequence[PanelRow]) -> Age:
    """Harvey-Sun/TurtleTrading, its 20/10 system on stock dailies: in on a close
    above the prior 20-day high; out on a close below the prior 10-day low, or
    2 ATR(20) below the entry close. Units, pyramiding and the 'mean' exit
    variant are left out: one unit, the plain channel exit."""
    n = len(rows)
    if n < 22:
        return None
    bars = [r.ohlc() for r in rows]
    highs, lows, closes = [b[1] for b in bars], [b[2] for b in bars], [b[3] for b in bars]
    atr = indicators.atr(highs, lows, closes, 20)
    high20 = prior_extreme(highs, 20, highest=True)
    low10 = prior_extreme(lows, 10, highest=False)
    entry_close: list[float] = []

    def enter(i: int) -> bool:
        ceiling = high20[i]
        if ceiling is None or closes[i] <= ceiling:
            return False
        entry_close[:] = [closes[i]]
        return True

    def leave(i: int) -> bool:
        stop, floor = atr[i], low10[i]
        below_channel = floor is not None and closes[i] < floor
        below_stop = (
            stop is not None and bool(entry_close) and closes[i] < entry_close[0] - 2 * stop
        )
        return below_channel or below_stop

    return _age(n, in_trade(n, enter, leave, start=max(20, n - STATE_WINDOW)))


STRATEGIES = (
    PaperStrategy(
        "nse_github_turtle_20_10",
        "Turtle 20/10 breakout, liquid NSE stocks (GitHub rule)",
        "github-2017-turtle-trading-stocks",
        "Harvey-Sun/TurtleTrading (GitHub, 2017)",
        "Buy a close above the prior 20-day high; sell below the prior 10-day low or 2 ATR under entry.",
        (
            "Among the point-in-time 250 most-traded stocks. One unit; the repository's "
            "pyramiding to four units and ATR position sizing are left out.",
            "Up to 20 names at a twentieth of capital each; filled at the next session's close.",
        ),
        STATE_WINDOW + 25,
        lambda: PositionRule(
            "nse_github_turtle_20_10", turtle_rule, lookback=STATE_WINDOW + 25, slots=20
        ),
    ),
)
