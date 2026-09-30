"""The batch runner: many configurations, one engine, one cost path.

It calls the same `event_driven.run` / `vector.run` that `make backtest` uses.
There is deliberately no batch-specific engine, because a second path to a
number is a second answer — the rule the whole project is built on.

Sequential by default. The obvious move is a process pool, and it is the wrong
first move: the panel is 540 MB, so N processes means N copies of it, and the
measured cost of a Tier B run on the real panel is ~16s of which the loop
dominates. Parallelism here needs shared memory to be worth anything, and
shared memory needs the panel in a format that supports it. Recorded rather
than guessed at (T-3319).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from eulerlab.batch import CACHE_DIR, Batch, Item, Outcome, read_cached, write_cached

Compute = Callable[[Item], dict[str, object]]
"""How to evaluate one item. Injected so the runner can be tested without a
panel, and so the API can pass its own already-cached engine."""


def run(
    items: Sequence[Item],
    compute: Compute,
    *,
    use_cache: bool = True,
    cache_dir: Path | None = None,
    on_progress: Callable[[int, int, Item], None] | None = None,
) -> Batch:
    """Evaluate every item, serving what it can from cache.

    `cache_dir` is an explicit parameter resolved at call time, not a default
    argument bound at import. The difference is not cosmetic: a module-level
    default cannot be redirected afterwards, which makes the location
    untestable and forecloses a per-workspace cache — the same defect the
    ledger's `LEDGER_PATH` default has.

    A failure is recorded against its item and the run continues. One bad
    configuration in a batch of fifty should not cost the other forty-nine —
    the same reasoning as the universe scan, where a delisted symbol must not
    kill the run.
    """
    directory = cache_dir if cache_dir is not None else CACHE_DIR
    batch = Batch()
    total = len(items)

    for index, item in enumerate(items, start=1):
        key = item.key()
        cached = read_cached(key, directory=directory) if use_cache else None

        if cached is not None:
            batch.outcomes.append(Outcome(item=item, cached=True, result=cached))
        else:
            try:
                result = compute(item)
            except Exception as exc:
                batch.outcomes.append(
                    Outcome(item=item, cached=False, error=f"{type(exc).__name__}: {exc}")
                )
            else:
                if use_cache:
                    write_cached(key, result, directory=directory)
                batch.outcomes.append(Outcome(item=item, cached=False, result=result))

        if on_progress:
            on_progress(index, total, item)

    return batch


def summarise(batch: Batch) -> dict[str, object]:
    """What the console needs, including what it would rather not say.

    `unrecorded` is the number that matters and the one a friendlier summary
    would omit: configurations evaluated here that the trial ledger will never
    know about. Reporting it does not close the gap, but an unreported gap is
    the one that gets forgotten.
    """
    return {
        "total": len(batch.outcomes),
        "cached": batch.cached,
        "computed": batch.computed,
        "failed": batch.failed,
        "unrecorded": batch.unrecorded,
        "spent_trials": 0,
        "note": (
            f"{batch.computed} configuration(s) were evaluated and none of them appears in "
            f"the trial ledger. Screening here is free, which is the point — and it is also "
            f"search that the noise bar does not know you performed."
            if batch.computed
            else "Every configuration was served from cache. Nothing new was evaluated."
        ),
        "results": [
            {
                "strategy": o.item.strategy_id,
                "params": o.item.params,
                "cached": o.cached,
                "error": o.error,
                **({} if o.error else {"result": o.result}),
            }
            for o in batch.outcomes
        ],
    }
