"""Nifty above its 60-day average (India).

Source: Mitra (2011), International Journal of Business and Management 6(7).

One daily strategy from a paper on Indian equities. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from eulerlab.backtest.strategy import Strategy
from eulerlab.strategies.daily.india_papers.common import INDEX_ETF, INDEX_ONLY, PaperStrategy


def _nifty_sma60() -> Strategy:
    from eulerlab.builder.compile import BuiltStrategy
    from eulerlab.builder.spec import BuilderSpec

    close = {"kind": "indicator", "name": "close", "params": {}}
    sma = {"kind": "indicator", "name": "sma", "params": {"period": 60}}
    spec = BuilderSpec.model_validate(
        {
            "id": "b_india_nifty_sma60",
            "name": "Nifty above its 60-day average",
            "universe": {"asset_class": "equity", "universe": "all", "instruments": [INDEX_ETF]},
            "entry": {"rules": [{"left": close, "op": "above", "right": sma}]},
            "exit": {"rules": [{"left": close, "op": "below", "right": sma}]},
            "sizing": {"max_positions": 1},
        }
    )
    strategy = BuiltStrategy(spec)
    strategy.name = "india_nifty_sma60"
    return strategy


STRATEGIES = (
    PaperStrategy(
        "india_nifty_sma60",
        "Nifty above its 60-day average (India)",
        "mitra-2011-moving-average-rules-india",
        "Mitra (2011), International Journal of Business and Management 6(7)",
        "Hold NIFTYBEES while it closes above its 60-day simple moving average.",
        (
            "Long NIFTYBEES while the close is above SMA(60); in cash when it closes below.",
            "The paper is always in the market, short below the average; long only here. "
            "SMA(60) is the rule the paper finds survives costs best.",
        ),
        70,
        _nifty_sma60,
        "all",
        INDEX_ONLY,
    ),
)
