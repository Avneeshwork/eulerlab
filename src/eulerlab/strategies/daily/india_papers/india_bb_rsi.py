"""Bollinger and RSI reversion (India).

Source: Shalinigayathri & Shunmuga Kumari (2024), IJCRT 12(4).

One daily strategy from a paper on Indian equities. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.strategies.daily.india_papers.common import PaperStrategy, liquid_universe


class LiquidBuilt(Strategy):
    """A Strategy Builder spec run over the point-in-time top 250 only, so a
    stock-level rule from a paper is not run on every listed name."""

    def __init__(self, inner: Strategy) -> None:
        self.inner = inner
        self.name = inner.name
        self.rebalance_every = getattr(inner, "rebalance_every", 1)
        self.hold_unchanged = getattr(inner, "hold_unchanged", False)
        self.sizing = getattr(inner, "sizing", "equal")
        self.lookback = inner.lookback

    def target_weights(self, view: MarketView) -> dict[str, float]:
        keep = set(liquid_universe(view))
        narrowed = MarketView(
            as_of=view.as_of, history={s: r for s, r in view.history.items() if s in keep}
        )
        return self.inner.target_weights(narrowed)


def _bb_rsi() -> Strategy:
    from eulerlab.builder.compile import BuiltStrategy
    from eulerlab.builder.spec import BuilderSpec

    def i(name: str, **params: float) -> dict[str, object]:
        return {"kind": "indicator", "name": name, "params": params}

    def v(value: float) -> dict[str, object]:
        return {"kind": "value", "value": value}

    spec = BuilderSpec.model_validate(
        {
            "id": "b_india_bb_rsi",
            "name": "Bollinger and RSI reversion",
            "universe": {"asset_class": "equity", "universe": "all"},
            "entry": {
                "match": "all",
                "rules": [
                    {"left": i("close"), "op": "below", "right": i("bb_lower", period=20, width=2)},
                    {"left": i("rsi", period=14), "op": "below", "right": v(30)},
                ],
            },
            "exit": {
                "match": "all",
                "rules": [
                    {"left": i("close"), "op": "above", "right": i("bb_upper", period=20, width=2)},
                    {"left": i("rsi", period=14), "op": "above", "right": v(70)},
                ],
            },
            "sizing": {"max_positions": 10},
        }
    )
    built = BuiltStrategy(spec)
    built.name = "india_bb_rsi"
    return LiquidBuilt(built)


STRATEGIES = (
    PaperStrategy(
        "india_bb_rsi",
        "Bollinger and RSI reversion (India)",
        "shalinigayathri-2024-bollinger-rsi-india",
        "Shalinigayathri & Shunmuga Kumari (2024), IJCRT 12(4)",
        "Buy a stock that closes below its lower Bollinger band with RSI under 30; sell above the upper band with RSI over 70.",
        (
            "Bollinger(20, 2) and RSI(14) on the point-in-time top 250; at most 10 positions.",
            "Entry: close below the lower band and RSI below 30. Exit: close above the upper "
            "band and RSI above 70. The paper tested ITC and Tata Coffee, 2019-2023.",
        ),
        40,
        _bb_rsi,
    ),
)
