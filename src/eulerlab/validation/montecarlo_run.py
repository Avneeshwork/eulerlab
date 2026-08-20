"""`make montecarlo` — resample a strategy's returns and report the two intervals.

Reads no ledger and writes no ledger. Resampling an *already computed* return
series evaluates nothing new — it is arithmetic on a result that has already
been paid for — so it costs no trial, and this command is safe to re-run.
"""

from __future__ import annotations

import argparse

from eulerlab.backtest import event_driven
from eulerlab.backtest.strategies import RankAndHold
from eulerlab.features.library import BY_NAME
from eulerlab.features.panel import read_panel, trading_days
from eulerlab.validation import montecarlo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monte Carlo resampling of a strategy.")
    parser.add_argument("--feature", default="momentum_12_1")
    parser.add_argument("--top-n", type=int, default=30)
    parser.add_argument("--rebalance", type=int, default=21)
    parser.add_argument("--days", type=int, default=800)
    parser.add_argument("--simulations", type=int, default=1000)
    args = parser.parse_args(argv)

    if args.feature not in BY_NAME:
        print(f"unknown feature {args.feature!r}; try {', '.join(sorted(BY_NAME))}")
        return 2

    rows = read_panel()
    if not rows:
        print("no panel. Run `make build-panel` first.")
        return 2
    days = trading_days(rows)
    if args.days and args.days < len(days):
        cutoff = days[-args.days]
        rows = [r for r in rows if r.day >= cutoff]

    strategy = RankAndHold(BY_NAME[args.feature], top_n=args.top_n)
    warmup = min(253, max(20, len(trading_days(rows)) // 4))
    result = event_driven.run(rows, strategy, rebalance_every=args.rebalance, warmup=warmup)
    returns = result.daily_returns()
    if len(returns) < 30:
        print(f"only {len(returns)} return days; widen --days")
        return 2

    print(f"\nstrategy: {strategy.describe()}   {len(returns):,} return days")
    print(montecarlo.run(returns, simulations=args.simulations).render())
    print("\nThis spent no trial: resampling an existing result evaluates nothing new.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
