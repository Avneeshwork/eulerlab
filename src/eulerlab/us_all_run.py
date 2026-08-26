"""`make us-all` — run every strategy on US equity, whatever market its paper used.

This asks a different question from `make optimize` and from `make
adopted-results`, and the difference is the point.

- `optimize` asks: which parameter setting is best, on the market the paper tested?
- `adopted-results` asks: what does the strategy do on the setting we chose?
- **this** asks: does the signal work on US equity at all?

Ten of the twenty signals were published or constructed for crypto, and have
only ever been measured on BTCUSDT. Running them on QQQ is not a re-measurement
of a result this platform already holds; it is a new test on an instrument they
have never seen.

### So it spends trials, unlike the confirmation runs

`intraday/adopted.py` may re-run only parameter sets a recorded sweep already
contains, on the same window, and spends nothing — it extracts another statistic
from work already paid for. This does not qualify. A signal evaluated on a new
instrument is a new configuration, and a search that tries twenty signals on a
new market and reports the best of them is exactly the max-of-N problem the
ledger exists to price.

Twenty-one trials, one per strategy. Small next to the 180 a sweep costs, and
recorded for the same reason.

### Every strategy runs on the parameters it actually uses

Not the paper's, where a sweep moved them. A crypto signal whose grid all lost
keeps its published values, which is the right default and also the honest one:
nothing about a losing BTCUSDT grid tells us which parameter suits QQQ.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from eulerlab.intraday import adopted

RESULTS_PATH = Path("data/derived/us_all_results.jsonl")

SYMBOL = "QQQ"
"""One liquid instrument, so the comparison across strategies is like for like.

QQQ rather than a cross-section: the question is whether a signal has any edge
on US equity, and twenty signals across five hundred names is a different and
far more expensive question — five hundred times the trial cost, for a claim
about breadth rather than about the signals."""


def run(*, start: dt.date, end: dt.date, only: Sequence[str] = ()) -> list[adopted.Result]:
    from eulerlab.features import trials
    from eulerlab.intraday.paper_scan import ALL_SIGNALS
    from eulerlab.strategies import REGISTRY

    before = trials.count()
    ids = [
        d.id
        for d in REGISTRY.values()
        if not d.is_strategy_subclass and d.id in ALL_SIGNALS and (not only or d.id in only)
    ]
    print(f"trials spent before this run: {before}")
    print(f"{'strategy':22s} {'net':>11} {'sharpe':>7} {'fills':>6}  home market")
    print("-" * 72)

    out: list[adopted.Result] = []
    for strategy_id in ids:
        result = adopted.compute(strategy_id, symbol=SYMBOL, market="us", start=start, end=end)
        if result is None:
            continue

        # Recorded before the row is printed, so an interrupted run still counts
        # what it spent. Counting only completed runs understates the
        # denominator, which is the direction that flatters.
        trials.append(
            trials.Trial(
                logged_at=trials.now_iso(),
                feature=f"{strategy_id}|{SYMBOL}|us-cross-test",
                horizon_days=(end - start).days,
                step_days=1,
                panel_start=start.isoformat(),
                panel_end=end.isoformat(),
                n_periods=result.sessions,
                mean_ic=result.net_pnl / adopted.EQUITY,
                t_stat=0.0,
            )
        )

        out.append(result)
        _write(out)
        declaration = REGISTRY.get(strategy_id)
        home = (declaration.recommended_class if declaration else "") or "?"
        sharpe = f"{result.sharpe:.2f}" if result.sharpe is not None else "  —"
        print(
            f"{strategy_id:22s} {result.net_pnl:>11,.0f} {sharpe:>7} {result.fills:>6}  {home}",
            flush=True,
        )

    after = trials.count()
    print("-" * 72)
    print(f"trials spent by this run: {after - before}  (total {after})")
    winners = [r for r in out if r.net_pnl > 0]
    print(f"{len(winners)} of {len(out)} made money on {SYMBOL}")
    return out


def _write(results: list[adopted.Result], path: Path = RESULTS_PATH) -> None:
    from eulerlab import strategy_results

    strategy_results.merge(strategy_results.US_CROSS, [adopted._as_row(r) for r in results])

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(
                {
                    "strategy_id": r.strategy_id,
                    "symbol": r.symbol,
                    "market": r.market,
                    "start": r.start,
                    "end": r.end,
                    "params": r.params,
                    "adopted": r.adopted,
                    "net_pnl": r.net_pnl,
                    "gross_pnl": r.gross_pnl,
                    "costs": r.costs,
                    "fills": r.fills,
                    "wins": r.wins,
                    "sessions": r.sessions,
                    "sharpe": r.sharpe,
                    "alt_broker": r.alt_broker,
                    "alt_net_pnl": r.alt_net_pnl,
                    "alt_costs": r.alt_costs,
                    "alt_sharpe": r.alt_sharpe,
                    "curve": r.curve,
                    "max_drawdown": r.max_drawdown,
                    "best_session": r.best_session,
                    "worst_session": r.worst_session,
                    "exits": r.exits,
                    "rejections": r.rejections,
                    "at": r.at,
                },
                sort_keys=True,
            )
            + "\n"
            for r in results
        ),
        encoding="utf-8",
    )


def read(path: Path = RESULTS_PATH) -> dict[str, dict[str, Any]]:
    """Every strategy's US result, keyed by strategy. Corrupt lines skipped."""
    if not path.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("strategy_id"):
            out[str(row["strategy_id"])] = row
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="us-all")
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
