"""The validation battery for an intraday rule, scored from its own trades (ADR-139).

`make validate` was built for daily `rank_and_hold` strategies: it re-runs the
strategy on each CPCV path and under each stress. An intraday rule is a list
of same-day trades instead, so here the same battery is computed from those
trades:

- **CPCV.** The same purged, embargoed splits of the session list; each path's
  in- and out-of-sample Sharpe is the Sharpe of the rule's daily net returns on
  those sessions. One configuration, so the probability of overfitting has no
  choice to indict and is reported as 0 over 0 paths, as the statistic itself
  defines it.
- **Stress**, under the names the gate reads:
  - `costs x2`, `costs x3`: every trade's charges and slippage multiplied.
  - `drop best 5 names`: the five symbols with the largest net profit removed.
  - `regime: first half`, `regime: second half`: the sessions split at the
    midpoint, nobody's choice.
  - `entry 5 minutes late`: entered at the first open after 09:25 instead of
    09:20, the intraday form of the signal-staleness proxy.

A rule is registered in `SOURCES` with a function that returns its trades,
the late-entry trades, the sessions and the capital its returns are measured
on. Only pre-registered hypotheses belong there.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date

from eulerlab.intraday import cross_section as cs
from eulerlab.validation.cpcv import cpcv_splits, leakage_check
from eulerlab.validation.statistics import sharpe_stats
from eulerlab.validation.stress import StressResult

MIN_DAYS = 60
"""A path or regime with fewer sessions has no Sharpe worth reading."""


@dataclass(frozen=True)
class IntradayRun:
    trades: list[cs.Trade]
    late_trades: list[cs.Trade]
    sessions: list[date]
    capital: float


def _h0096() -> IntradayRun:
    from eulerlab.intraday import nse_reports_screen

    return nse_reports_screen.ban_short_run()


SOURCES: dict[str, Callable[[], IntradayRun]] = {"H-0096": _h0096}


def supported(hypothesis_id: str) -> bool:
    return hypothesis_id in SOURCES


def daily_returns(
    trades: Sequence[cs.Trade],
    sessions: Sequence[date],
    capital: float,
    *,
    cost_multiple: float = 1.0,
) -> dict[date, float]:
    """Net return on `capital` for every session; a session with no trade is 0."""
    pnl: dict[date, float] = defaultdict(float)
    for trade in trades:
        pnl[trade.day] += trade.gross - cost_multiple * trade.costs
    return {day: pnl.get(day, 0.0) / capital for day in sessions}


def sharpe_on(returns: dict[date, float], days: Sequence[date]) -> float:
    values = [returns[d] for d in days if d in returns]
    return sharpe_stats(values).sharpe if len(values) >= MIN_DAYS else 0.0


def stresses(run: IntradayRun) -> list[StressResult]:
    base_returns = daily_returns(run.trades, run.sessions, run.capital)
    base = sharpe_on(base_returns, run.sessions)
    out: list[StressResult] = []
    for multiple in (2.0, 3.0):
        stressed = sharpe_on(
            daily_returns(run.trades, run.sessions, run.capital, cost_multiple=multiple),
            run.sessions,
        )
        out.append(
            StressResult(
                f"costs x{multiple:g}",
                f"charges and slippage x{multiple:g}: Sharpe {base:.2f} -> {stressed:.2f}",
                base,
                stressed,
            )
        )
    by_name: dict[str, float] = defaultdict(float)
    for trade in run.trades:
        by_name[trade.symbol] += trade.gross - trade.costs
    best = sorted(by_name, key=lambda s: (-by_name[s], s))[:5]
    kept = [t for t in run.trades if t.symbol not in set(best)]
    stressed = sharpe_on(daily_returns(kept, run.sessions, run.capital), run.sessions)
    out.append(
        StressResult(
            "drop best 5 names",
            f"removed {', '.join(best)}: Sharpe {base:.2f} -> {stressed:.2f}",
            base,
            stressed,
        )
    )
    late = sharpe_on(daily_returns(run.late_trades, run.sessions, run.capital), run.sessions)
    out.append(
        StressResult(
            "entry 5 minutes late",
            f"entered from 09:26 instead of 09:20: Sharpe {base:.2f} -> {late:.2f}",
            base,
            late,
        )
    )
    middle = len(run.sessions) // 2
    for label, days in (
        ("first half", run.sessions[:middle]),
        ("second half", run.sessions[middle:]),
    ):
        stressed = sharpe_on(base_returns, days)
        out.append(
            StressResult(
                f"regime: {label}",
                f"{days[0]} to {days[-1]}: Sharpe {stressed:.2f}",
                base,
                stressed,
            )
        )
    return out


@dataclass
class Scored:
    label: str
    in_sample: list[float] = field(default_factory=list)
    out_of_sample: list[float] = field(default_factory=list)
    full_returns: list[float] = field(default_factory=list)
    dated_returns: dict[date, float] = field(default_factory=dict)


def evaluate(
    run: IntradayRun, *, n_blocks: int, test_blocks: int, horizon: int, embargo: int
) -> tuple[list[Scored], list[str]]:
    """The rule's Sharpe on each purged CPCV path, and its full daily series."""
    returns = daily_returns(run.trades, run.sessions, run.capital)
    scored = Scored(label="intraday rule as registered")
    notes: list[str] = []
    for i, split in enumerate(
        cpcv_splits(
            run.sessions,
            n_blocks=n_blocks,
            test_block_count=test_blocks,
            horizon=horizon,
            embargo=embargo,
        ),
        1,
    ):
        problem = leakage_check(split, run.sessions, horizon=horizon)
        if problem:
            notes.append(f"path {i}: LEAKAGE — {problem}")
            continue
        scored.in_sample.append(sharpe_on(returns, split.train_days))
        scored.out_of_sample.append(sharpe_on(returns, split.test_days))
    scored.dated_returns = returns
    scored.full_returns = list(returns.values())
    return [scored], notes
