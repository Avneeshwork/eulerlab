"""The portfolio agent: sizes only what passed the gate, and watches books drift from their backtests.

**Sizing.** A strategy gets a proposed weight only if its hypothesis's latest
gate verdict is PROMOTE (`validation/verdicts.py`) and its card names the
strategy (`strategies:`). Weights are inverse to each strategy's backtest
volatility, capped at `max_weight`, and summed to one. They are proposals in
the operator's inbox; the Deploy dialog is still where capital is set. Today
nothing has passed the gate, and the agent says so rather than sizing anything.

**Drift.** Every active paper or live book is placed against its own
backtest's band (`risk/book.against_backtest`): where the backtest says equity
should be after this many days, 5th to 95th percentile. A book below the band
is flagged with a retirement proposal; the rule to retire was written before
the deployment, so the decision is not made while losing.
"""

from __future__ import annotations

import json
import math
import statistics
from itertools import pairwise
from pathlib import Path
from typing import Any

import yaml

from eulerlab.agents.runtime import Context, Item, WorkerResult

WORKSPACES = Path("data/workspaces")
HYPOTHESES = Path("hypotheses")


def longest_backtest(strategy_id: str) -> list[float]:
    best: list[float] = []
    if "/" in strategy_id or ".." in strategy_id:
        return best
    for path in WORKSPACES.glob(f"*/reports/{strategy_id}/*.json"):
        try:
            values = (json.loads(path.read_text(encoding="utf-8")).get("equity") or {}).get(
                "values"
            ) or []
        except (OSError, json.JSONDecodeError):
            continue
        if len(values) > len(best):
            best = [float(v) for v in values]
    return best


def volatility(values: list[float]) -> float | None:
    rets = [b / a - 1 for a, b in pairwise(values) if a > 0]
    if len(rets) < 60:
        return None
    return statistics.pstdev(rets) * math.sqrt(252)


def weights(vols: dict[str, float], cap: float) -> dict[str, float]:
    """Inverse-volatility weights, capped, renormalised until no weight exceeds the cap."""
    raw = {k: 1 / v for k, v in vols.items() if v > 0}
    if not raw:
        return {}
    fixed: dict[str, float] = {}
    free = dict(raw)
    for _ in range(len(raw)):
        room = 1 - sum(fixed.values())
        total = sum(free.values())
        trial = {k: room * v / total for k, v in free.items()}
        over = {k for k, w in trial.items() if w > cap}
        if not over:
            fixed.update(trial)
            break
        for k in over:
            fixed[k] = cap
            free.pop(k)
        if not free:
            break
    return {k: round(v, 4) for k, v in fixed.items()}


def strategies_of(hypotheses: list[str], directory: Path = HYPOTHESES) -> dict[str, str]:
    out: dict[str, str] = {}
    for hid in hypotheses:
        path = directory / f"{hid}.yaml"
        if not path.exists():
            continue
        spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for sid in spec.get("strategies") or []:
            out[str(sid)] = hid
    return out


def run(ctx: Context) -> WorkerResult:
    from eulerlab.deploy import deployments
    from eulerlab.risk import book as rb
    from eulerlab.validation import verdicts

    items: list[Item] = []
    promoted = verdicts.promoted()
    sized: dict[str, float] = {}
    if not promoted:
        items.append(
            Item(
                kind="finding",
                title="nothing has passed the gate, so nothing is sized",
                body=f"{verdicts.trial_count()} trials in the ledger; no PROMOTE verdict.",
            )
        )
    else:
        linked = strategies_of(promoted)
        vols = {sid: v for sid in linked if (v := volatility(longest_backtest(sid))) is not None}
        sized = weights(vols, float(ctx.options.get("max_weight", 0.4)))
        if sized:
            items.append(
                Item(
                    kind="proposal",
                    title=f"weights for {len(sized)} promoted strateg{'y' if len(sized) == 1 else 'ies'}",
                    body="\n".join(
                        f"{sid} ({linked[sid]}): {w:.0%} (backtest vol {vols[sid]:.1%})"
                        for sid, w in sized.items()
                    ),
                    needs_approval=True,
                    data={"weights": sized},
                )
            )
        else:
            items.append(
                Item(
                    kind="finding",
                    title="promoted hypotheses name no strategy with a stored backtest",
                    body=", ".join(promoted),
                )
            )

    drift: list[dict[str, Any]] = []
    for d in deployments.all_deployments():
        if d.status != "active":
            continue
        state = deployments.read_state(d)
        book = rb.book_from_state(d.id, d.strategy_id, d.strategy_id, d.capital, d.status, state)
        verdict = rb.against_backtest(book, longest_backtest(d.strategy_id))
        drift.append(
            {
                "deployment": d.id,
                "strategy": d.strategy_id,
                "verdict": verdict["verdict"],
                "expected": verdict["expected"],
            }
        )
        if verdict["verdict"] == "below":
            items.append(
                Item(
                    kind="proposal",
                    title=f"retire {d.strategy_id}? it is below its backtest's 5th percentile",
                    body=(
                        f"Deployment {d.id} after {len(book.curve)} sessions is under the band its own backtest "
                        "drew. Approving records that you want it stopped; stopping it is the Stop button on "
                        "Live & Risk."
                    ),
                    severity="warn",
                    needs_approval=True,
                    data={"deployment": d.id},
                )
            )
    return WorkerResult(
        f"{len(promoted)} promoted, {len(sized)} sized; {len(drift)} active books, "
        f"{sum(1 for x in drift if x['verdict'] == 'below')} below their band",
        items,
        data={"promoted": promoted, "weights": sized, "drift": drift},
    )
