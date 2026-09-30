"""Parameters adopted from a sweep, and the evidence each one rests on.

When a sweep finds a setting that beats the published one, this is where that
setting becomes the strategy's actual default. `paper_scan` reads from here, so
a backtest, a paper run and a live signal all use the adopted value rather than
the paper's — which is the point: an optimisation nobody acts on is a report,
not a change.

### Adopting the winner of a grid is the thing this repo warns about

`optimize.py` exists to say that the maximum of N draws from noise rises with N,
so promoting the best of nine settings is precisely the selection it was written
to expose. Three rules keep that from being a quiet disaster.

**The trials must have been spent.** A parameter chosen by a search the ledger
has no record of gives you the selection bias without the correction that
accounts for it. Every `Adoption` below names the sweep that produced it, and
that sweep was recorded, not a dry run.

**Nothing is adopted from a losing grid.** Where every setting lost money, the
best is the least-bad loss and adopting it is fitting noise with extra steps.
Those strategies keep their published parameters and carry a `NOT_ADOPTED`
entry saying so, because "we looked and found nothing" is a result worth
storing.

**The evidence travels with the value.** Each entry carries the best, the
median, the fill count and how much of the win sits above the median. A reader
who sees only `stop_atr_mult = 2.0` cannot tell whether it beat the paper by a
mile on 600 trades or by a whisker on 17.

### What an adoption is not

It is not a validated result. None of these clears the platform's own bar —
t > 3.0 and a deflated-Sharpe probability of 0.95 — and several rest on fewer
than twenty fills over 58 sessions. Adopting a parameter says "this is the
better guess of the ones we tried", not "this works".
"""

from __future__ import annotations

from dataclasses import dataclass, field

NOT_ADOPTED = "not adopted"


@dataclass(frozen=True)
class Adoption:
    """One strategy's tuned parameters, and why they were adopted or were not."""

    strategy_id: str
    params: dict[str, float] = field(default_factory=dict)
    paper_params: dict[str, float] = field(default_factory=dict)
    symbol: str = ""
    market: str = ""
    best_pnl: float = 0.0
    median_pnl: float = 0.0
    fills: int = 0
    sessions: int = 0
    candidates: int = 0
    swept_at: str = ""
    reason: str = ""

    @property
    def adopted(self) -> bool:
        return bool(self.params)

    @property
    def tail_share(self) -> float:
        """How much of the best sits above the median, as a share of the best.

        The number that says whether the winner is a peak or a plateau. Zero
        when the best is not positive, because a share of a loss is not a
        quantity anyone can act on.
        """
        if self.best_pnl <= 0:
            return 0.0
        return max(0.0, self.best_pnl - self.median_pnl) / self.best_pnl

    @property
    def changed(self) -> dict[str, tuple[float, float]]:
        """Only the fields the sweep actually moved, as (paper, adopted).

        A grid sweeps two parameters and often lands on the paper's value for
        one of them. Reporting that as a change would overstate what the sweep
        found, and it is the kind of overstatement nobody checks.
        """
        return {
            name: (self.paper_params[name], value)
            for name, value in self.params.items()
            if name in self.paper_params and self.paper_params[name] != value
        }


ADOPTIONS: dict[str, Adoption] = {}
"""Filled by `load()` from the recorded sweep. Empty until one has run."""


def load() -> dict[str, Adoption]:
    """Read adoptions from the last recorded sweep.

    Derived rather than hand-written, so a parameter cannot be adopted here
    that no sweep ever produced — the failure mode where a number is typed in,
    the sweep is re-run, and the two silently disagree.

    A **dry run is ignored**. Its numbers are identical to a recorded one and
    it spends no trials, so adopting from it would take the selection without
    the denominator that corrects for it.
    """
    from eulerlab import optimize_store
    from eulerlab.intraday.papers import PaperRules

    # The path is read from the module at call time rather than taken from the
    # function's default, which binds once at import and cannot be redirected.
    # Every recorded sweep, oldest first, so a later one overwrites an earlier
    # adoption for the same strategy and leaves the others alone.
    #
    # Reading only the newest sweep was wrong the moment a sweep covered a
    # subset. `make optimize ONLY=...` on the four NSE adaptations produced a
    # four-row document, and the twenty US and crypto adoptions vanished — a
    # partial sweep silently un-adopting every strategy it did not mention.
    sweeps = [
        s for s in optimize_store.read_all(optimize_store.SWEEPS_PATH) if not s.get("dry_run", True)
    ]
    if not sweeps:
        return {}

    # A partial sweep still adopts, for the strategies it finished. Each row is
    # a complete nine-setting grid for one strategy regardless of whether the
    # next strategy has started, and making a finished result wait on unrelated
    # work would be arbitrary.

    defaults = PaperRules()
    out: dict[str, Adoption] = {}
    rows_with_time = [
        (str(sweep.get("at", "")), row) for sweep in sweeps for row in sweep.get("rows", [])
    ]
    for swept_at, row in rows_with_time:
        strategy_id = str(row.get("strategy_id", ""))
        params = dict(row.get("best_params") or {})
        paper = {name: float(getattr(defaults, name)) for name in params if hasattr(defaults, name)}
        best = float(row.get("best_pnl") or 0.0)
        median = float(row.get("median_pnl") or 0.0)

        adopt = best > 0
        moved = any(paper.get(name) != value for name, value in params.items() if name in paper)
        if not adopt:
            reason = (
                "every setting in the grid lost money, so there is nothing to adopt — "
                "the published parameters stand"
            )
        elif not moved:
            # The most reassuring outcome the sweep can produce, and the one
            # most easily mistaken for "nothing happened". The search ran, the
            # paper's own values won it, and that is evidence *for* the paper
            # rather than an absence of evidence.
            reason = (
                "the sweep ran and the paper's own values won it — the published "
                "parameters are confirmed rather than merely untested"
            )
        else:
            reason = "the best setting made money and beat the published parameters"
        out[strategy_id] = Adoption(
            strategy_id=strategy_id,
            params=params if adopt else {},
            paper_params=paper,
            symbol=str(row.get("symbol", "")),
            market=str(row.get("market", "")),
            best_pnl=best,
            median_pnl=median,
            fills=int(row.get("fills") or 0),
            sessions=int(row.get("sessions") or 0),
            candidates=int(row.get("candidates") or 0),
            swept_at=swept_at,
            reason=reason,
        )
    return out


def refresh() -> dict[str, Adoption]:
    """Re-read adoptions and replace the cache. Called after a sweep."""
    ADOPTIONS.clear()
    ADOPTIONS.update(load())
    return ADOPTIONS


def for_strategy(strategy_id: str) -> Adoption | None:
    """The adoption record for one strategy, if a recorded sweep covered it."""
    if not ADOPTIONS:
        refresh()
    return ADOPTIONS.get(strategy_id)


def rules_for(strategy_id: str) -> object:
    """`PaperRules` with any adopted parameters applied.

    The published defaults when nothing was adopted — which is the common case
    and the correct one. A strategy whose grid all lost keeps the parameters
    its paper published.
    """
    from dataclasses import replace

    from eulerlab.intraday.papers import PaperRules

    rules = PaperRules()
    adoption = for_strategy(strategy_id)
    if adoption is None or not adoption.adopted:
        return rules

    changes: dict[str, object] = {}
    declared = {f: str(t) for f, t in PaperRules.__annotations__.items()}
    for name, value in adoption.params.items():
        if name not in declared:
            continue
        kind = declared[name]
        changes[name] = round(value) if "int" in kind and "float" not in kind else float(value)
    return replace(rules, **changes)  # type: ignore[arg-type]
