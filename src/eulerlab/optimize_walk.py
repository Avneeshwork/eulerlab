"""Walk-forward evaluation of a parameter sweep, and the PBO it implies.

Every result this platform holds for an intraday signal is **in-sample**: the
parameter was chosen by searching a window, and then reported on that same
window. The noise bar corrects for how much searching happened, which is a real
correction and not the same thing as an out-of-sample test. A parameter can
clear a bar raised for 300 trials and still be fitted to the particular 59 days
it was chosen on.

This splits the sessions and asks the only question that distinguishes the two:
**does the setting that won in-sample still win out of sample?**

### The splitting is free; the evaluating is not

Re-partitioning sessions costs nothing: nine candidates scored over 59 sessions
is nine configurations however many ways the 59 days are later cut. That is the
part this module does, and `walk` itself evaluates nothing.

**The caller still has to produce the candidates**, and where it does that by
running scans — which `walk_run` does — those runs are configurations evaluated
and are recorded as trials. An earlier version of this docstring claimed the
whole exercise was free, which was true of the mathematics and false of the
code sitting next to it: `walk_run` re-scans every grid point, and the extended
grid contained seven settings no sweep had ever recorded.

Configurations already in the ledger are recorded again rather than matched and
skipped. That over-counts, and the alternative under-counts far worse — see
A-034. The ledger errs toward the bar being too high, which is the only
direction that does not flatter.

### The independence this leans on, and where it is imperfect

Splitting by session assumes a session's result does not depend on which other
sessions were in the training set. For a strategy that is flat at every close
that is nearly true — but not exactly. Lookbacks cross the boundary: with
`ou_lookback=120` on 375-bar sessions, the first 120 bars of each session read
into the previous one. So a test session is very slightly informed by the
session before it, whichever block that landed in.

The effect is bounded by the lookback and is small at these lengths. It is
stated rather than corrected because correcting it properly means purging the
first bars of every test session, which changes the thing being measured.
`validation/cpcv.py` does exactly that purging for daily panels, and this is
the intraday analogue with the purge left explicit and undone.

### What PBO says, and what it does not

`probability_of_backtest_overfitting` asks, across many splits: does the
in-sample winner land below the out-of-sample median? Above 0.5 the selection
is picking noise. The mandate's ceiling is 0.25.

It indicts **the act of choosing**, not any single configuration. A low PBO
does not certify the winner; it says that choosing a winner this way, on this
data, is not by itself a mistake.
"""

from __future__ import annotations

import itertools
import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

TRADING_DAYS = 252.0


@dataclass(frozen=True)
class Candidate:
    """One parameter set and what it earned on each session."""

    params: dict[str, float]
    by_session: dict[date, float]

    def total(self, days: Sequence[date]) -> float:
        return sum(self.by_session.get(day, 0.0) for day in days)

    def sharpe(self, days: Sequence[date], equity: float) -> float | None:
        """Annualised Sharpe over a subset of sessions, or None if undefined."""
        series = [self.by_session.get(day, 0.0) / equity for day in days]
        if len(series) < 2:
            return None
        spread = statistics.pstdev(series)
        if spread <= 0:
            return None
        return float((statistics.fmean(series) / spread) * math.sqrt(TRADING_DAYS))


@dataclass
class WalkResult:
    """What the split found."""

    strategy_id: str
    symbol: str
    n_blocks: int
    test_blocks: int
    splits: int = 0
    pbo: float = 0.0
    pbo_verdict: str = ""
    # The setting that won most often in sample, and how it did out of sample.
    modal_winner: dict[str, float] = field(default_factory=dict)
    winner_oos_sharpe: float | None = None
    winner_oos_pnl: float = 0.0
    median_oos_pnl: float = 0.0
    oos_positive_splits: int = 0
    settings_profitable_oos: int = 0
    settings_total: int = 0

    @property
    def winner_beat_median(self) -> bool:
        return self.winner_oos_pnl > self.median_oos_pnl

    @property
    def most_settings_work(self) -> bool:
        """Whether the grid is broadly profitable rather than narrowly so."""
        if not self.settings_total:
            return False
        return self.settings_profitable_oos / self.settings_total >= 0.75

    @property
    def verdict(self) -> str:
        """A sentence a reader can act on, not a number they must interpret.

        A high PBO has two very different causes and they call for opposite
        responses, which reading the number alone cannot tell apart.

        When **most settings are profitable**, they perform near-identically, so
        which one wins in sample is close to a coin toss and PBO climbs toward
        0.5 by construction. That is not a warning about the strategy — it says
        the parameter does not matter, and any setting will do.

        When **few settings are profitable**, a high PBO means the search is
        finding the ones that happened to work on the training days. That is the
        failure the statistic exists to catch.

        `orb_breakout` is the first case: PBO 0.47 with every setting in its grid
        profitable and 13 of 15 splits making money. `ou_reversion` on the same
        window is PBO 0.53 with fewer settings surviving, which is the second.
        Both read as "substantial overfitting risk" if the number is taken
        alone, and only one of them is.
        """
        if self.splits < 4:
            return "too few splits to say anything"
        if self.pbo > 0.25 and self.most_settings_work:
            return (
                f"the parameter barely matters — {self.settings_profitable_oos} of "
                f"{self.settings_total} settings make money out of sample, so the "
                "in-sample ranking among them is noise. Pick any of them."
            )
        if self.pbo > 0.5:
            return "the selection is picking noise: the winner is usually below the median"
        if self.pbo > 0.25:
            return "substantial overfitting risk — above the mandate's 0.25 ceiling"
        if self.winner_oos_pnl <= 0:
            return "overfitting risk is low, and the winner still loses out of sample"
        return "overfitting risk is low and the winner holds up out of sample"


def _signature(candidate: Candidate) -> tuple[float, ...]:
    """A candidate's parameters as a hashable key, in a stable order."""
    return tuple(value for _, value in sorted(candidate.params.items()))


def blocks_of(days: Sequence[date], n_blocks: int) -> list[list[date]]:
    """Contiguous, near-equal blocks of sessions, in time order.

    Contiguous rather than interleaved: a block of consecutive days is a
    stretch of one market regime, which is what a walk-forward test is supposed
    to hold out. Interleaving days would leave every regime represented in both
    halves and make the test far easier than reality.
    """
    ordered = sorted(days)
    if n_blocks < 2 or len(ordered) < n_blocks:
        return [ordered]
    size, extra = divmod(len(ordered), n_blocks)
    out: list[list[date]] = []
    start = 0
    for index in range(n_blocks):
        take = size + (1 if index < extra else 0)
        out.append(ordered[start : start + take])
        start += take
    return out


def walk(
    strategy_id: str,
    symbol: str,
    candidates: Sequence[Candidate],
    *,
    equity: float,
    n_blocks: int = 6,
    test_blocks: int = 2,
) -> WalkResult:
    """Score every candidate on every train/test combination and estimate PBO.

    `test_blocks` of `n_blocks` are held out at a time, in every combination —
    15 splits at the defaults. Combinatorial rather than a single forward walk
    because one path gives one answer, and PBO needs a distribution of them to
    be estimable at all.
    """
    from eulerlab.validation.statistics import probability_of_backtest_overfitting

    days = sorted({day for candidate in candidates for day in candidate.by_session})
    out = WalkResult(
        strategy_id=strategy_id, symbol=symbol, n_blocks=n_blocks, test_blocks=test_blocks
    )
    if len(candidates) < 2 or len(days) < n_blocks * 2:
        return out

    parts = blocks_of(days, n_blocks)
    in_sample: list[list[float]] = []
    out_sample: list[list[float]] = []
    winners: list[tuple[tuple[float, ...], dict[str, float]]] = []
    winner_oos: list[float] = []
    median_oos: list[float] = []

    for held in itertools.combinations(range(len(parts)), test_blocks):
        test_days = [day for index in held for day in parts[index]]
        train_days = [day for index, part in enumerate(parts) if index not in held for day in part]
        if len(train_days) < 2 or len(test_days) < 2:
            continue

        train_scores = [c.total(train_days) for c in candidates]
        test_scores = [c.total(test_days) for c in candidates]
        in_sample.append(train_scores)
        out_sample.append(test_scores)

        best = max(range(len(candidates)), key=lambda i: train_scores[i])
        winners.append((_signature(candidates[best]), dict(candidates[best].params)))
        winner_oos.append(test_scores[best])
        median_oos.append(statistics.median(test_scores))

    if not in_sample:
        return out

    pbo = probability_of_backtest_overfitting(in_sample, out_sample)
    out.splits = pbo.n_paths or len(in_sample)
    out.pbo = pbo.pbo
    out.pbo_verdict = pbo.verdict

    # The setting that won most often, not the one that won the last split.
    tally: dict[tuple[float, ...], int] = {}
    params_for: dict[tuple[float, ...], dict[str, float]] = {}
    for signature, params in winners:
        tally[signature] = tally.get(signature, 0) + 1
        params_for[signature] = params
    modal = max(tally, key=lambda k: tally[k])
    out.modal_winner = params_for[modal]

    # How many settings make money out of sample, averaged across splits. The
    # statistic that tells a benign high PBO from a damning one.
    out.settings_total = len(candidates)
    out.settings_profitable_oos = sum(
        1
        for index in range(len(candidates))
        if statistics.fmean([scores[index] for scores in out_sample]) > 0
    )

    out.winner_oos_pnl = statistics.fmean(winner_oos)
    out.median_oos_pnl = statistics.fmean(median_oos)
    out.oos_positive_splits = sum(1 for value in winner_oos if value > 0)

    # Out-of-sample Sharpe of the modal winner, pooled across held-out blocks.
    chosen = next((c for c in candidates if _signature(c) == modal), None)
    if chosen is not None:
        out.winner_oos_sharpe = chosen.sharpe(days, equity)
    return out
