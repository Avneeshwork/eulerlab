"""`make tune-sharpe-momentum` — sweep the volatility-adjusted momentum strategy's
own three settings, choose on the years before 2024, and test once on 2024 on.

The strategy is `india_sharpe_momentum` (research 064): hold the top N of the
point-in-time top 250 by return over a window divided by volatility over the
same window, rebalanced every R sessions. Those are its only settings, and the
sweep varies only them — no new rule is added:

- `window`  — sessions the return and volatility are measured over (paper: 252)
- `top`     — names held, equal-weighted (paper: 30)
- `rebalance` — sessions between rebalances (paper: 21)

### How overfitting is guarded against

1. **A holdout.** Every choice is made on 2016-2023. 2024-01-01 to the end of
   the panel is read only to report the chosen setting's result. Research 064
   had already run the paper's setting over those years, so the holdout is
   unseen for the *choice*, not for the project; research 067 says so.
2. **A plateau, not a peak.** A setting is scored by the mean in-sample Sharpe
   of itself and its grid neighbours. A lone spike surrounded by poor settings
   loses to a broad region of good ones.
3. **Walk-forward.** For each year 2019-2023 the rule above is applied to the
   years before it, and the chosen setting's next year is recorded. The stitched
   years are what choosing this way would actually have earned.
4. **PBO and deflated Sharpe.** CSCV over eight in-sample blocks estimates how
   often the in-sample winner lands below the median out of sample; the deflated
   Sharpe charges the chosen result for every setting in the grid.

Each setting runs once over the whole panel through `event_driven.run`, the
Tier B engine the batch uses, and its daily equity is kept. In-sample, fold and
holdout statistics are slices of that one curve. The strategy is causal, so a
year's slice is what that year would have earned; the only carry-over is the
portfolio held on its first day.

Results are appended per setting to `RUNS`, so a run interrupted part-way
resumes where it stopped. These are screening runs: like `make india-papers`
they spend no trial in the ledger.
"""

from __future__ import annotations

import argparse
import itertools
import json
import time
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from eulerlab.validation.statistics import (
    deflated_sharpe,
    expected_max_sharpe,
    probability_of_backtest_overfitting,
    sharpe_stats,
)

STRATEGY_ID = "india_sharpe_momentum"
OUT_DIR = Path("data/derived/sweeps") / STRATEGY_ID
RUNS = OUT_DIR / "runs.jsonl"
SUMMARY = OUT_DIR / "summary.json"

WINDOWS = (63, 126, 189, 252)
TOPS = (10, 20, 30, 50)
REBALANCES = (10, 21, 42, 63)
PAPER = (252, 30, 21)

HOLDOUT_STARTS = date(2024, 1, 1)
WALK_YEARS = (2019, 2020, 2021, 2022, 2023)
CSCV_BLOCKS = 8
WARMUP = 253  # what the batch uses on the whole panel (`warmup_for`)

Params = tuple[int, int, int]


def key_of(params: Params) -> str:
    return "w{}-n{}-r{}".format(*params)


def grid() -> list[Params]:
    return list(itertools.product(WINDOWS, TOPS, REBALANCES))


# --- running -----------------------------------------------------------------


def _load_runs(path: Path = RUNS) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            out[record["key"]] = record
    return out


def _run_one(params: Params, *, cost_multiplier: float) -> dict[str, Any]:
    from eulerlab.api.panels import PANEL
    from eulerlab.backtest import event_driven
    from eulerlab.backtest.india_papers import (
        LIQUID_TOP,
        RankTop,
        sharpe_momentum_over,
    )
    from eulerlab.strategies import AssetClass

    window, top, rebalance = params
    rows = PANEL.rows(0)
    strategy = RankTop(
        STRATEGY_ID,
        sharpe_momentum_over(window),
        fraction=top / LIQUID_TOP,
        highest=True,
        rebalance_every=rebalance,
        lookback=window + 5,
    )
    began = time.monotonic()
    result = event_driven.run(
        rows,
        strategy,
        asset_class=AssetClass.EQUITY.value,
        rebalance_every=rebalance,
        warmup=WARMUP,
        adjusted_index=PANEL.index(0, rows, "all"),
        cost_mode="realistic",
        cost_multiplier=cost_multiplier,
    )
    return {
        "key": key_of(params) + ("" if cost_multiplier == 1.0 else f"-c{cost_multiplier:g}"),
        "params": {"window": window, "top": top, "rebalance": rebalance},
        "cost_multiplier": cost_multiplier,
        "fills": len(result.fills),
        "costs": round(result.total_cost, 2),
        "seconds": round(time.monotonic() - began),
        "days": [d.isoformat() for d in result.days],
        "equity": [round(v, 2) for v in result.equity],
    }


def run_all(settings: Sequence[Params], *, cost_multiplier: float = 1.0) -> None:
    done = _load_runs()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for i, params in enumerate(settings, 1):
        key = key_of(params) + ("" if cost_multiplier == 1.0 else f"-c{cost_multiplier:g}")
        if key in done:
            continue
        print(f"[{i}/{len(settings)}] {key} ...", flush=True)
        record = _run_one(params, cost_multiplier=cost_multiplier)
        # One line per finished setting, flushed, so an interruption loses at
        # most the setting in progress.
        with RUNS.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        total = record["equity"][-1] / record["equity"][0] - 1.0 if record["equity"] else 0.0
        print(f"   {record['seconds']}s fills={record['fills']} total={total:+.0%}", flush=True)


# --- analysing ---------------------------------------------------------------


def _returns(record: dict[str, Any]) -> list[tuple[date, float]]:
    days = [date.fromisoformat(d) for d in record["days"]]
    equity = record["equity"]
    return [(days[i], equity[i] / equity[i - 1] - 1.0) for i in range(1, len(equity))]


def _slice(series: list[tuple[date, float]], start: date | None, end: date | None) -> list[float]:
    return [r for d, r in series if (start is None or d >= start) and (end is None or d < end)]


def _sharpe(returns: Sequence[float]) -> float:
    return sharpe_stats(returns).sharpe


def describe(returns: Sequence[float]) -> dict[str, float]:
    """Sharpe, CAGR, total return and max drawdown of a daily return series."""
    level, peak, worst = 1.0, 1.0, 0.0
    for r in returns:
        level *= 1.0 + r
        peak = max(peak, level)
        worst = min(worst, level / peak - 1.0)
    years = len(returns) / 252
    return {
        "sharpe": round(_sharpe(returns), 3),
        "cagr": round(level ** (1 / years) - 1.0, 4) if years > 0 and level > 0 else 0.0,
        "total_return": round(level - 1.0, 4),
        "max_drawdown": round(worst, 4),
        "days": len(returns),
    }


def _neighbours(params: Params) -> list[Params]:
    axes = (WINDOWS, TOPS, REBALANCES)
    out = []
    for axis, values in enumerate(axes):
        i = values.index(params[axis])
        for j in (i - 1, i + 1):
            if 0 <= j < len(values):
                moved = list(params)
                moved[axis] = values[j]
                out.append((moved[0], moved[1], moved[2]))
    return out


def plateau_scores(sharpes: dict[Params, float]) -> dict[Params, float]:
    """Mean Sharpe of a setting and its one-step grid neighbours."""
    out = {}
    for params, own in sharpes.items():
        values = [own, *(sharpes[n] for n in _neighbours(params) if n in sharpes)]
        out[params] = sum(values) / len(values)
    return out


def choose(sharpes: dict[Params, float]) -> Params:
    scores = plateau_scores(sharpes)
    return max(scores, key=lambda p: (scores[p], sharpes[p], p))


def analyse() -> dict[str, Any]:
    runs = _load_runs()
    settings = [p for p in grid() if key_of(p) in runs]
    if len(settings) < len(grid()):
        print(f"warning: {len(settings)} of {len(grid())} settings have run; analysing those")
    series = {p: _returns(runs[key_of(p)]) for p in settings}
    first_day = min(d for s in series.values() for d, _ in s[:1])

    train = {p: _slice(s, None, HOLDOUT_STARTS) for p, s in series.items()}
    hold = {p: _slice(s, HOLDOUT_STARTS, None) for p, s in series.items()}
    train_sharpe = {p: _sharpe(r) for p, r in train.items()}
    hold_sharpe = {p: _sharpe(r) for p, r in hold.items()}
    plateau = plateau_scores(train_sharpe)
    chosen = choose(train_sharpe)
    best_point = max(train_sharpe, key=lambda p: (train_sharpe[p], p))

    # Walk-forward: choose on everything before year Y, earn year Y.
    walk = []
    stitched: list[float] = []
    stitched_paper: list[float] = []
    for year in WALK_YEARS:
        cut, after = date(year, 1, 1), date(year + 1, 1, 1)
        fold_sharpe = {p: _sharpe(_slice(s, None, cut)) for p, s in series.items()}
        pick = choose(fold_sharpe)
        earned = _slice(series[pick], cut, after)
        stitched += earned
        if PAPER in series:
            stitched_paper += _slice(series[PAPER], cut, after)
        walk.append(
            {"year": year, "chosen": key_of(pick), "next_year": describe(earned)["total_return"]}
        )

    # CSCV: split the in-sample days into blocks, every half as in-sample.
    n_days = min(len(r) for r in train.values())
    edges = [round(i * n_days / CSCV_BLOCKS) for i in range(CSCV_BLOCKS + 1)]
    blocks = {p: [r[edges[i] : edges[i + 1]] for i in range(CSCV_BLOCKS)] for p, r in train.items()}
    order = list(settings)
    is_scores, oos_scores = [], []
    for picked in itertools.combinations(range(CSCV_BLOCKS), CSCV_BLOCKS // 2):
        rest = [i for i in range(CSCV_BLOCKS) if i not in picked]
        is_scores.append([_sharpe([x for i in picked for x in blocks[p][i]]) for p in order])
        oos_scores.append([_sharpe([x for i in rest for x in blocks[p][i]]) for p in order])
    pbo = probability_of_backtest_overfitting(is_scores, oos_scores)

    values = list(train_sharpe.values())
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / max(1, len(values) - 1)
    stats = sharpe_stats(train[chosen])
    dsr = deflated_sharpe(stats, n_trials=len(settings), variance_of_sharpes=variance)
    noise_bar = expected_max_sharpe(len(settings), variance_of_sharpes=variance)

    # Does in-sample rank carry into the holdout at all?
    def ranks(scores: dict[Params, float]) -> dict[Params, int]:
        return {p: i for i, p in enumerate(sorted(scores, key=lambda p: scores[p]))}

    ri, rh = ranks(train_sharpe), ranks(hold_sharpe)
    n = len(settings)
    rank_corr = 1 - 6 * sum((ri[p] - rh[p]) ** 2 for p in settings) / (n * (n * n - 1))

    def side_by_side(p: Params) -> dict[str, Any]:
        record = runs[key_of(p)]
        stress = runs.get(key_of(p) + "-c2")
        out: dict[str, Any] = {
            "setting": key_of(p),
            "params": list(p),
            "in_sample": describe(train[p]),
            "holdout": describe(hold[p]),
            "whole": describe([r for _, r in series[p]]),
            "fills": record["fills"],
            "costs": record["costs"],
            "plateau_sharpe": round(plateau[p], 3),
            "holdout_rank": n - rh[p],
        }
        if stress:
            s = _returns(stress)
            out["at_2x_costs"] = {
                "in_sample": describe(_slice(s, None, HOLDOUT_STARTS)),
                "holdout": describe(_slice(s, HOLDOUT_STARTS, None)),
            }
        return out

    summary = {
        "strategy": STRATEGY_ID,
        "grid": {"window": WINDOWS, "top": TOPS, "rebalance": REBALANCES},
        "settings_run": len(settings),
        "in_sample": [first_day.isoformat(), "2023-12-31"],
        "holdout_from": HOLDOUT_STARTS.isoformat(),
        "chosen": side_by_side(chosen),
        "paper": side_by_side(PAPER) if PAPER in series else None,
        "best_single_point": side_by_side(best_point),
        "walk_forward": {
            "folds": walk,
            "stitched": describe(stitched),
            "paper_same_years": describe(stitched_paper) if stitched_paper else None,
        },
        "pbo": {"value": round(pbo.pbo, 3), "splits": pbo.n_paths, "verdict": pbo.verdict},
        "deflated_sharpe": {
            "probability": round(dsr, 4),
            "trials": len(settings),
            "noise_bar_sharpe": round(noise_bar, 3),
        },
        "rank_correlation_in_sample_vs_holdout": round(rank_corr, 3),
        "table": [
            {
                "setting": key_of(p),
                "in_sample_sharpe": round(train_sharpe[p], 3),
                "plateau_sharpe": round(plateau[p], 3),
                "holdout_sharpe": round(hold_sharpe[p], 3),
                "fills": runs[key_of(p)]["fills"],
            }
            for p in sorted(settings, key=lambda p: -plateau[p])
        ],
        "spent_trials": 0,
        "note": "Screening sweep: no trial recorded in the ledger.",
    }
    SUMMARY.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _print(summary: dict[str, Any]) -> None:
    def line(label: str, block: dict[str, Any] | None) -> None:
        if not block:
            return
        a, b = block["in_sample"], block["holdout"]
        print(
            f"{label:<14}{block['setting']:<14}"
            f"IS sharpe {a['sharpe']:>5.2f} cagr {a['cagr']:>6.1%} dd {a['max_drawdown']:>6.1%} | "
            f"HO sharpe {b['sharpe']:>5.2f} cagr {b['cagr']:>6.1%} dd {b['max_drawdown']:>6.1%}"
        )

    line("chosen", summary["chosen"])
    line("paper", summary["paper"])
    line("best point", summary["best_single_point"])
    wf = summary["walk_forward"]
    print(f"walk-forward 2019-2023: {wf['stitched']}  (paper same years: {wf['paper_same_years']})")
    print(f"PBO {summary['pbo']}  DSR {summary['deflated_sharpe']}")
    print(f"rank correlation IS vs holdout: {summary['rank_correlation_in_sample_vs_holdout']}")
    print(f"written to {SUMMARY}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tune-sharpe-momentum")
    parser.add_argument("--analyse-only", action="store_true")
    args = parser.parse_args(argv)
    if not args.analyse_only:
        run_all(grid())
        first = analyse()
        w, n, r = first["chosen"]["params"]
        stress = [(w, n, r), PAPER]
        run_all(stress, cost_multiplier=2.0)
    _print(analyse())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
