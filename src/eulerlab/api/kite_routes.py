"""Kite login from the Instruments page.

Operator, 2026-10-09: "why i am not able to update zerodha minute data and no
button". The minute-bar ingest needs an access token minted the same day, and
the only way to mint one was `make kite-login` in a terminal.

The login itself cannot be automated and is not: Zerodha requires the account
holder to sign in on its own page. What this adds is the two ends of that:

- `GET /api/kite/status` gives the link to Zerodha's login page and says
  whether today's token is held.
- `POST /api/kite/login` takes what the operator pastes back (the redirect URL
  or the bare `request_token`) and exchanges it, exactly as `make kite-login`
  does, through `broker.kite_session`.
- `GET /api/kite/callback` does the same without the paste, for a Kite app
  whose redirect URL is set to `http://localhost:3000/api/kite/callback`.

No route returns the token, the API secret or the key. The status says
"held" or "not held".
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from eulerlab.broker import kite_session

router = APIRouter(prefix="/api/kite")

KEY_ENV, SECRET_ENV = "ZERODHA_API_KEY", "ZERODHA_API_SECRET"


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pasted: str = Field(min_length=1, max_length=2000)
    """The redirect URL Zerodha sent the browser to, or the request_token alone."""


def _credentials() -> tuple[str, str]:
    from eulerlab.env import load_env

    load_env()
    return os.environ.get(KEY_ENV, "").strip(), os.environ.get(SECRET_ENV, "").strip()


@router.get("/status")
def kite_status() -> dict[str, Any]:
    key, secret = _credentials()
    if not key or not secret:
        return {
            "configured": False,
            "fresh": False,
            "reason": f"{KEY_ENV} and {SECRET_ENV} are not both set in .env",
        }
    session = kite_session.load()
    fresh = kite_session.is_fresh(session)
    return {
        "configured": True,
        "fresh": fresh,
        "user": session.user_id if session and fresh else "",
        "expires_at": kite_session.expires_at(session).isoformat() if session and fresh else "",
        "login_url": kite_session.login_url(key),
        "reason": "" if fresh else "no Kite token minted today",
    }


def _exchange(pasted: str) -> dict[str, Any]:
    key, secret = _credentials()
    if not key or not secret:
        return {"ok": False, "error": f"{KEY_ENV} and {SECRET_ENV} are not both set in .env"}
    try:
        token = kite_session.extract_request_token(pasted)
        session = kite_session.exchange(api_key=key, api_secret=secret, request_token=token)
    except kite_session.SessionError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # network, TLS, a malformed reply
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    kite_session.save(session, Path(kite_session.SESSION_FILE))
    return {
        "ok": True,
        "user": session.user_id,
        "expires_at": kite_session.expires_at(session).isoformat(),
    }


@router.post("/login")
def kite_login(request: LoginRequest) -> dict[str, Any]:
    return _exchange(request.pasted)


@router.get("/callback", response_class=HTMLResponse)
def kite_callback(request_token: str = "", status: str = "") -> str:
    """Where Zerodha sends the browser, if the Kite app's redirect URL points here."""
    if not request_token:
        body = f"No request_token in the address. Zerodha said: {status or 'nothing'}."
    else:
        outcome = _exchange(request_token)
        body = (
            f"Logged in to Kite as {outcome['user']}. You can close this tab."
            if outcome["ok"]
            else f"Kite login failed: {outcome['error']}"
        )
    import html

    return (
        "<!doctype html><meta charset=utf-8><title>Kite login</title>"
        f"<p style='font:16px system-ui;margin:3rem'>{html.escape(body)}</p>"
    )
