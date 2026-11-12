"""`/api/auth`: log in, log out, and who am I (ADR-168)."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from eulerlab import accounts
from eulerlab.accounts import store
from eulerlab.accounts.middleware import COOKIE

router = APIRouter(prefix="/api/auth")


class Login(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(body: Login, request: Request, response: Response) -> dict[str, Any]:
    if not accounts.enabled():
        return {"auth": "off", "principal": accounts.current().__dict__}
    try:
        address = request.client.host if request.client else ""
        token = store.login(body.email, body.password, address=address)
        principal = store.from_session(token, None)
    except store.AccessDenied as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    response.set_cookie(
        COOKIE,
        token,
        max_age=store.SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        # Behind HTTPS on a server, set EULERLAB_COOKIE_SECURE=1.
        secure=os.environ.get("EULERLAB_COOKIE_SECURE", "") == "1",
    )
    return {"auth": "on", "principal": principal.__dict__}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict[str, str]:
    token = request.cookies.get(COOKIE, "")
    if token and accounts.enabled():
        store.logout(token)
    response.delete_cookie(COOKIE)
    return {"status": "logged out"}


@router.get("/me")
def me() -> dict[str, Any]:
    return {
        "auth": "on" if accounts.enabled() else "off",
        "principal": accounts.current().__dict__,
    }


# --- the workspace's gate (ADR-169) -------------------------------------------------------------

gate_router = APIRouter()


class GateRules(BaseModel):
    rules: dict[str, float]


@gate_router.get("/api/gate/rules")
def gate_rules() -> dict[str, Any]:
    """What this workspace is held to, and which thresholds it may tighten."""
    from eulerlab import gates
    from eulerlab.accounts import gate

    base = gates.load_mandate()
    floors = {key: gate._at(base, key)[0][gate._at(base, key)[1]] for key in gate.TIGHTENABLE}
    return {
        "workspace": accounts.current().workspace_id,
        "own": gate.own_rules(),
        "platform": floors,
        "stricter_is": gate.TIGHTENABLE,
    }


@gate_router.post("/api/accounts/gate")
def set_gate_rules(body: GateRules) -> dict[str, Any]:
    """Owner only (`/api/accounts`). Stricter than the platform, or refused."""
    from eulerlab.accounts import gate

    try:
        version = gate.set_rules(body.rules)
    except gate.Looser as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"version": version, "own": gate.own_rules()}


# --- the workspace's own keys (ADR-170) ----------------------------------------------------------


class Secret(BaseModel):
    name: str
    value: str


@gate_router.get("/api/accounts/secrets")
def secret_names() -> dict[str, Any]:
    """Owner only. Which keys are set; never a value."""
    from eulerlab.accounts import secrets

    return {"workspace": accounts.current().workspace_id, "names": secrets.names()}


@gate_router.post("/api/accounts/secrets")
def set_secret(body: Secret) -> dict[str, Any]:
    from eulerlab.accounts import secrets

    try:
        secrets.put(body.name, body.value)
    except (ValueError, secrets.NoSecretKey) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"names": secrets.names()}
