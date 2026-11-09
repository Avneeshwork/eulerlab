"""Real money from the workbench: H-0194 on Angel One (ADR-162, `deploy/live_money.py`).

    GET  /api/live-money          the deploy, today's picks, orders, P&L, the kill switch
    POST /api/live-money/preview  sizing for an amount and leverage; sends nothing
    POST /api/live-money/funds    Angel's available cash (logs in; read-only)
    POST /api/live-money/dry-run  today's picks on live quotes; sends nothing
    POST /api/live-money/deploy   arm the next session; needs confirm == "DEPLOY"
    POST /api/live-money/stop     disarm before the entry; nothing open is touched
    POST /api/live-money/kill     trip the kill switch, close today's positions, disarm

Clearing a tripped kill switch is deliberately not here: it needs the separate
`KILLSWITCH_TOKEN` (CLAUDE.md: kill switches have separate credentials), so a
button on the same screen that sends orders cannot undo it.
"""

from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from eulerlab.deploy import live_money as lm

router = APIRouter(prefix="/api/live-money")
_DRY = threading.Lock()


class SizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capital: float = Field(gt=0, allow_inf_nan=False)
    leverage: float = Field(default=1.0, ge=1.0, le=lm.MAX_LEVERAGE)
    loss_cap: float = Field(gt=0, allow_inf_nan=False)


class DeployRequest(SizeRequest):
    confirm: str = ""


class KillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="operator pressed Kill on the workbench", max_length=200)


def _settings(body: SizeRequest) -> lm.Settings:
    return lm.Settings(capital=body.capital, leverage=body.leverage, loss_cap=body.loss_cap)


@router.get("")
def live_status() -> dict[str, Any]:
    return lm.status()


@router.post("/preview")
def preview(body: SizeRequest) -> dict[str, Any]:
    sized = lm.size(_settings(body))
    return {
        "exposure": sized.exposure,
        "names": sized.names,
        "per_name": sized.per_name,
        "refused": sized.refused,
        "notes": list(sized.notes),
        "for_session": lm.next_session(lm.now_ist()).isoformat(),
    }


@router.post("/funds")
def funds() -> dict[str, Any]:
    try:
        return {"available": lm.AngelDesk().funds()}
    except Exception as exc:
        raise HTTPException(502, f"Angel One: {type(exc).__name__}: {exc}") from exc


@router.post("/dry-run")
def dry_run(body: SizeRequest) -> dict[str, Any]:
    if not _DRY.acquire(blocking=False):
        raise HTTPException(409, "a dry run is already running")
    try:
        return lm.dry_run(_settings(body))
    finally:
        _DRY.release()


@router.post("/deploy")
def deploy(body: DeployRequest) -> dict[str, Any]:
    result = lm.arm(_settings(body), body.confirm)
    if result.get("status") != "armed":
        raise HTTPException(400, result.get("why", "refused"))
    lm.CLOCK.start()
    return result


@router.post("/stop")
def stop() -> dict[str, Any]:
    return lm.disarm("operator pressed Stop on the workbench")


@router.post("/kill")
def kill(body: KillRequest) -> dict[str, Any]:
    return lm.kill(body.reason)
