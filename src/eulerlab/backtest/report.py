"""`make backtest-fast` — run a Tier A backtest and print an honest report.

Honest here means the approximations are printed with the numbers, not filed
in documentation. A Tier A result read as though it came from an event-driven
engine is worse than no result, because it carries false precision into a
decision.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from eulerlab.backtest.strategies import BuyAndHold, RankAndHold
from eulerlab.backtest.strategy import Strategy
from eulerlab.backtest.vector import APPROXIMATIONS, BacktestResult, run
from eulerlab.features.library import BY_NAME, LIBRARY
from eulerlab.features.panel import read_panel, trading_days
from eulerlab.quality.robust import median

TRADING_DAYS_PER_YEAR = 252


def _annualised(result: BacktestResult) -> float:
    rets = result.daily_returns()
    if not rets:
        return 0.0
    years = len(rets) / TRADING_DAYS_PER_YEAR
    if years <= 0 or result.final_equity <= 0:
        return 0.0
    return float((result.final_equity / result.starting_cash) ** (1 / years) - 1.0)


def _max_drawdown(result: BacktestResult) -> float:
    peak = 0.0
    worst = 0.0
    for value in result.equity:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return worst


def _robust_sharpe(result: BacktestResult) -> float:
    """Annualised return over a **MAD-based** dispersion, not stdev.

    The same choice as everywhere else in this codebase (ADR-017): daily
    returns are fat-tailed, so a standard deviation is dominated by a handful
    of days and a Sharpe built on it moves for reasons that are not risk.
    Reported as `robust Sharpe` rather than `Sharpe` because it is not the
    textbook quantity and should not be compared to one.
    """
    rets = result.daily_returns()
    if len(rets) < 20:
        return 0.0
    centre = median(rets)
    mad = median([abs(r - centre) for r in rets])
    if mad <= 0:
        return 0.0
    daily_vol = mad * 1.4826
    return float(_annualised(result) / (daily_vol * TRADING_DAYS_PER_YEAR**0.5))


def render(result: BacktestResult) -> str:
    lines: list[str] = []
    add = lines.append
    add(f"\nstrategy       : {result.strategy}")
    add(f"cost mode      : {result.cost_mode}")
    if result.days:
        add(f"period         : {result.days[0]} to {result.days[-1]} ({len(result.days):,} days)")
    add("")
    add(f"final equity   : Rs {result.final_equity:,.0f}  (from Rs {result.starting_cash:,.0f})")
    add(f"total return   : {result.total_return:+.2%}")
    add(f"annualised     : {_annualised(result):+.2%}")
    add(f"max drawdown   : {_max_drawdown(result):.2%}")
    add(f"robust Sharpe  : {_robust_sharpe(result):.2f}   (MAD-based, not textbook)")
    add("")
    add(f"fills          : {len(result.fills):,}")
    add(f"turnover       : Rs {result.turnover:,.0f}")
    add(f"total costs    : Rs {result.total_cost:,.0f}")
    if result.turnover > 0:
        add(f"cost/turnover  : {result.total_cost / result.turnover:.4%}")
    if result.starting_cash > 0:
        add(f"costs as % of starting capital: {result.total_cost / result.starting_cash:.2%}")

    add("\nTIER A APPROXIMATIONS — this is a screen, not a backtest:")
    for item in APPROXIMATIONS:
        add(f"  - {item}")
    return "\n".join(lines)


def _build(name: str, feature: str, top_n: int, min_turnover: float = 0.0) -> Strategy:
    if name == "buyhold":
        return BuyAndHold(top_n=top_n)
    return RankAndHold(BY_NAME[feature], top_n=top_n, min_turnover=min_turnover)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="backtest-fast", description=__doc__)
    parser.add_argument("--strategy", default="", help="'buyhold', 'rank', or omit to list")
    parser.add_argument("--feature", default="momentum_12_1")
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--min-turnover", type=float, default=0.0)
    parser.add_argument("--rebalance", type=int, default=21)
    parser.add_argument("--cost-mode", default="realistic", choices=("realistic", "replication"))
    parser.add_argument("--compare", action="store_true", help="run both cost modes")
    parser.add_argument(
        "--allow-low-grade",
        action="store_true",
        help="run even if the price panel is below its data quality grade (ADR-086)",
    )
    args = parser.parse_args(argv)

    if not args.strategy:
        print("strategies: buyhold, rank")
        print("\nfeatures for --feature:")
        for feature in LIBRARY:
            print(f"  {feature.name:<22} {feature.description}")
        return 0

    from eulerlab.quality import contract

    try:
        contract.guard(["Price panel"], allow_low=args.allow_low_grade)
    except contract.LowGrade as exc:
        print(exc)
        return 3

    rows = read_panel()
    if not rows:
        print("no panel. Run `make build-panel` first.")
        return 2
    days = trading_days(rows)
    print(f"panel: {len(rows):,} rows, {len(days):,} days, {days[0]} to {days[-1]}")

    strategy = _build(args.strategy, args.feature, args.top, args.min_turnover)
    modes = ("replication", "realistic") if args.compare else (args.cost_mode,)
    results = []
    for mode in modes:
        result = run(
            rows, strategy, rebalance_every=args.rebalance, cost_mode=mode, asset_class="equity"
        )
        results.append(result)
        print(render(result))

    if len(results) == 2:
        free, paid = results
        drag = free.total_return - paid.total_return
        print(f"\ncost drag      : {drag:+.2%} of total return")
        print(
            "That difference is the whole question Sprint 9 exists to answer: a\n"
            "signal is only real if it survives it."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
