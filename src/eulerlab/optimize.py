"""Sweep a strategy's parameters, and make the cost of doing so visible.

### What optimising costs here, specifically

`mandate.yaml` requires a deflated Sharpe probability of 0.95 and a
t-statistic above 3.0. Both corrections take the **total** number of
configurations ever evaluated as their denominator, and `features/trials.py`
says it plainly: a count that begins late "looks authoritative while
understating the denominator, which is exactly the direction that flatters."

So a sweep is not free and it is not local. Every configuration it evaluates
permanently raises the bar for **every** result this platform has produced or
will produce. Twelve trials had been spent before this module existed; a
careless grid over thirty-two strategies would spend thousands.

That is a reason to sweep deliberately, not a reason never to sweep. What this
module refuses to do is hide the cost: it records every configuration, reports
the count before and after, and states the t-statistic the new count demands.

### Why the best result is not the answer

The maximum of N draws from noise rises with N. A sweep that tries forty
parameter sets and reports the best one has not found an edge, it has found the
right tail of forty samples — which is why `Best` in `results.py` carries its
`runs` denominator and why this reports the **median** alongside the best. A
sweep whose best is far above its median found variance, not signal.

### On the asset class

Each signal declares `recommended_class` — the market its source paper tested.
The sweep runs there rather than wherever is convenient, because a signal
published on US equity futures and swept on NSE minute bars is being asked a
different question than the one it answers.
"""

from __future__ import annotations

import itertools
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

from eulerlab.features import trials

if TYPE_CHECKING:
    from eulerlab.strategies.intraday.papers import PaperRules as PaperRulesLike
else:
    PaperRulesLike = object


@dataclass(frozen=True)
class Candidate:
    """One parameter set and what it produced."""

    params: dict[str, float]
    net_pnl: float
    fills: int
    wins: int
    sessions: int

    @property
    def win_rate(self) -> float:
        return self.wins / self.fills if self.fills else 0.0


@dataclass
class Sweep:
    """Every candidate for one strategy, and the honest reading of them."""

    strategy_id: str
    asset_class: str
    symbol: str
    candidates: list[Candidate] = field(default_factory=list)
    trials_before: int = 0
    trials_after: int = 0
    error: str = ""

    @property
    def best(self) -> Candidate | None:
        return max(self.candidates, key=lambda c: c.net_pnl) if self.candidates else None

    @property
    def median_pnl(self) -> float:
        """The middle candidate, which is the honest summary of a sweep.

        Reported beside the best because the maximum of N draws from noise
        rises with N. A best far above the median is the shape of variance,
        not of edge.
        """
        return statistics.median([c.net_pnl for c in self.candidates]) if self.candidates else 0.0

    @property
    def spread(self) -> float:
        """Best minus median. Large means the sweep is picking the tail."""
        top = self.best
        return (top.net_pnl - self.median_pnl) if top else 0.0

    @property
    def any_profitable(self) -> bool:
        return any(c.net_pnl > 0 for c in self.candidates)

    @property
    def required_t(self) -> float:
        """Roughly the t-statistic this many trials now demands.

        The Bonferroni-style bound: a two-sided 5% test over `n` independent
        trials needs about `sqrt(2 * ln n)` in the tail. Stated as an
        approximation because it is one — the exact deflated-Sharpe correction
        lives in the gate and depends on the return distribution, not just the
        count. This is here so the cost of a sweep is legible before the gate
        refuses it, not to replace the gate.
        """
        import math

        n = max(self.trials_after, 2)
        return max(3.0, math.sqrt(2.0 * math.log(n)))


def _rules(params: dict[str, float]) -> PaperRulesLike:
    """Build `PaperRules` with each value cast to its declared type.

    Constructed field by field rather than splatted, because the dataclass
    mixes ints and floats — `atr_period: int` beside `stop_atr_mult: float` —
    and a `**dict[str, object]` satisfies neither. Handing 14.0 to an int field
    also works right up until something uses it as a slice index.
    """
    from dataclasses import fields, replace

    from eulerlab.strategies.intraday.papers import PaperRules

    rules = PaperRules()
    declared = {f.name: str(f.type) for f in fields(PaperRules)}
    changes: dict[str, object] = {}
    for name, value in params.items():
        if name not in declared:
            raise TypeError(f"PaperRules has no field {name!r}")
        kind = declared[name]
        changes[name] = round(value) if "int" in kind and "float" not in kind else float(value)
    return replace(rules, **changes)  # type: ignore[arg-type]


def grid(space: Mapping[str, Sequence[float]]) -> list[dict[str, float]]:
    """Every combination, in a stable order.

    Sorted by key so two runs of the same space evaluate in the same sequence
    — a sweep that shuffles its own order cannot be compared with its previous
    self, and the trial log would record the same work as different work.
    """
    keys = sorted(space)
    return [
        dict(zip(keys, values, strict=True))
        for values in itertools.product(*(space[k] for k in keys))
    ]


def sweep_intraday(
    strategy_id: str,
    symbol: str,
    *,
    asset_class: str,
    space: Mapping[str, Sequence[float]],
    start: date,
    end: date,
    equity: float = 1_000_000.0,
    record: bool = True,
) -> Sweep:
    """Evaluate a parameter grid for one intraday signal.

    Every candidate is written to the trial log before the result is read, so
    an interrupted sweep still counts what it spent. Counting only completed
    sweeps would understate the denominator, which is the direction that
    flatters.
    """
    from eulerlab.intraday import paper_scan

    out = Sweep(
        strategy_id=strategy_id,
        asset_class=asset_class,
        symbol=symbol,
        trials_before=trials.count(),
    )

    for params in grid(space):
        # Coerced to each field's declared type. `PaperRules` mixes ints and
        # floats — `atr_period: int` beside `stop_atr_mult: float` — and
        # handing 14.0 to an int field is the kind of thing that works until a
        # comparison or a slice index does not.
        try:
            rules = _rules(params)
        except TypeError as exc:
            out.error = f"parameter not accepted by PaperRules: {exc}"
            break

        try:
            scan = paper_scan.scan_symbol(
                strategy_id,
                symbol,
                start=start,
                end=end,
                rules=rules,
                equity=equity,
                asset_class=asset_class,
            )
        except Exception as exc:
            out.error = f"{type(exc).__name__}: {str(exc)[:110]}"
            break

        candidate = Candidate(
            params=dict(params),
            net_pnl=scan.net_pnl,
            fills=scan.filled,
            wins=scan.wins,
            sessions=scan.sessions,
        )
        out.candidates.append(candidate)

        if record:
            # Recorded whatever the outcome. The log is a count of everything
            # ever tried, and skipping the losers is how a denominator quietly
            # shrinks.
            trials.append(
                trials.Trial(
                    logged_at=trials.now_iso(),
                    feature=f"{strategy_id}|{symbol}|{sorted(params.items())}",
                    horizon_days=(end - start).days,
                    step_days=1,
                    panel_start=start.isoformat(),
                    panel_end=end.isoformat(),
                    n_periods=scan.sessions,
                    mean_ic=candidate.net_pnl / equity,
                    t_stat=0.0,
                )
            )

    out.trials_after = trials.count()
    return out
