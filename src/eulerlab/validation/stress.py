"""Stress tests: not "is this significant" but "when does this break".

The rest of the battery asks whether a result could be luck. These ask
something different and more practical: **what has to be true for this to keep
working, and how close is it to not being true?** A strategy can be
statistically respectable and still be one assumption away from useless.

Four questions, each chosen because a plausible-looking strategy can fail it:

**How much cost can it absorb?** Sprint 9's rates are researched but every one
comes from a secondary source (A-016), and impact is not modelled at all. If
the edge dies at 1.5x the modelled cost, the modelling error is larger than
the edge and nothing else matters.

**Does it survive being slow?** Fills here happen at the next close. Real
execution slips. If a one-day delay destroys the result, the strategy is
trading a signal that decays faster than anyone can act on it, which is a
different business from the one the backtest describes.

**Is it a handful of lucky positions?** An equal-weight book of thirty names
over eleven years takes thousands of positions. If dropping the best few turns
the result negative, there is no strategy — there is a small number of stocks
that happened to work, and no reason to expect the next few to.

**Does it work in more than one regime?** A single eleven-year Sharpe averages
over a crash and two bull markets. Sprint 10 and Sprint 11 reached opposite
conclusions from different windows of the same data, which is exactly this
failure discovered the expensive way.

Every test is a *comparison against the base case*, not a threshold. Thresholds
belong in the promotion gate, which is the operator's file.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from eulerlab.backtest import event_driven
from eulerlab.backtest.strategy import Strategy
from eulerlab.backtest.vector import build_adjusted_index
from eulerlab.features.panel import PanelRow
from eulerlab.validation.statistics import sharpe_stats


@dataclass(frozen=True)
class StressResult:
    name: str
    detail: str
    base: float
    stressed: float

    @property
    def survives(self) -> bool:
        """Still positive after the stress. Deliberately a low bar — this
        reports how much room there is, and the gate decides what is enough."""
        return self.stressed > 0

    @property
    def retained(self) -> float:
        if self.base <= 0:
            return 0.0
        return self.stressed / self.base


def _sharpe(result: event_driven.TierBResult) -> float:
    return sharpe_stats(result.daily_returns()).sharpe


def cost_multiple(
    rows: Sequence[PanelRow],
    strategy: Strategy,
    *,
    multiples: Sequence[float] = (1.0, 2.0, 3.0, 5.0),
    rebalance: int = 21,
    index: dict[str, dict[date, float]] | None = None,
) -> list[StressResult]:
    """Re-run with **every** cost scaled by a multiple.

    The first version scaled only brokerage, which was close to meaningless:
    the default delivery brokerage is zero, so "costs x2" quietly meant
    "introduce a 0.06% fee that did not exist", while STT and stamp duty —
    the charges that actually dominate — were untouched. It reported 95% of
    the Sharpe surviving 5x costs, which was not a fact about the strategy.

    Now the multiplier applies to the total of every charge, so the number
    means what its name says. This is the test that matters most, because
    impact is not modelled at all (T-907) and every statutory rate comes from
    a secondary source (A-016) — if the edge dies at 2x, the gap between the
    cost model and reality is larger than the edge.
    """
    index = index or build_adjusted_index(rows)
    base = _sharpe(
        event_driven.run(
            rows, strategy, asset_class="equity", rebalance_every=rebalance, adjusted_index=index
        )
    )
    out: list[StressResult] = []
    for multiple in multiples:
        if multiple == 1.0:
            continue
        stressed = _sharpe(
            event_driven.run(
                rows,
                strategy,
                asset_class="equity",
                rebalance_every=rebalance,
                cost_multiplier=multiple,
                adjusted_index=index,
            )
        )
        out.append(
            StressResult(
                name=f"costs x{multiple:g}",
                detail=f"Sharpe {base:.2f} -> {stressed:.2f}",
                base=base,
                stressed=stressed,
            )
        )
    return out


def execution_delay(
    rows: Sequence[PanelRow],
    strategy: Strategy,
    *,
    rebalance: int = 21,
    index: dict[str, dict[date, float]] | None = None,
) -> StressResult:
    """Trade less often, as a proxy for acting later on a stale signal.

    A true one-day delay needs the engine to separate signal time from fill
    time by an arbitrary lag, which it does not yet support — fills are fixed
    at the next close. Halving the rebalance frequency is a weaker but honest
    stand-in: it makes every position act on an older signal on average.
    Named as a proxy rather than dressed up as the real thing.
    """
    index = index or build_adjusted_index(rows)
    base = _sharpe(
        event_driven.run(
            rows, strategy, asset_class="equity", rebalance_every=rebalance, adjusted_index=index
        )
    )
    slower = _sharpe(
        event_driven.run(
            rows,
            strategy,
            asset_class="equity",
            rebalance_every=rebalance * 2,
            adjusted_index=index,
        )
    )
    return StressResult(
        name="signal staleness (proxy)",
        detail=f"rebalance {rebalance}d -> {rebalance * 2}d: Sharpe {base:.2f} -> {slower:.2f}",
        base=base,
        stressed=slower,
    )


def drop_best_contributors(
    rows: Sequence[PanelRow],
    strategy: Strategy,
    *,
    drop: int = 5,
    rebalance: int = 21,
    index: dict[str, dict[date, float]] | None = None,
) -> StressResult:
    """Remove the best-contributing symbols entirely and re-run.

    The sharpest of these tests. Concentration in a few names is invisible in
    a Sharpe ratio and fatal to the conclusion: if the result depends on five
    stocks out of thousands, nothing about it generalises, and the next five
    are not going to be those five.
    """
    index = index or build_adjusted_index(rows)
    base_run = event_driven.run(
        rows, strategy, asset_class="equity", rebalance_every=rebalance, adjusted_index=index
    )
    base = _sharpe(base_run)

    contribution: dict[str, float] = {}
    for fill in base_run.fills:
        signed = -fill.signed_quantity * fill.price
        contribution[fill.symbol] = contribution.get(fill.symbol, 0.0) + signed
    best = sorted(contribution, key=lambda s: -contribution[s])[:drop]

    trimmed = [r for r in rows if r.symbol not in set(best)]
    stressed = _sharpe(
        event_driven.run(trimmed, strategy, rebalance_every=rebalance, asset_class="equity")
    )
    return StressResult(
        name=f"drop best {drop} names",
        detail=f"removed {', '.join(best[:3])}...: Sharpe {base:.2f} -> {stressed:.2f}",
        base=base,
        stressed=stressed,
    )


def by_regime(
    rows: Sequence[PanelRow],
    strategy: Strategy,
    *,
    rebalance: int = 21,
    index: dict[str, dict[date, float]] | None = None,
) -> list[StressResult]:
    """Split the history in half and compare.

    Crude on purpose. A named crisis window would be a choice made after
    seeing the data; halving the sample is a split nobody picked. Sprint 10
    and Sprint 11 reached opposite conclusions from different windows of this
    same data, so the question is not academic.
    """
    index = index or build_adjusted_index(rows)
    days = sorted({r.day for r in rows})
    midpoint = days[len(days) // 2]
    first = [r for r in rows if r.day <= midpoint]
    second = [r for r in rows if r.day > midpoint]

    out: list[StressResult] = []
    base = _sharpe(
        event_driven.run(
            rows, strategy, asset_class="equity", rebalance_every=rebalance, adjusted_index=index
        )
    )
    for label, subset in (("first half", first), ("second half", second)):
        if len({r.day for r in subset}) < 400:
            continue
        stressed = _sharpe(
            event_driven.run(subset, strategy, rebalance_every=rebalance, asset_class="equity")
        )
        out.append(
            StressResult(
                name=f"regime: {label}",
                detail=f"{subset[0].day} to {subset[-1].day}: Sharpe {stressed:.2f}",
                base=base,
                stressed=stressed,
            )
        )
    return out


def run_all(
    rows: Sequence[PanelRow], strategy: Strategy, *, rebalance: int = 21
) -> list[StressResult]:
    """Every stress test, sharing one adjusted-price index."""
    index = build_adjusted_index(rows)
    results: list[StressResult] = []
    results.extend(cost_multiple(rows, strategy, rebalance=rebalance, index=index))
    results.append(execution_delay(rows, strategy, rebalance=rebalance, index=index))
    results.append(drop_best_contributors(rows, strategy, rebalance=rebalance, index=index))
    results.extend(by_regime(rows, strategy, rebalance=rebalance, index=index))
    return results


def render(results: Sequence[StressResult]) -> str:
    lines = ["", "-- stress tests: when does this break? --"]
    width = max((len(r.name) for r in results), default=10)
    for r in results:
        mark = "ok  " if r.survives else "FAIL"
        kept = f"{r.retained:5.0%} kept" if r.base > 0 else "     n/a"
        lines.append(f"  {mark} {r.name.ljust(width)}  {kept}   {r.detail}")
    broken = [r for r in results if not r.survives]
    if broken:
        lines.append(f"\n  {len(broken)} stress test(s) turn the result negative.")
    return "\n".join(lines)
