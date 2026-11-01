"""`make validate H=H-0001` — put a hypothesis through the battery.

The order of operations is the design. Each step can stop the run, and the
cheap disqualifying checks come first, so an untrustworthy ledger or a
holdout violation is caught before any expensive analysis lends it false
authority.

1. **Verify the trial ledger.** If the hash chain is broken, every
   multiple-testing correction below rests on a trial count that may have been
   edited, and the correct response is to report nothing at all.
2. **Truncate the holdout.** Once, at the top, so nothing downstream can reach
   past it.
3. **Run every configuration over every CPCV path.** Purged and embargoed.
4. **Compute PBO, Deflated Sharpe, MinBTL** from those paths and the real
   trial count.
5. **Log the validation itself as a trial**, because running the battery is an
   evaluation too, and a counter that exempts its own use is not a counter.
6. **Emit a hash-signed evidence pack.**

The evidence pack is JSON and Markdown rather than the PDF the build plan
names. A PDF would add a rendering dependency for presentation only; the hash
is what makes it evidence, and a hash over JSON is easier to verify than a
hash over a generated document.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from itertools import pairwise
from pathlib import Path

from eulerlab.backtest import event_driven
from eulerlab.backtest.strategies import RankAndHold
from eulerlab.features.library import BY_NAME
from eulerlab.features.panel import PanelRow, read_panel, trading_days
from eulerlab.validation import holdout as holdout_mod
from eulerlab.validation import ledger, search_bar, stress
from eulerlab.validation.cpcv import cpcv_splits, leakage_check
from eulerlab.validation.statistics import (
    deflated_sharpe,
    min_backtest_length,
    probability_of_backtest_overfitting,
    sharpe_stats,
)

HYPOTHESES = Path("hypotheses")
EVIDENCE = Path("data/derived/evidence")


@dataclass
class ConfigResult:
    label: str
    in_sample: list[float] = field(default_factory=list)
    out_of_sample: list[float] = field(default_factory=list)
    full_returns: list[float] = field(default_factory=list)
    dated_returns: dict[date, float] = field(default_factory=dict)


def _strategy_for(config: dict[str, object]) -> tuple[RankAndHold, int]:
    """Build a strategy from a config row, with the casts in one place.

    Configurations come from YAML, so every field arrives as `object`. Doing
    the conversion once here keeps `# type: ignore` out of the analysis code,
    where it would be easy to silence a real mistake.
    """
    if str(config.get("feature", "")) in BY_NAME and not config.get("min_turnover"):
        feature = BY_NAME[str(config["feature"])]
        top_n = int(str(config["top_n"]))
        rebalance = int(str(config["rebalance"]))
        return RankAndHold(feature, top_n=top_n), rebalance
    # A formula feature or a liquidity floor (idea lab cards, ADR-116): build it exactly
    # as the lab tested it, so validation judges the same strategy.
    from eulerlab.research import codegen

    built = codegen.build_one(config)
    if not isinstance(built.strategy, RankAndHold):
        msg = f"validation runs rank_and_hold configurations, not {config.get('shape')!r}"
        raise ValueError(msg)
    return built.strategy, built.rebalance


def _sharpe_of(rows: Sequence[PanelRow], config: dict[str, object]) -> float:
    """Annualised Sharpe of one configuration over one set of days."""
    if len(trading_days(rows)) < 300:
        return 0.0
    strategy, rebalance = _strategy_for(config)
    result = event_driven.run(
        rows, strategy, rebalance_every=rebalance, warmup=253, asset_class="equity"
    )
    return sharpe_stats(result.daily_returns()).sharpe


def evaluate(
    rows: Sequence[PanelRow],
    configurations: Sequence[dict[str, object]],
    *,
    n_blocks: int,
    test_blocks: int,
    horizon: int,
    embargo: int,
    verbose: bool = True,
) -> tuple[list[ConfigResult], list[str]]:
    """Score every configuration on every purged CPCV path."""
    days = trading_days(rows)
    by_day: dict[date, list[PanelRow]] = {d: [] for d in days}
    for row in rows:
        by_day[row.day].append(row)

    results = [ConfigResult(label=_label(c)) for c in configurations]
    notes: list[str] = []

    splits = list(
        cpcv_splits(
            days,
            n_blocks=n_blocks,
            test_block_count=test_blocks,
            horizon=horizon,
            embargo=embargo,
        )
    )
    if verbose:
        print(f"  {len(splits)} CPCV paths, {len(configurations)} configurations")

    for i, split_ in enumerate(splits, 1):
        problem = leakage_check(split_, days, horizon=horizon)
        if problem:
            notes.append(f"path {i}: LEAKAGE — {problem}")
            continue

        train_rows = [r for d in split_.train_days for r in by_day[d]]
        test_rows = [r for d in split_.test_days for r in by_day[d]]

        for config, result in zip(configurations, results, strict=True):
            result.in_sample.append(_sharpe_of(train_rows, config))
            result.out_of_sample.append(_sharpe_of(test_rows, config))
        if verbose:
            print(
                f"  path {i}/{len(splits)}: train {split_.n_train:,}d "
                f"(purged {split_.purged}, embargoed {split_.embargoed}), "
                f"test {split_.n_test:,}d"
            )

    for config, result in zip(configurations, results, strict=True):
        result.dated_returns = _dated_returns_of(rows, config)
        result.full_returns = list(result.dated_returns.values())

    return results, notes


def _dated_returns_of(rows: Sequence[PanelRow], config: dict[str, object]) -> dict[date, float]:
    """Daily returns keyed by the day they were earned, in day order."""
    strategy, rebalance = _strategy_for(config)
    run = event_driven.run(
        rows, strategy, rebalance_every=rebalance, warmup=253, asset_class="equity"
    )
    return {
        day: after / before - 1.0
        for (_, before), (day, after) in pairwise(zip(run.days, run.equity, strict=True))
        if before > 0
    }


def _label(config: dict[str, object]) -> str:
    return f"{config['feature']}|top{config['top_n']}|rb{config['rebalance']}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="validate", description=__doc__)
    parser.add_argument("--hypothesis", default="H-0001")
    parser.add_argument("--blocks", type=int, default=6)
    parser.add_argument("--test-blocks", type=int, default=2)
    parser.add_argument("--horizon", type=int, default=21)
    parser.add_argument("--embargo", type=int, default=5)
    parser.add_argument("--no-stress", action="store_true")
    args = parser.parse_args(argv)

    # --- 1. the ledger must be trustworthy before anything else runs ---
    ledger.migrate_from_trials(Path("data/derived/trials.jsonl"))
    chain = ledger.verify_chain()
    print(f"trial ledger   : {chain.detail}")
    if not chain.intact:
        print(
            "\nREFUSING TO VALIDATE. Every correction below divides by the trial\n"
            "count, and the chain says that count may have been edited. Fix the\n"
            "ledger, or explain the break, before reading any number from here."
        )
        return 1
    n_trials = chain.entries

    path = HYPOTHESES / f"{args.hypothesis}.yaml"
    if not path.exists():
        print(f"no hypothesis at {path}")
        return 2
    hypothesis = holdout_mod.load(path)
    print(f"hypothesis     : {hypothesis.id} — {hypothesis.title}")

    rows = read_panel()
    if not rows:
        print("no panel. Run `make build-panel` first.")
        return 2

    # --- 2. the holdout is removed once, at the top ---
    rows, dropped = holdout_mod.truncate(rows, hypothesis.holdout)
    days = trading_days(rows)
    print(
        f"holdout        : {hypothesis.holdout.starts} onward withheld "
        f"({dropped:,} rows), status={hypothesis.holdout.status}"
    )
    print(f"in-sample      : {len(days):,} days, {days[0]} to {days[-1]}")

    # --- 3. CPCV ---
    print("\nrunning purged CPCV...")
    results, notes = evaluate(
        rows,
        hypothesis.configurations,
        n_blocks=args.blocks,
        test_blocks=args.test_blocks,
        horizon=args.horizon,
        embargo=args.embargo,
    )

    # --- 4. the statistics ---
    in_sample = [list(col) for col in zip(*[r.in_sample for r in results], strict=True)]
    out_sample = [list(col) for col in zip(*[r.out_of_sample for r in results], strict=True)]
    pbo = probability_of_backtest_overfitting(in_sample, out_sample)

    # --- 4a. the bar from what was searched (ADR-108, research 138) ---
    from eulerlab import gates

    search_rules = gates.load_mandate()["statistical"]["search_correction"]
    best_result = max(results, key=lambda r: sharpe_stats(r.full_returns).sharpe)
    search = search_bar.assess(
        best_result.dated_returns,
        [r.dated_returns for r in results if r is not best_result],
        search_rules,
    )
    family = search.get("families") or {}
    if family:
        bar_n = int(family["families"])
        bar_var = float(family["sigma"]) ** 2
        print(
            f"\nsearch bar     : {family['families']} families of {family['strategies']} "
            f"strategies, sigma {family['sigma']}, bar Sharpe {family['bar']}"
        )
    else:
        bar_n, bar_var = n_trials, 1.0
        print(
            "\nsearch bar     : UNAVAILABLE (no stored strategies); ledger count used, gate will fail"
        )
    rw = search.get("romano_wolf")
    if rw:
        print(
            f"romano-wolf    : {'PASS' if rw['passed'] else 'FAIL'} — candidate {rw['candidate_sharpe']} "
            f"over Nifty vs critical {rw['critical_sharpe']} ({rw['strategies']} strategies, {rw['days']} days)"
        )

    print("\n-- per configuration --")
    print(f"{'configuration':<38}{'IS Sharpe':>11}{'OOS Sharpe':>12}{'DSR':>8}")
    rows_out: list[dict[str, float | str]] = []
    for result in results:
        mean_is = sum(result.in_sample) / len(result.in_sample) if result.in_sample else 0.0
        mean_oos = (
            sum(result.out_of_sample) / len(result.out_of_sample) if result.out_of_sample else 0.0
        )
        stats = sharpe_stats(result.full_returns)
        dsr = deflated_sharpe(stats, n_trials=bar_n, variance_of_sharpes=bar_var)
        print(f"{result.label:<38}{mean_is:>11.2f}{mean_oos:>12.2f}{dsr:>8.3f}")
        rows_out.append(
            {
                "configuration": result.label,
                "mean_is_sharpe": round(mean_is, 4),
                "mean_oos_sharpe": round(mean_oos, 4),
                "full_sample_sharpe": round(stats.sharpe, 4),
                "skew": round(stats.skew, 4),
                "excess_kurtosis": round(stats.kurtosis, 4),
                "deflated_sharpe_probability": round(dsr, 4),
            }
        )

    sharpes = [float(r["full_sample_sharpe"]) for r in rows_out]
    best_sharpe = max(sharpes, default=0.0)
    min_years = min_backtest_length(
        bar_n, target_sharpe=max(best_sharpe, 0.01), variance_of_sharpes=bar_var
    )
    have_years = len(days) / 252

    print("\n-- the battery --")
    print(f"trials ever run       : {n_trials}")
    print(f"PBO                   : {pbo.pbo:.1%} over {pbo.n_paths} paths — {pbo.verdict}")
    print(f"best full-sample SR   : {best_sharpe:.2f}")
    print(f"min backtest length   : {min_years:.1f} years needed; {have_years:.1f} available")
    if min_years > have_years:
        print("  ^ NOT ENOUGH HISTORY for that Sharpe at this trial count")
    for note in notes:
        print(f"  {note}")

    # --- 4b. stress tests: not "is this significant" but "when does it break" ---
    stress_rows: list[dict[str, object]] = []
    if not args.no_stress:
        best_config = max(
            hypothesis.configurations,
            key=lambda c: next(
                (r["full_sample_sharpe"] for r in rows_out if r["configuration"] == _label(c)), 0.0
            ),
        )
        best_strategy, best_rebalance = _strategy_for(best_config)
        print(f"\nstress-testing the strongest configuration: {_label(best_config)}")
        stressed = stress.run_all(rows, best_strategy, rebalance=best_rebalance)
        print(stress.render(stressed))
        stress_rows = [
            {
                "test": r.name,
                "base_sharpe": round(r.base, 4),
                "stressed_sharpe": round(r.stressed, 4),
                "survives": r.survives,
                "detail": r.detail,
            }
            for r in stressed
        ]

    # --- 5. running the battery is itself a trial ---
    entry = ledger.append(
        kind="validation",
        subject=hypothesis.id,
        params={
            "blocks": args.blocks,
            "test_blocks": args.test_blocks,
            "horizon": args.horizon,
            "embargo": args.embargo,
            "n_configurations": len(hypothesis.configurations),
        },
        outcome={
            "pbo": round(pbo.pbo, 4),
            "n_paths": pbo.n_paths,
            "best_full_sample_sharpe": best_sharpe,
            # The canonical key `sharpe_dispersion` reads. Written alongside the
            # original rather than replacing it: the eleven existing entries are
            # hash-chained and cannot be renamed, so both keys must be readable
            # forever and only new rows can carry the canonical one.
            ledger.SHARPE_KEY: best_sharpe,
        },
    )

    # --- 6. evidence pack ---
    pack: dict[str, object] = {
        "hypothesis": hypothesis.id,
        "title": hypothesis.title,
        "claim": hypothesis.claim,
        "red_flags": hypothesis.red_flags,
        "generated_at": datetime.now(UTC).isoformat(),
        "trial_ledger": {"entries": n_trials, "chain": chain.detail},
        "holdout": {
            "starts": hypothesis.holdout.starts.isoformat(),
            "status": hypothesis.holdout.status,
            "rows_withheld": dropped,
        },
        "sample": {"days": len(days), "first": str(days[0]), "last": str(days[-1])},
        "cpcv": {
            "blocks": args.blocks,
            "test_blocks": args.test_blocks,
            "horizon": args.horizon,
            "embargo": args.embargo,
            "paths": pbo.n_paths,
        },
        "configurations": rows_out,
        "search": search,
        "pbo": {"value": round(pbo.pbo, 4), "verdict": pbo.verdict},
        "min_backtest_length_years": round(min_years, 2),
        "available_years": round(have_years, 2),
        "stress_tests": stress_rows,
        "notes": notes,
        "ledger_entry": entry.entry_hash,
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    body = json.dumps(pack, indent=2, sort_keys=True)
    signature = ledger.compute_hash({"body": body})
    out = EVIDENCE / f"{hypothesis.id}.json"
    out.write_text(
        json.dumps({**pack, "signature": signature}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"\nevidence pack  : {out}")
    print(f"signature      : {signature[:32]}...")
    print(f"ledger entry   : #{entry.seq} {entry.entry_hash[:16]}...")

    print(f"\nRED FLAGS declared in {hypothesis.id} before any of this was run:")
    for flag in hypothesis.red_flags:
        print(f"  - {flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
