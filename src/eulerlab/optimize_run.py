"""`make optimize` — sweep every strategy, on the market its paper tested.

Runs one strategy at a time and reports, for each, the best candidate **beside
the median**. The gap between them is the finding: the maximum of N draws from
noise rises with N, so a best far above its median has found the right tail of
a sample rather than an edge.

Each signal is swept on its `recommended_class` — the market its source paper
tested — because a signal published on US equity futures and swept on NSE
minute bars is being asked a different question than the one it answers.

The trial count is printed before and after. Every configuration evaluated is
permanent and raises the bar for every result this platform will ever produce,
so the cost is stated rather than buried.
"""

from __future__ import annotations

import argparse
import datetime as dt
from collections.abc import Sequence

from eulerlab import optimize
from eulerlab.features import trials

SPACES: dict[str, dict[str, list[float]]] = {
    # Deliberately small. A three-point sweep of two parameters is nine trials
    # per strategy; a ten-point sweep of four would be ten thousand across the
    # library, and the deflated-Sharpe denominator does not forget.
    # The two knobs every bracket signal shares: where the stop sits and how
    # far the target reaches. Field names checked against `PaperRules` rather
    # than guessed — the first version swept `target_r_multiple`, which does
    # not exist, and every strategy errored out. That the sweep refused rather
    # than silently ignoring the unknown key is the behaviour worth keeping.
    "default": {
        "stop_atr_mult": [1.0, 1.4, 2.0],
        "target_r": [1.5, 2.0, 3.0],
    },
}

SYMBOL_FOR: dict[str, str] = {
    "equity": "RELIANCE",
    "crypto": "BTCUSDT",
}
"""One liquid instrument per class. A sweep across a universe multiplies the
trial cost by the universe size for a question about parameters, not breadth."""


def run(
    strategy_ids: Sequence[str],
    *,
    start: dt.date,
    end: dt.date,
    record: bool = True,
) -> list[optimize.Sweep]:
    from eulerlab.strategies import REGISTRY

    before = trials.count()
    print(f"trials spent before this run: {before}")
    print(f"{'strategy':22s} {'class':8s} {'cands':>5} {'best':>12} {'median':>12} {'spread':>12}")
    print("-" * 76)

    out: list[optimize.Sweep] = []
    for strategy_id in strategy_ids:
        declaration = REGISTRY.get(strategy_id)
        if declaration is None:
            continue
        # The paper's market, not ours. `recommended_class` is what the source
        # tested; falling back to the declared class only when it is absent.
        wanted = (declaration.recommended_class or declaration.asset_class.value).lower()
        asset_class = "crypto" if "crypto" in wanted else "equity"
        symbol = SYMBOL_FOR.get(asset_class, "RELIANCE")

        sweep = optimize.sweep_intraday(
            strategy_id,
            symbol,
            asset_class=asset_class,
            space=SPACES["default"],
            start=start,
            end=end,
            record=record,
        )
        out.append(sweep)
        top = sweep.best
        print(
            f"{strategy_id:22s} {asset_class:8s} {len(sweep.candidates):>5} "
            f"{top.net_pnl if top else 0:>12,.0f} {sweep.median_pnl:>12,.0f} "
            f"{sweep.spread:>12,.0f}"
            f"{'  ' + sweep.error if sweep.error else ''}",
            flush=True,
        )

    after = trials.count()
    print("-" * 76)
    print(f"trials spent by this run: {after - before}  (total {after})")
    if out:
        print(f"a result now needs t > {out[-1].required_t:.2f} to clear the noise bar")
        profitable = [s for s in out if s.best and s.best.net_pnl > 0]
        print(f"{len(profitable)} of {len(out)} had any profitable candidate")
        wide = [s for s in out if s.best and s.spread > abs(s.median_pnl) * 2]
        print(
            f"{len(wide)} of {len(out)} had a best more than twice their median — "
            "that gap is the sweep finding variance, not edge"
        )
    return out


def main(argv: Sequence[str] | None = None) -> int:
    from eulerlab.strategies import REGISTRY

    parser = argparse.ArgumentParser(prog="optimize")
    parser.add_argument("--start", default="2026-06-01")
    parser.add_argument("--end", default="2026-08-23")
    parser.add_argument("--only", default="", help="comma-separated strategy ids")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="evaluate without recording trials — for checking the sweep, never for a result",
    )
    args = parser.parse_args(argv)

    if args.only:
        ids = [s.strip() for s in args.only.split(",") if s.strip()]
    else:
        ids = [d.id for d in REGISTRY.values() if not d.is_strategy_subclass]

    run(
        ids,
        start=dt.date.fromisoformat(args.start),
        end=dt.date.fromisoformat(args.end),
        record=not args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
