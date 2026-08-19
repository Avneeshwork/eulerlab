"""`make backtest` — run Tier B, and reconcile it against Tier A.

The reconciliation is not a footnote, it is the reason the command runs both.
`CLAUDE.md` requires one `Strategy` used unchanged across engines, and the
only way to know that is true rather than aspirational is to run the same
object through both and compare the curves.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from eulerlab.backtest import event_driven, vector
from eulerlab.backtest.report import _annualised, _build, _max_drawdown, _robust_sharpe
from eulerlab.features.library import LIBRARY
from eulerlab.features.panel import read_panel, trading_days


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="backtest", description=__doc__)
    parser.add_argument("--strategy", default="", help="'buyhold', 'rank', or omit to list")
    parser.add_argument("--feature", default="momentum_12_1")
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--min-turnover", type=float, default=0.0)
    parser.add_argument("--rebalance", type=int, default=21)
    parser.add_argument("--cost-mode", default="realistic", choices=("realistic", "replication"))
    parser.add_argument("--no-reconcile", action="store_true")
    args = parser.parse_args(argv)

    if not args.strategy:
        print("strategies: buyhold, rank")
        for feature in LIBRARY:
            print(f"  {feature.name:<22} {feature.description}")
        return 0

    rows = read_panel()
    if not rows:
        print("no panel. Run `make build-panel` first.")
        return 2
    days = trading_days(rows)
    print(f"panel: {len(rows):,} rows, {len(days):,} days, {days[0]} to {days[-1]}")

    strategy = _build(args.strategy, args.feature, args.top, args.min_turnover)
    common = {"rebalance_every": args.rebalance, "cost_mode": args.cost_mode}

    result = event_driven.run(rows, strategy, **common)
    print(f"\nstrategy       : {result.strategy}")
    print(f"cost mode      : {result.cost_mode}")
    if result.days:
        print(f"period         : {result.days[0]} to {result.days[-1]} ({len(result.days):,} days)")
    print(
        f"\nfinal equity   : Rs {result.final_equity:,.0f}  (from Rs {result.starting_cash:,.0f})"
    )
    print(f"total return   : {result.total_return:+.2%}")
    print(f"annualised     : {_annualised(result):+.2%}")  # type: ignore[arg-type]
    print(f"max drawdown   : {_max_drawdown(result):.2%}")  # type: ignore[arg-type]
    print(f"robust Sharpe  : {_robust_sharpe(result):.2f}   (MAD-based, not textbook)")  # type: ignore[arg-type]

    print("\n-- order lifecycle, which Tier A cannot express --")
    print(f"orders placed  : {len(result.orders):,}")
    print(f"filled         : {len(result.fills):,}")
    print(f"rejected       : {len(result.rejections):,}  (instrument did not trade that day)")
    if result.portfolio:
        print(f"realised P&L   : Rs {result.portfolio.realised_pnl:,.0f}")
        print(f"total costs    : Rs {result.portfolio.total_costs:,.0f}")

    if not args.no_reconcile:
        tier_a = vector.run(rows, strategy, **common)
        rec = event_driven.reconcile(tier_a.equity, result.equity)
        print("\n-- reconciliation against Tier A --")
        print(f"days compared  : {rec.days:,}")
        print(f"Tier A final   : Rs {rec.tier_a_final:,.2f}")
        print(f"Tier B final   : Rs {rec.tier_b_final:,.2f}")
        print(f"max difference : {rec.max_relative:.2e} relative")
        print(f"agree          : {rec.agrees}")
        print(f"Tier A not optimistic: {rec.tier_a_is_pessimistic}")
        if not rec.agrees:
            print(
                "\nDIVERGENCE. The two engines share one Strategy and one cost path, so a\n"
                "difference beyond floating-point noise is a bug in one of them, not a\n"
                "modelling choice. Do not read either number until it is explained."
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
