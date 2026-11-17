"""Loss limits that act: reduce-only, then halt (ADR-092).

Research 079 named two gaps that matter before live capital: a deployment in
trouble could not be told to only close positions, and nothing stopped a
strategy on a loss. This module closes both.

After every run, `apply` measures the deployment's drawdown from its own
highest point on the time-weighted curve (`risk.book.growth`, so a withdrawal
is not a loss) and compares it with `config/loss_limits.yaml`:

    drawdown >= halt_at    trip the deployment's kill switch; status halted
    drawdown >= reduce_at  open a reduce-only window from the next session

A reduce-only window is a dated record on the deployment, `reducing`:
`{"from": day, "to": day | null, "why": ..., "by": ...}`. The runner replays
history every day, so the refusal has to be the same on every replay: a buy
filled on a day inside a window is refused, a day outside is not. Resuming
closes the window at the last traded day rather than deleting it, so the days
already traded reduce-only replay as they were traded.

Only the daily rebalancing book (`deploy.runner._run`) enforces reduce-only;
the overnight, intraday and study books run their own order loops and get the
halt but not the reduce step (S-050).
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from eulerlab.deploy import deployments as store
from eulerlab.deploy.deployments import Deployment

CONFIG = Path("config/loss_limits.yaml")


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reduce_at: float | None = Field(default=None, gt=0, lt=1)
    halt_at: float | None = Field(default=None, gt=0, lt=1)


def load(path: Path | None = None) -> Limits:
    path = path or CONFIG
    if not path.exists():
        return Limits()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Limits.model_validate(raw)


def for_deployment(deployment: Deployment, defaults: Limits | None = None) -> Limits:
    """The deployment's own levels where it has them, the defaults otherwise."""
    base = defaults or load()
    return Limits(
        reduce_at=deployment.reduce_at if deployment.reduce_at is not None else base.reduce_at,
        halt_at=deployment.halt_at if deployment.halt_at is not None else base.halt_at,
    )


def drawdown(state: dict[str, Any], capital: float) -> tuple[float, float]:
    """(current drawdown, worst drawdown) from the time-weighted curve, as positive shares."""
    from eulerlab.risk.book import growth

    curve = [(date.fromisoformat(str(d)), float(v)) for d, v in state.get("curve") or []]
    flows = [
        (date.fromisoformat(str(f["applied_day"])), float(f["amount"]))
        for f in state.get("flows") or []
        if f.get("applied_day") and isinstance(f.get("amount"), int | float)
    ]
    path = growth(curve, flows, capital)
    peak, worst, now = 0.0, 0.0, 0.0
    for _, value in path:
        peak = max(peak, value)
        now = 1.0 - value / peak if peak > 0 else 0.0
        worst = max(worst, now)
    return now, worst


def reducing_on(deployment: Deployment, day: date) -> bool:
    """Is a buy filled on `day` refused? True inside any reduce-only window."""
    for window in deployment.reducing:
        start = date.fromisoformat(str(window["from"]))
        end = date.fromisoformat(str(window["to"])) if window.get("to") else None
        if day >= start and (end is None or day <= end):
            return True
    return False


def is_reducing(deployment: Deployment) -> bool:
    """An open window: reduce-only now and from here on."""
    return any(not window.get("to") for window in deployment.reducing)


def start_reducing(deployment: Deployment, after: date, why: str, by: str) -> Deployment:
    """Open a window from the day after `after`, the last day already traded."""
    if is_reducing(deployment):
        return deployment
    window = {"from": (after + timedelta(days=1)).isoformat(), "to": None, "why": why, "by": by}
    updated = deployment.model_copy(update={"reducing": [*deployment.reducing, window]})
    store.save(updated)
    return updated


def stop_reducing(deployment: Deployment, through: date, by: str) -> Deployment:
    """Close the open window at `through`, the last day already traded."""
    windows = []
    for window in deployment.reducing:
        if not window.get("to"):
            start = date.fromisoformat(str(window["from"]))
            if through < start:
                continue  # never took effect: nothing was traded inside it
            window = {**window, "to": through.isoformat(), "resumed_by": by}
        windows.append(window)
    updated = deployment.model_copy(update={"reducing": windows})
    store.save(updated)
    return updated


def apply(deployment: Deployment, state: dict[str, Any]) -> tuple[Deployment, dict[str, Any]]:
    """Measure the drawdown, act on it, and record what was seen in the state."""
    if state.get("status") != "ok":
        return deployment, state
    limits = for_deployment(deployment)
    now, worst = drawdown(state, deployment.capital)
    traded = state.get("traded_through") or state.get("as_of")
    action = ""
    if limits.halt_at is not None and now >= limits.halt_at:
        reason = (
            f"loss limit: down {now:.1%} from its high, past the halt level of "
            f"{limits.halt_at:.0%} (Live & Risk, loss limits)"
        )
        _trip(deployment, reason)
        deployment = store.set_status(deployment, "halted", reason)
        state = {**state, "status": "halted", "reason": reason}
        action = "halted"
    elif (
        limits.reduce_at is not None
        and now >= limits.reduce_at
        and not is_reducing(deployment)
        and traded
    ):
        why = f"down {now:.1%} from its high, past the reduce-only level of {limits.reduce_at:.0%}"
        deployment = start_reducing(deployment, date.fromisoformat(str(traded)), why, "loss limit")
        action = "reducing"
        state.setdefault("warnings", []).append(
            f"reduce-only from the next session: {why}. Sells go through; buys are refused "
            f"until you resume it on Live & Risk."
        )
    state = {
        **state,
        "loss_limit": {
            "drawdown": round(now, 4),
            "worst": round(worst, 4),
            "reduce_at": limits.reduce_at,
            "halt_at": limits.halt_at,
            "reducing": is_reducing(deployment),
            "action": action,
        },
    }
    store.write_state(deployment, state)
    return deployment, state


def _trip(deployment: Deployment, reason: str) -> None:
    from eulerlab.oms.killswitch import KillSwitch

    folder = deployment.folder
    folder.mkdir(parents=True, exist_ok=True)
    KillSwitch(folder / "KILL_SWITCH", folder / "killswitch_log.jsonl").trip(
        reason, by="deploy.loss_limits"
    )


__all__ = [
    "CONFIG",
    "Limits",
    "apply",
    "drawdown",
    "for_deployment",
    "is_reducing",
    "load",
    "reducing_on",
    "start_reducing",
    "stop_reducing",
]
