"""`make gate-acceptance` — Sprint 14's acceptance test.

*Deliberately feed it 3 overfit strategies; all must be killed.*

Each is run through the **real** battery — purged CPCV, PBO, Deflated Sharpe,
stress tests — and the resulting evidence is put through the **real** gate. No
hand-written evidence packs: a gate tested against fixtures I wrote is a gate
tested against my own assumptions, which is how Sprint 12's self-tests ended up
with a hole in them.

It is deliberately smaller than a full validation run — fewer CPCV paths and
the most liquid names only — because the question is whether the gate refuses
these, not what their exact Sharpe is. Restricting to liquid names also makes
the test *harder*: microcaps are where spurious results live.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass

from eulerlab import gates
from eulerlab.backtest.strategy import Strategy
from eulerlab.backtest.vector import build_adjusted_index
from eulerlab.features.panel import PanelRow, read_panel, trading_days
from eulerlab.validation import overfit, stress
from eulerlab.validation.cpcv import cpcv_splits, leakage_check
from eulerlab.validation.ledger import count as trial_count
from eulerlab.validation.statistics import (
    deflated_sharpe,
    min_backtest_length,
    probability_of_backtest_overfitting,
    sharpe_stats,
)


@dataclass
class Outcome:
    strategy: str
    verdict: gates.Verdict
    failed: list[str]


def _evidence(
    rows: Sequence[PanelRow], strategy: Strategy, *, blocks: int, n_trials: int
) -> dict[str, object]:
    """Run the real battery and shape the result like a validation pack."""
    from eulerlab.backtest import event_driven

    days = trading_days(rows)
    index = build_adjusted_index(rows)
    by_day: dict[object, list[PanelRow]] = {d: [] for d in days}
    for row in rows:
        by_day[row.day].append(row)

    in_sample: list[list[float]] = []
    out_sample: list[list[float]] = []
    for split_ in cpcv_splits(days, n_blocks=blocks, test_block_count=2, horizon=21, embargo=5):
        if leakage_check(split_, days, horizon=21):
            continue
        train = [r for d in split_.train_days for r in by_day[d]]
        test = [r for d in split_.test_days for r in by_day[d]]
        # Two configurations so PBO has something to choose between: the
        # strategy itself, and a lower-turnover variant of it.
        scores_is, scores_oos = [], []
        for rebalance in (21, 63):
            scores_is.append(
                sharpe_stats(
                    event_driven.run(train, strategy, rebalance_every=rebalance).daily_returns()
                ).sharpe
            )
            scores_oos.append(
                sharpe_stats(
                    event_driven.run(test, strategy, rebalance_every=rebalance).daily_returns()
                ).sharpe
            )
        in_sample.append(scores_is)
        out_sample.append(scores_oos)

    pbo = probability_of_backtest_overfitting(in_sample, out_sample)
    full = event_driven.run(rows, strategy, rebalance_every=21, adjusted_index=index)
    stats = sharpe_stats(full.daily_returns())
    dsr = deflated_sharpe(stats, n_trials=n_trials)
    stressed = stress.run_all(rows, strategy, rebalance=21)
    needed = min_backtest_length(n_trials, target_sharpe=max(stats.sharpe, 0.01))

    pack: dict[str, object] = {
        "hypothesis": strategy.describe(),
        "configurations": [
            {
                "configuration": strategy.describe(),
                "full_sample_sharpe": round(stats.sharpe, 4),
                "deflated_sharpe_probability": round(dsr, 4),
            }
        ],
        "pbo": {"value": round(pbo.pbo, 4), "verdict": pbo.verdict},
        "min_backtest_length_years": round(needed, 2),
        "available_years": round(len(days) / 252, 2),
        "stress_tests": [
            {
                "test": r.name,
                "base_sharpe": round(r.base, 4),
                "stressed_sharpe": round(r.stressed, 4),
                "survives": r.survives,
                "detail": r.detail,
            }
            for r in stressed
        ],
    }
    return pack


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gate-acceptance", description=__doc__)
    parser.add_argument("--blocks", type=int, default=4)
    parser.add_argument("--symbols", type=int, default=400)
    args = parser.parse_args(argv)

    rows = read_panel()
    if not rows:
        print("no panel. Run `make build-panel` first.")
        return 2
    rows = overfit.shrink(rows, symbols=args.symbols)
    days = trading_days(rows)
    print(f"universe: {args.symbols} most liquid names, {len(days):,} days")
    print(f"{len(overfit.CATALOGUE)} deliberately overfit strategies; all must be KILLED\n")

    n_trials = trial_count()
    mandate = gates.load_mandate()
    outcomes: list[Outcome] = []

    for strategy in overfit.CATALOGUE:
        print(f"--- {strategy.describe()} ---")
        pack = _evidence(rows, strategy, blocks=args.blocks, n_trials=n_trials)
        # Process rules concern registration and signing, which a synthetic
        # candidate has no meaningful version of. The statistical and
        # robustness rules are the ones under test here.
        decision = gates.Decision(hypothesis=str(pack["hypothesis"]))
        decision.findings.extend(gates._check_statistics(pack, mandate["statistical"]))
        decision.findings.extend(gates._check_robustness(pack, mandate["robustness"]))
        print(decision.render())
        outcomes.append(
            Outcome(strategy.describe(), decision.verdict, [f.rule for f in decision.failures])
        )
        print()

    survived = [o for o in outcomes if o.verdict is gates.Verdict.PROMOTE]
    print("=" * 66)
    for o in outcomes:
        mark = "KILLED" if o.verdict is gates.Verdict.KILL else "*** SURVIVED ***"
        print(f"  {mark:<18} {o.strategy}")
    print()
    if survived:
        print(
            f"ACCEPTANCE FAILED: {len(survived)} overfit strateg(ies) passed the gate.\n"
            "The gate certifies a kind of overfitting it cannot see, which is worse\n"
            "than having no gate. Do not promote anything until this is red no more."
        )
        return 1
    print(f"ACCEPTANCE PASSED: all {len(outcomes)} overfit strategies were killed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
