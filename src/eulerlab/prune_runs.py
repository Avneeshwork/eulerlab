"""`make prune-runs` — one stored run per strategy, without losing the denominator.

A strategy accumulated a run for every backtest anyone ever pointed at it: an
old NSE screen, a 500-day custom window, the adopted result. The library then
had to choose between them and the report dialog offered a picker, which asked
the reader to know which of three numbers was the strategy.

This keeps the **last** run — the strategy on the parameters it actually uses —
and drops the rest.

There is deliberately no notion of a "best version" of a strategy here. A best
of N stored runs is a maximum over N draws and a biased estimator of any one of
them, which is the argument `results.latest` makes for showing the most recent.
Where a strategy performs best is a separate question about *markets*, answered
by a tag derived at read time from the runs themselves — never by promoting one
stored run over its siblings.

### What is dropped and what is not

The superseded runs' **payloads** go: their curves, their reports, the rows in
`results/<strategy>.jsonl`. Those are storage and clutter.

The **count** does not go. `Best.runs` is the denominator of the selection-bias
correction — "Sharpe 2.19 as the only run means one thing, as the highest of
forty another" — and quietly dropping thirty-nine of forty would make every
surviving result look better attested than it is. That is the one direction
this repository never rounds in.

So each kept run carries `superseded`, the number of configurations it stands
in for, and `distinct()` reports the sum. Deleting the rows changes what is on
disk and not what the statistics believe.

### Why the adopted run rather than the highest Sharpe

The adopted run is not a maximum over stored runs — it is the one configuration
the strategy is defined to use, chosen by a sweep whose cost the trial ledger
already carries. Keeping it is not the same act as keeping whichever run
happened to score highest, and the difference is the whole reason this is safe
to do at all.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def prune(*, dry_run: bool = True) -> dict[str, tuple[int, int]]:
    """Keep one run per strategy. Returns {strategy: (kept, dropped)}."""
    from eulerlab import results as result_store
    from eulerlab import workspace as workspace_mod
    from eulerlab.strategies import REGISTRY

    tenant = workspace_mod.resolve(None)
    outcome: dict[str, tuple[int, int]] = {}

    for strategy_id in sorted(REGISTRY):
        runs = result_store.distinct(tenant, strategy_id)
        if len(runs) < 2:
            continue

        keeper = _keeper(runs)
        if keeper is None:
            continue
        dropped = [r for r in runs if r.configuration != keeper.configuration]
        outcome[strategy_id] = (1, len(dropped))
        if dry_run:
            continue

        _rewrite(tenant, strategy_id, keeper, superseded=len(dropped))
        _drop_reports(tenant, strategy_id, keep=keeper.configuration)

    return outcome


def _keeper(runs: Sequence[Any]) -> Any | None:
    """The run to keep: the adopted one, else the most recent that traded.

    **Never the highest Sharpe.** A maximum over stored runs is a biased
    estimator of any one of them, and picking one here would smuggle that bias
    into storage, where nothing downstream could see it or correct for it.
    """
    adopted = [r for r in runs if r.universe == "adopted"]
    if adopted:
        return max(adopted, key=lambda r: r.at)
    traded = [r for r in runs if r.fills > 0]
    return max(traded, key=lambda r: r.at) if traded else None


def _rewrite(tenant: Any, strategy_id: str, keeper: Any, *, superseded: int) -> None:
    """Replace the log with one row, carrying the count it stands in for."""
    path = Path(tenant.results) / f"{strategy_id}.jsonl"
    row = keeper.to_row()
    # Written into the row rather than tracked elsewhere, so a file that is
    # copied or inspected on its own still says how many runs it represents.
    row["superseded"] = int(row.get("superseded") or 0) + superseded
    path.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")


def _drop_reports(tenant: Any, strategy_id: str, *, keep: str) -> None:
    """Delete report payloads for configurations no longer stored."""
    folder = Path(tenant.root) / "reports" / strategy_id
    if not folder.exists():
        return
    for report in folder.iterdir():
        if report.is_file() and report.stem != keep:
            report.unlink()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="prune-runs")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually rewrite; without it nothing is touched",
    )
    args = parser.parse_args(argv)

    outcome = prune(dry_run=not args.apply)
    if not outcome:
        print("nothing to prune — every strategy already has one stored run")
        return 0

    total = sum(dropped for _, dropped in outcome.values())
    for strategy_id, (kept, dropped) in sorted(outcome.items()):
        print(f"{strategy_id:24s} keep {kept}, drop {dropped}")
    print("-" * 48)
    verb = "dropped" if args.apply else "would drop"
    print(f"{verb} {total} superseded runs across {len(outcome)} strategies")
    print("the count each keeper stands in for is preserved, so the bias denominator is unchanged")
    if not args.apply:
        print("\nnothing was written. re-run with --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
