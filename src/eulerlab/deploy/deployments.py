"""A deployment: one strategy, trading forward, with its own money and records.

Operator, 2026-10-07: "build full paper trading infra mimicking live trading
and deploy first". ADR-060, research 069.

Each deployment is a directory under `data/deployments/<id>/` holding
everything it needs and nothing another deployment can touch:

- `deployment.json` — what was deployed, with how much, from when
- `orders.jsonl` — the OMS journal (append-only, fsynced)
- `paper_broker.json` — the simulated broker's own state, kept apart from the
  journal so reconciliation compares two records rather than one
- `KILL_SWITCH` — this deployment's switch; tripping it stops only this one
- `state.json` — the latest run's book, written by `runner.run`

A paper deployment and a live one differ only in the broker adapter. Live is
not enabled: the Kite adapter has never been run against the real API
(T-3336), and the operator has not yet set the live safety limits.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path("data/deployments")

Mode = Literal["paper", "live"]
Status = Literal["active", "stopped", "halted"]


class Deployment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    strategy_id: str
    mode: Mode
    capital: float = Field(gt=0)
    start: date
    """The first decision day: the latest panel day when it was deployed."""
    created_at: str
    status: Status = "active"
    status_reason: str = ""
    # ASSUMPTION: A-048 — 5 bps adverse slippage stands in for a live fill near the close.
    slippage_bps: float = Field(default=5.0, ge=0)
    """Adverse slippage on every paper fill. A live order
    near the close does not get exactly the closing price (A-048)."""
    flows: list[dict[str, Any]] = Field(default_factory=list)
    """Dated external cash flows. Positive amounts are deposits."""
    reducing: list[dict[str, Any]] = Field(default_factory=list)
    """Reduce-only windows, `{from, to, why, by}`: buys filled inside one are
    refused, sells go through (ADR-092, `deploy/loss_limits.py`)."""
    reduce_at: float | None = Field(default=None, gt=0, lt=1)
    """This deployment's own reduce-only drawdown, else config/loss_limits.yaml."""
    halt_at: float | None = Field(default=None, gt=0, lt=1)
    """This deployment's own halt drawdown, else config/loss_limits.yaml."""

    @property
    def folder(self) -> Path:
        return ROOT / self.id


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomic: a crash mid-write leaves the previous file whole."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, default=str)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def save(deployment: Deployment) -> None:
    _write_json(deployment.folder / "deployment.json", deployment.model_dump(mode="json"))


def create(strategy_id: str, *, mode: Mode, capital: float, start: date) -> Deployment:
    now = datetime.now(UTC).isoformat(timespec="seconds")
    digest = hashlib.sha256(f"{strategy_id}|{mode}|{capital}|{now}".encode()).hexdigest()[:6]
    deployment = Deployment(
        id=f"{mode}-{strategy_id}-{start.isoformat()}-{digest}",
        strategy_id=strategy_id,
        mode=mode,
        capital=capital,
        start=start,
        created_at=now,
    )
    save(deployment)
    return deployment


def load(deployment_id: str) -> Deployment:
    path = ROOT / deployment_id / "deployment.json"
    return Deployment.model_validate_json(path.read_text(encoding="utf-8"))


def all_deployments() -> list[Deployment]:
    if not ROOT.exists():
        return []
    out = []
    for path in sorted(ROOT.glob("*/deployment.json")):
        out.append(Deployment.model_validate_json(path.read_text(encoding="utf-8")))
    return sorted(out, key=lambda d: d.created_at, reverse=True)


def set_status(deployment: Deployment, status: Status, reason: str = "") -> Deployment:
    updated = deployment.model_copy(update={"status": status, "status_reason": reason})
    save(updated)
    return updated


def read_state(deployment: Deployment) -> dict[str, Any] | None:
    path = deployment.folder / "state.json"
    if not path.exists():
        return None
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def write_state(deployment: Deployment, state: dict[str, Any]) -> None:
    _write_json(deployment.folder / "state.json", state)


def write_fills(deployment: Deployment, fills: list[dict[str, Any]]) -> None:
    """Every fill, beside the state's last 200, for the deployment's report."""
    _write_json(deployment.folder / "fills.json", {"fills": fills})


def read_fills(deployment: Deployment) -> list[dict[str, Any]] | None:
    """Every fill, or None for a deployment last run before this file existed."""
    path = deployment.folder / "fills.json"
    if not path.exists():
        return None
    fills: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))["fills"]
    return fills
