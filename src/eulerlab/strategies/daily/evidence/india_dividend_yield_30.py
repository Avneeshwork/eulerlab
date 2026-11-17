"""High dividend yield, top 30 (India).

Source: Tripathi & Aggarwal (2013), Dividend Opportunity Index: An Opportunity for Small
Investors (SSRN 2258327).

One daily momentum or reversal refinement with published evidence. Its rule and its
library entry (STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.strategies.daily.evidence.common import HOLD, _equal, dividend_yield
from eulerlab.strategies.daily.india_papers import MONTH, PaperStrategy, liquid_universe


class DividendYield(Strategy):
    """The `hold` highest trailing 12-month dividend yields among the 250
    most-traded, every six months. Yields above 15% are left out: they are
    one-off special dividends or a price that has collapsed, not a yield."""

    def __init__(self, name: str, *, hold: int = HOLD) -> None:
        self.name = name
        self.hold = hold
        self.rebalance_every = 6 * MONTH
        self.lookback = 10

    def target_weights(self, view: MarketView) -> dict[str, float]:
        scored = []
        for symbol in liquid_universe(view):
            found = dividend_yield(symbol, view.history[symbol])
            if 0 < found <= 0.15:
                scored.append((found, symbol))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return _equal([s for _, s in scored[: self.hold]])


STRATEGIES = (
    PaperStrategy(
        "india_dividend_yield_30",
        "High dividend yield, top 30 (India)",
        "tripathi-aggarwal-2013-dividend-opportunity-india",
        "Tripathi & Aggarwal (2013), Dividend Opportunity Index: An Opportunity for Small Investors (SSRN 2258327)",
        "Every six months, hold the 30 highest trailing-yield stocks among the 250 most-traded.",
        (
            "Yield: dividends with an ex-date in the past year (NSE corporate actions) over "
            "the close; yields above 15% left out as one-offs.",
            "The Indian study found high-yield stocks beat the market at lower risk in "
            "2007-2012; later comparisons with the Nifty are mixed.",
        ),
        10,
        lambda: DividendYield("india_dividend_yield_30"),
    ),
)
