"""Accelerating dual momentum, Indian ETFs (GitHub rule).

Source: AleksLi1/Accelerating_Dual_Momentum (GitHub, 2025).

One daily rule from a public GitHub repository. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from collections.abc import Sequence

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.features.panel import PanelRow
from eulerlab.strategies.daily.india_papers import MONTH, PaperStrategy

DUAL = ("NIFTYBEES", "JUNIORBEES", "GOLDBEES", "LIQUIDBEES")


def _ret(rows: Sequence[PanelRow], days: int) -> float | None:
    if len(rows) <= days or rows[-1 - days].close <= 0:
        return None
    return rows[-1].close / rows[-1 - days].close - 1.0


class DualMomentum(Strategy):
    """AleksLi1/Accelerating_Dual_Momentum on Indian ETFs.

    The repository's SPY and VBR (large and small caps) become NIFTYBEES and
    JUNIORBEES (the Nifty Next 50); its safe pair, long Treasuries and TIPS,
    becomes GOLDBEES and LIQUIDBEES. Monthly: the risk asset with the higher
    mean of 1, 3 and 6-month return, if that mean is positive; otherwise the
    safe asset with the higher 1-month return.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.rebalance_every = MONTH
        self.lookback = 6 * MONTH + 10

    def target_weights(self, view: MarketView) -> dict[str, float]:
        def score(symbol: str) -> float | None:
            rows = view.history.get(symbol) or []
            found = [_ret(rows, d) for d in (MONTH, 3 * MONTH, 6 * MONTH)]
            return None if None in found else sum(x for x in found if x is not None) / 3

        risky = [(s, score(s)) for s in DUAL[:2]]
        best = max(((v, s) for s, v in risky if v is not None), default=None)
        if best is not None and best[0] > 0:
            return {best[1]: 1.0}
        safe = [
            (r, s) for s in DUAL[2:] if (r := _ret(view.history.get(s) or [], MONTH)) is not None
        ]
        return {max(safe)[1]: 1.0} if safe else {}


STRATEGIES = (
    PaperStrategy(
        "nse_github_dual_momentum_etf",
        "Accelerating dual momentum, Indian ETFs (GitHub rule)",
        "github-2025-accelerating-dual-momentum",
        "AleksLi1/Accelerating_Dual_Momentum (GitHub, 2025)",
        "Each month, hold the Nifty 50 or Next 50 ETF with the better 1/3/6-month momentum if positive; otherwise gold or cash.",
        (
            "Score = mean of 1, 3 and 6-month return for NIFTYBEES and JUNIORBEES (the "
            "repository's SPY and VBR). Hold the higher if its score is positive.",
            "Otherwise hold GOLDBEES or LIQUIDBEES (for its Treasuries and TIPS), whichever "
            "returned more over the month. Monthly; all in one ETF.",
        ),
        6 * MONTH + 10,
        lambda: DualMomentum("nse_github_dual_momentum_etf"),
        "all",
        DUAL,
    ),
)
