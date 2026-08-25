"""`make adopted-results` — run every swept strategy once, on the parameters it uses.

Produces the number the library shows as a strategy's result. Separate from the
sweep because it is a different question: the sweep asks which setting is best,
this asks what the chosen setting actually does.

Spends no trials, and can only run parameter sets a recorded sweep already
contains — see `intraday/adopted.py` for why that distinction is drawn narrowly.
"""

from __future__ import annotations

import argparse
import datetime as dt
from collections.abc import Sequence

from eulerlab.intraday import adopted


def run(*, start: dt.date, end: dt.date, only: Sequence[str] = ()) -> list[adopted.Result]:
    from eulerlab import optimize_store
    from eulerlab.features import trials

    before = trials.count()
    latest = optimize_store.latest()
    if latest is None:
        print("no sweep recorded yet — run `make optimize` first")
        return []
    if latest.get("dry_run", True):
        print("the last sweep was a dry run, so nothing has been adopted from it")
        return []

    rows = [r for r in latest.get("rows", []) if not only or r.get("strategy_id") in only]
    print(f"{'strategy':22s} {'symbol':7s} {'net':>12} {'sharpe':>7} {'fills':>6} {'params'}")
    print("-" * 84)

    out: list[adopted.Result] = []
    for row in rows:
        result = adopted.compute(
            str(row.get("strategy_id", "")),
            symbol=str(row.get("symbol", "")),
            market=str(row.get("market", "")),
            start=start,
            end=end,
        )
        if result is None:
            continue
        out.append(result)
        # Written after every strategy: these runs take minutes each and a
        # cache that only appears on completion is a cache that disappears on
        # any interruption.
        adopted.write(out)
        sharpe = f"{result.sharpe:.2f}" if result.sharpe is not None else "  —"
        params = ", ".join(f"{k}={v}" for k, v in sorted(result.params.items())) or "paper defaults"
        print(
            f"{result.strategy_id:22s} {result.symbol:7s} {result.net_pnl:>12,.0f} "
            f"{sharpe:>7} {result.fills:>6}  {params}",
            flush=True,
        )

    after = trials.count()
    print("-" * 84)
    # Asserted in the output rather than trusted. If this ever prints a
    # non-zero figure, something in here has started searching.
    print(f"trials spent by this run: {after - before}  (total {after})")
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="adopted-results")
    parser.add_argument("--start", default="2026-06-01")
    parser.add_argument("--end", default="2026-08-23")
    parser.add_argument("--only", default="")
    args = parser.parse_args(argv)

    run(
        start=dt.date.fromisoformat(args.start),
        end=dt.date.fromisoformat(args.end),
        only=[s.strip() for s in args.only.split(",") if s.strip()],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
