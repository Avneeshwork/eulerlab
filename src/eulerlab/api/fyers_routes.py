"""FYERS's daily login flow from the Instruments page.

The account holder signs in on FYERS. The browser returns an auth-code URL;
this API validates the one-time state and exchanges the code locally. Neither
the app secret nor the access token is returned to the browser.
"""

from __future__ import annotations

import html
import json
import os
import secrets
import tempfile
import threading
import urllib.parse
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from eulerlab.ingest.fyers_expired_fo import (
    FyersAPIError,
    auth_url,
    exchange_auth_code,
    token_status,
)
from eulerlab.paths import data_path

router = APIRouter(prefix="/api/fyers")
STATE_PATH = data_path("cache/fyers_login_state.json")
STATE_TTL = timedelta(minutes=15)
STATE_LOCK = threading.Lock()


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pasted: str = Field(min_length=1, max_length=4000)


def _read_state() -> tuple[str, datetime] | None:
    try:
        row = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        state = row.get("state")
        expires_at = datetime.fromisoformat(row.get("expires_at", ""))
        if isinstance(state, str) and state and datetime.now(UTC) < expires_at:
            return state, expires_at
    except (OSError, TypeError, ValueError, AttributeError, json.JSONDecodeError):
        pass
    return None


def _write_state() -> tuple[str, datetime]:
    state = secrets.token_urlsafe(24)
    expires_at = datetime.now(UTC) + STATE_TTL
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(dir=STATE_PATH.parent, suffix=".part")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(
                json.dumps({"state": state, "expires_at": expires_at.isoformat()}, sort_keys=True)
                + "\n"
            )
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, STATE_PATH)
    finally:
        temporary.unlink(missing_ok=True)
    return state, expires_at


def _login_state() -> str:
    with STATE_LOCK:
        current = _read_state()
        return current[0] if current else _write_state()[0]


def _callback_values(pasted: str) -> tuple[str, str]:
    text = pasted.strip()
    query = urllib.parse.urlparse(text).query
    values = urllib.parse.parse_qs(query or text.lstrip("?"))
    auth_code = next(iter(values.get("auth_code", [])), "")
    state = next(iter(values.get("state", [])), "")
    if not auth_code or not state:
        raise FyersAPIError("Paste the full FYERS redirect address with auth_code and state.")
    return auth_code, state


def _complete(pasted: str) -> dict[str, Any]:
    try:
        auth_code, returned_state = _callback_values(pasted)
        expected = _read_state()
        if expected is None or returned_state != expected[0]:
            raise FyersAPIError("FYERS login state expired or did not match; start login again.")
        STATE_PATH.unlink(missing_ok=True)
        session = exchange_auth_code(auth_code)
    except FyersAPIError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    return {"ok": True, **session}


@router.get("/status")
def fyers_status() -> dict[str, Any]:
    status = token_status()
    if not status["configured"]:
        return status
    if not status["fresh"]:
        try:
            status["login_url"] = auth_url(_login_state())
        except FyersAPIError as exc:
            status["configured"] = False
            status["reason"] = str(exc)
    return status


@router.post("/login")
def fyers_login(request: LoginRequest) -> dict[str, Any]:
    return _complete(request.pasted)


@router.get("/callback", response_class=HTMLResponse)
def fyers_callback(auth_code: str = "", state: str = "", error: str = "") -> str:
    """Complete login automatically when the app redirects to this endpoint."""
    if error:
        body = f"FYERS login failed: {error}"
    elif not auth_code or not state:
        body = "No auth_code or state in the redirect address."
    else:
        outcome = _complete(urllib.parse.urlencode({"auth_code": auth_code, "state": state}))
        body = (
            f"Logged in to FYERS as {outcome.get('user', 'user')}. You can close this tab."
            if outcome.get("ok")
            else f"FYERS login failed: {outcome.get('error', 'unknown error')}"
        )
    return (
        "<!doctype html><meta charset=utf-8><title>FYERS login</title>"
        f"<p style='font:16px system-ui;margin:3rem'>{html.escape(body)}</p>"
    )
