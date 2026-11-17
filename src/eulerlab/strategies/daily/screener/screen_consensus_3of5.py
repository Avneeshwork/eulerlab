"""Consensus: stocks 3 of the top 5 long-term models pick.

Source: Consensus of five stored strategies (research 152).

One stock-screener model. Its rule and its library entry (SPECS, at the bottom) are both
in this file.
"""

from __future__ import annotations

from collections.abc import Sequence

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.strategies.daily.india_papers import MONTH, PaperStrategy
from eulerlab.strategies.daily.screener.common import LONG, LONG_LOOKBACK


class Consensus(Strategy):
    """Hold, equal-weighted, the stocks at least `min_votes` of the parts pick (research 152)."""

    def __init__(
        self, name: str, parts: Sequence[str], min_votes: int, rebalance_every: int
    ) -> None:
        from eulerlab.strategies.daily.published import BUILDERS

        self.name = name
        self.parts = [(pid, BUILDERS[pid]()) for pid in parts]
        self.min_votes = min_votes
        self.rebalance_every = rebalance_every
        self.lookback = max(int(getattr(s, "lookback", 0) or 0) for _, s in self.parts)

    def picks(self, view: MarketView) -> dict[str, list[str]]:
        """Each part's picks on this view, by part id."""
        from eulerlab.backtest.strategy import decide

        out: dict[str, list[str]] = {}
        for pid, strategy in self.parts:
            lookback = int(getattr(strategy, "lookback", 0) or 0)
            narrowed = MarketView(
                as_of=view.as_of,
                history={s: h[-lookback:] if lookback else h for s, h in view.history.items()},
            )
            longs, _ = decide(strategy, narrowed)
            out[pid] = sorted(s for s, w in longs.items() if w > 0)
        return out

    def votes(self, view: MarketView) -> dict[str, int]:
        counts: dict[str, int] = {}
        for chosen in self.picks(view).values():
            for s in chosen:
                counts[s] = counts.get(s, 0) + 1
        return counts

    def target_weights(self, view: MarketView) -> dict[str, float]:
        held = sorted(s for s, n in self.votes(view).items() if n >= self.min_votes)
        return dict.fromkeys(held, 1.0 / len(held)) if held else {}


CONSENSUS_PARTS = (
    "nse_github_stocks_on_the_move",
    "india_sharpe_momentum",
    "nse_github_weinstein_stage2",
    "screen_quality_momentum",
    "india_physical_momentum",
)


SPECS = (
    (
        PaperStrategy(
            id="screen_consensus_3of5",
            title="Consensus: stocks 3 of the top 5 long-term models pick",
            paper="jacob-pradeep-varma-2022-quality-india",
            citation="Consensus of five stored strategies (research 152)",
            summary="Every 21 sessions, hold equally the stocks that at least 3 of the top 5 long-term models pick.",
            logic=(
                *(f"Part: {pid}" for pid in CONSENSUS_PARTS),
                "A stock is held when 3 or more parts pick it; equal weights; none means cash.",
                "Rebalanced every 21 sessions.",
            ),
            lookback=LONG_LOOKBACK,
            build=lambda: Consensus("screen_consensus_3of5", CONSENSUS_PARTS, 3, MONTH),
        ),
        LONG,
    ),
)
