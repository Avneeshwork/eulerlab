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
def login(body: Login, response: Response) -> dict[str, Any]:
    if not accounts.enabled():
        return {"auth": "off", "principal": accounts.current().__dict__}
    try:
        token = store.login(body.email, body.password)
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
