"""MACD buy signal, Nifty (India).

Source: Muruganandan (2020), Colombo Business Journal 11(1).

One daily strategy from a paper on Indian equities. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from eulerlab.backtest.strategy import Strategy
from eulerlab.strategies.daily.india_papers.common import INDEX_ETF, INDEX_ONLY, PaperStrategy


def _macd_buy() -> Strategy:
    from eulerlab.builder.compile import BuiltStrategy
    from eulerlab.builder.spec import BuilderSpec

    def i(name: str, **params: float) -> dict[str, object]:
        return {"kind": "indicator", "name": name, "params": params}

    spec = BuilderSpec.model_validate(
        {
            "id": "b_india_macd_buy",
            "name": "MACD buy signal on the Nifty",
            "universe": {"asset_class": "equity", "universe": "all", "instruments": [INDEX_ETF]},
            "entry": {
                "match": "all",
                "rules": [
                    {"left": i("macd_line"), "op": "below", "right": {"kind": "value", "value": 0}},
                    {
                        "left": i("macd_signal"),
                        "op": "below",
                        "right": {"kind": "value", "value": 0},
                    },
                    {"left": i("macd_signal"), "op": "above", "right": i("macd_line")},
                ],
            },
            "sizing": {"max_positions": 1},
            "risk": {"max_hold_days": 1},
        }
    )
    strategy = BuiltStrategy(spec)
    strategy.name = "india_macd_buy"
    return strategy


STRATEGIES = (
    PaperStrategy(
        "india_macd_buy",
        "MACD buy signal, Nifty (India)",
        "muruganandan-2020-technical-rules-india",
        "Muruganandan (2020), Colombo Business Journal 11(1)",
        "Hold NIFTYBEES for one day after a MACD buy signal.",
        (
            "Buy when MACD(12,26) is below 0, its signal line is below 0, and the signal "
            "is above MACD. Sell the next day.",
            "The paper's signal line is a 9-day SMA; the builder's is an EMA. The paper "
            "trades open to close; the daily engine trades close to close. The paper's "
            "profitable side was the short (sell) signal, which cannot be run long only.",
        ),
        40,
        _macd_buy,
        "all",
        INDEX_ONLY,
    ),
)
