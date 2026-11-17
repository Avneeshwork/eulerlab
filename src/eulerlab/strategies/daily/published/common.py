"""Shared pieces of the published strategies: the multi-feature rank."""

from __future__ import annotations

from collections.abc import Sequence

from eulerlab.backtest.strategy import MarketView, Strategy, normalise
from eulerlab.features.library import BY_NAME, Feature


class Composite(Strategy):
    """Rank on several features at once, averaging the ranks.

    Ranks rather than raw values, because the features are in incompatible
    units — a log turnover and a negated drawdown cannot be averaged and mean
    anything. Averaging their *positions* can.

    Equal weights, deliberately. Fitting weights across features is exactly the
    search the trial ledger exists to count, and doing it silently inside a
    strategy would be the worst place to hide it.
    """

    def __init__(
        self,
        features: Sequence[Feature | str],
        *,
        top_n: int = 30,
        min_names: int = 20,
    ) -> None:
        self.features = [BY_NAME[f] if isinstance(f, str) else f for f in features]
        self.top_n = top_n
        self.min_names = min_names
        """How wide the cross-section must be before ranking means anything.

        Defaulted for an equity panel of hundreds. The whole crypto universe is
        20 coins, so the equity default of 50 makes every crypto strategy
        return no positions at all — which reads in a backtest as Sharpe 0.00
        rather than as "this never ran". Sized per universe at the call site.
        """
        names = "+".join(f.name for f in self.features)
        self.name = f"composite({names}, top{top_n})"
        self.lookback = max(f.min_history for f in self.features) + 10

    def target_weights(self, view: MarketView) -> dict[str, float]:
        symbols = view.symbols()
        rank_sum: dict[str, float] = {}
        counted: dict[str, int] = {}

        for feature in self.features:
            scored: list[tuple[float, str]] = []
            for symbol in symbols:
                value = feature(view.history[symbol])
                if value is not None:
                    scored.append((value, symbol))
            if len(scored) < self.min_names:
                # Too thin a cross-section for this feature to rank. Skipping it
                # is right; ranking 3 names would give them extreme positions on
                # no information.
                continue
            scored.sort()
            for position, (_, symbol) in enumerate(scored):
                rank_sum[symbol] = rank_sum.get(symbol, 0.0) + position / len(scored)
                counted[symbol] = counted.get(symbol, 0) + 1

        # A symbol scored by only some features is not comparable to one scored
        # by all of them, so it is dropped rather than averaged over fewer.
        wanted = len(self.features)
        eligible = [(rank_sum[s] / counted[s], s) for s in rank_sum if counted[s] == wanted]
        if len(eligible) < self.min_names:
            return {}

        eligible.sort(reverse=True)
        chosen = [symbol for _, symbol in eligible[: self.top_n]]
        return normalise(dict.fromkeys(chosen, 1.0 / len(chosen)))
