"""Three strategies built to be overfit, so the gate can be tested against them.

The build plan's acceptance criterion for Sprint 14 is: *deliberately feed it
3 overfit strategies; all must be killed.* A gate that has only ever seen a
real candidate is untested — the same argument as Sprint 12's mutation suite,
where every self-test passed first time and one of them turned out to have a
hole.

Each of these fails in a **different** way, because a gate that catches one
kind of overfitting and not another is worse than no gate: it certifies the
kinds it cannot see.

1. `NoiseFit` — a signal with no information at all, selected because it
   happened to work. Tests whether the statistical rules bite.
2. `RegimeFit` — genuinely predictive in one half of the history and useless
   in the other. Tests whether the regime stress bites. This is the one most
   likely to slip through, because its full-sample statistics look fine.
3. `LookaheadFit` — cheats outright, reading the future. Tests whether the
   gate rejects a result that is too good rather than accepting it.

The third is the important one to understand. An overfitting battery is built
to catch results that are *weaker* than they look. A strategy that cheats
produces results that are far *stronger* than anything real, and a gate tuned
only for weakness can wave it through. That is why `LookaheadFit` exists and
why it must be killed rather than promoted.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.features.panel import PanelRow


class NoiseFit(Strategy):
    """Ranks symbols by a deterministic hash of their name and the date.

    Carries no information whatsoever. Re-drawn each period so it is a true
    null — Sprint 12 established that a *constant* per-symbol label is not
    null, because in any fixed panel some symbols persistently out-drift
    others and a fixed ordering can align with them.
    """

    def __init__(self, top_n: int = 30, seed: int = 11) -> None:
        self.top_n = top_n
        self.seed = seed
        self.name = f"overfit_noise(top{top_n})"
        self.lookback = 2

    def target_weights(self, view: MarketView) -> dict[str, float]:
        symbols = view.symbols()
        if len(symbols) < self.top_n:
            return {}
        scored = sorted(
            symbols,
            key=lambda s: random.Random(f"{self.seed}|{s}|{view.as_of}").random(),
        )
        chosen = scored[: self.top_n]
        return dict.fromkeys(chosen, 1.0 / len(chosen))


class RegimeFit(Strategy):
    """Predictive in the first half of the sample and random in the second.

    The hardest case for a gate. Its full-sample Sharpe can look respectable
    because one good half carries the average, and only a regime split reveals
    that half the history contributes nothing. Sprint 10 and Sprint 11 reached
    opposite conclusions on the same data for exactly this reason.
    """

    def __init__(self, cutoff_year: int = 2021, top_n: int = 30) -> None:
        self.cutoff_year = cutoff_year
        self.top_n = top_n
        self.name = f"overfit_regime(pre{cutoff_year})"
        self.lookback = 130

    def target_weights(self, view: MarketView) -> dict[str, float]:
        symbols = view.symbols()
        if len(symbols) < self.top_n:
            return {}
        if view.as_of.year >= self.cutoff_year:
            # After the cutoff: no signal at all.
            chosen = sorted(symbols, key=lambda s: random.Random(f"r|{s}|{view.as_of}").random())[
                : self.top_n
            ]
        else:
            # Before it: hold whatever has actually been rising.
            scored: list[tuple[float, str]] = []
            for symbol in symbols:
                rows = view.history[symbol]
                if len(rows) >= 120 and rows[-120].close > 0:
                    scored.append((rows[-1].close / rows[-120].close, symbol))
            if len(scored) < self.top_n:
                return {}
            scored.sort(reverse=True)
            chosen = [s for _, s in scored[: self.top_n]]
        return dict.fromkeys(chosen, 1.0 / len(chosen))


class LookaheadFit(Strategy):
    """Cheats: ranks on a return window that extends past the decision date.

    It cannot actually see the future — `MarketView` makes that structurally
    impossible, which is Sprint 4's whole point. So it does the next best
    thing and uses the most recent close as though it were tomorrow's, which
    reproduces the *effect* of a one-bar lookahead: a signal correlated with
    the immediate next move.

    Included because an overfitting battery is built to catch results weaker
    than they look, and a cheat produces results far stronger. A gate tuned
    only for weakness waves this through, so it must be tested explicitly.
    """

    def __init__(self, top_n: int = 30) -> None:
        self.top_n = top_n
        self.name = f"overfit_lookahead(top{top_n})"
        self.lookback = 5

    def target_weights(self, view: MarketView) -> dict[str, float]:
        scored: list[tuple[float, str]] = []
        for symbol in view.symbols():
            rows = view.history[symbol]
            if len(rows) >= 2 and rows[-2].close > 0:
                scored.append((rows[-1].close / rows[-2].close, symbol))
        if len(scored) < self.top_n:
            return {}
        scored.sort(reverse=True)
        chosen = [s for _, s in scored[: self.top_n]]
        return dict.fromkeys(chosen, 1.0 / len(chosen))


CATALOGUE: tuple[Strategy, ...] = (NoiseFit(), RegimeFit(), LookaheadFit())


def shrink(rows: Sequence[PanelRow], *, symbols: int = 400) -> list[PanelRow]:
    """A smaller universe, so the acceptance test runs in minutes not hours.

    Keeps the most liquid names, which is also the least favourable choice for
    an overfit strategy — microcaps are where spurious results live, so
    removing them makes the test harder to pass rather than easier.
    """
    turnover: dict[str, float] = {}
    for row in rows:
        turnover[row.symbol] = turnover.get(row.symbol, 0.0) + row.turnover
    keep = set(sorted(turnover, key=lambda s: -turnover[s])[:symbols])
    return [r for r in rows if r.symbol in keep]
