"""`make walk` — walk-forward a strategy's sweep and estimate its PBO.

Answers the question the noise bar cannot: the bar corrects for *how much
searching happened*, and this asks whether the winner of that search survives
being tested on days it was not chosen on.

**Spends one trial per grid point.** The splitting is free — sessions are
re-partitioned, not re-evaluated — but producing the candidates means scanning
each setting, and a setting scanned is a configuration evaluated. The extended
`ou_reversion_in` grid contained seven settings no sweep had recorded, and
calling that free would have taken the search without the denominator that
prices it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections.abc import Sequence
from pathlib import Path

from eulerlab import optimize_walk
from eulerlab.paths import data_path

RESULTS_PATH = data_path("derived/walk_results.jsonl")


def run(
    strategy_id: str,
    *,
    start: dt.date,
    end: dt.date,
    n_blocks: int = 6,
    test_blocks: int = 2,
) -> optimize_walk.WalkResult | None:
    from eulerlab.features import trials
    from eulerlab.intraday import paper_scan
    from eulerlab.optimize import _rules, grid
    from eulerlab.optimize_run import SPACES, market_for
    from eulerlab.strategies import REGISTRY

    declaration = REGISTRY.get(strategy_id)
    if declaration is None:
        print(f"no strategy {strategy_id!r}")
        return None

    market, symbol = market_for(declaration)
    space = SPACES.get(strategy_id, SPACES["default"])
    before = trials.count()

    candidates: list[optimize_walk.Candidate] = []
    for params in grid(space):
        # Recorded before the result is read, so an interrupted walk still
        # counts what it spent.
        trials.append(
            trials.Trial(
                logged_at=trials.now_iso(),
                feature=f"{strategy_id}|{symbol}|walk|{sorted(params.items())}",
                horizon_days=(end - start).days,
                step_days=1,
                panel_start=start.isoformat(),
                panel_end=end.isoformat(),
                n_periods=0,
                mean_ic=0.0,
                t_stat=0.0,
            )
        )
        scan = paper_scan.scan_symbol(
            strategy_id,
            symbol,
            start=start,
            end=end,
            rules=_rules(params),
            equity=optimize_walk_equity(),
            asset_class=market,
        )
        candidates.append(
            optimize_walk.Candidate(params=dict(params), by_session=scan.pnl_by_session())
        )

    result = optimize_walk.walk(
        strategy_id,
        symbol,
        candidates,
        equity=optimize_walk_equity(),
        n_blocks=n_blocks,
        test_blocks=test_blocks,
    )

    print(f"{strategy_id} on {symbol} — {len(candidates)} settings, {result.splits} splits")
    print(f"  PBO                  : {result.pbo:.2f}  ({result.pbo_verdict})")
    print(f"  in-sample winner     : {result.modal_winner}")
    print(f"  its out-of-sample P&L: {result.winner_oos_pnl:>12,.0f} per split")
    print(f"  median setting       : {result.median_oos_pnl:>12,.0f} per split")
    print(f"  splits it made money : {result.oos_positive_splits}/{result.splits}")
    print(
        f"  settings that work   : {result.settings_profitable_oos}/{result.settings_total} "
        "profitable out of sample"
    )
    if result.winner_oos_sharpe is not None:
        print(f"  winner Sharpe        : {result.winner_oos_sharpe:.2f}")
    print(f"  verdict              : {result.verdict}")
    print(f"  trials spent         : {trials.count() - before} (one per setting scanned)")
    _store(result)
    return result


def _store(result: optimize_walk.WalkResult, path: Path = RESULTS_PATH) -> None:
    """Keep one row per strategy, merged, so a single-strategy run is safe.

    Replacing the file would drop every other strategy — the failure mode a
    subset sweep already caused twice in this codebase.
    """
    existing = read(path)
    existing[result.strategy_id] = {
        "strategy_id": result.strategy_id,
        "symbol": result.symbol,
        "n_blocks": result.n_blocks,
        "test_blocks": result.test_blocks,
        "splits": result.splits,
        "pbo": result.pbo,
        "pbo_verdict": result.pbo_verdict,
        "verdict": result.verdict,
        "modal_winner": result.modal_winner,
        "winner_oos_sharpe": result.winner_oos_sharpe,
        "winner_oos_pnl": result.winner_oos_pnl,
        "median_oos_pnl": result.median_oos_pnl,
        "oos_positive_splits": result.oos_positive_splits,
        "settings_profitable_oos": result.settings_profitable_oos,
        "settings_total": result.settings_total,
        "most_settings_work": result.most_settings_work,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for _, row in sorted(existing.items())),
        encoding="utf-8",
    )


def read(path: Path = RESULTS_PATH) -> dict[str, dict[str, object]]:
    """Every stored walk-forward, keyed by strategy. Corrupt lines skipped."""
    if not path.exists():
        return {}
    out: dict[str, dict[str, object]] = {}
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


def optimize_walk_equity() -> float:
    from eulerlab.intraday.adopted import EQUITY

    return EQUITY


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="walk")
    parser.add_argument("strategy")
    parser.add_argument("--start", default="2026-06-01")
    parser.add_argument("--end", default="2026-08-23")
    parser.add_argument("--blocks", type=int, default=6)
    parser.add_argument("--test-blocks", type=int, default=2)
    args = parser.parse_args(argv)

    run(
        args.strategy,
        start=dt.date.fromisoformat(args.start),
        end=dt.date.fromisoformat(args.end),
        n_blocks=args.blocks,
        test_blocks=args.test_blocks,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
