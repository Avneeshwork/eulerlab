"""Reference strategies, deliberately simple.

These exist to exercise the *engine*, not to make money. Sprint 8 measured
that the ten seed features collapse into about three findings, all long-only
cross-sectional ranks, so a rank-and-hold is the honest shape to start with —
and `BuyAndHold` is here because a backtester that cannot reproduce buy-and-
hold is broken in a way no strategy result would reveal.
"""

from __future__ import annotations

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.features.library import BY_NAME, Feature


class RankAndHold(Strategy):
    """Hold the top `n` names by a feature, equally weighted.

    Long-only and equal-weighted on purpose. Anything cleverer — weighting by
    signal strength, shorting the bottom — adds a second decision that would
    make a poor result ambiguous between the feature and the weighting.
    """

    def __init__(
        self,
        feature: Feature | str,
        *,
        top_n: int = 30,
        min_names: int = 50,
        min_turnover: float = 0.0,
    ) -> None:
        self.feature = BY_NAME[feature] if isinstance(feature, str) else feature
        self.top_n = top_n
        self.min_names = min_names
        self.min_turnover = min_turnover
        """Minimum daily turnover to be eligible, in rupees.

        Defaults to zero so the naive behaviour is the default and has to be
        *seen* rather than quietly prevented. It is worth seeing: measured on
        the real panel, an unfiltered top-30 momentum portfolio bought names
        like SPYL on a daily turnover of **Rs 49,839** - a position of
        Rs 33,000 is most of a day's volume, so the fill price in this engine
        is fiction. That is where its -42% drawdown came from.
        """
        suffix = f", >Rs{min_turnover:,.0f}" if min_turnover else ""
        self.name = f"rank_and_hold({self.feature.name}, top{top_n}{suffix})"

    def target_weights(self, view: MarketView) -> dict[str, float]:
        scored: list[tuple[float, str]] = []
        for symbol in view.symbols():
            if self.min_turnover:
                row = view.latest(symbol)
                if row is None or row.turnover < self.min_turnover:
                    continue
            value = self.feature(view.history[symbol])
            if value is not None:
                scored.append((value, symbol))

        if len(scored) < self.min_names:
            # Too thin a cross-section to rank meaningfully. Holding nothing is
            # the honest answer; holding whatever few names qualified would
            # make the early portfolio an accident of data coverage.
            return {}

        scored.sort(reverse=True)
        chosen = [symbol for _, symbol in scored[: self.top_n]]
        weight = 1.0 / len(chosen)
        return dict.fromkeys(chosen, weight)


class BuyAndHold(Strategy):
    """Equal-weight the `n` most liquid names and never trade again.

    The engine's control. Its return should track the market and its cost
    should be one round of entry charges — if either is wrong, the engine is
    wrong, and that is far easier to see here than inside a real strategy.
    """

    def __init__(self, top_n: int = 30) -> None:
        self.top_n = top_n
        self.name = f"buy_and_hold(top{top_n})"

    def target_weights(self, view: MarketView) -> dict[str, float]:
        liquid: list[tuple[float, str]] = []
        for symbol in view.symbols():
            row = view.latest(symbol)
            if row and row.turnover > 0:
                liquid.append((row.turnover, symbol))
        if not liquid:
            return {}
        liquid.sort(reverse=True)
        chosen = [symbol for _, symbol in liquid[: self.top_n]]
        weight = 1.0 / len(chosen)
        return dict.fromkeys(chosen, weight)
