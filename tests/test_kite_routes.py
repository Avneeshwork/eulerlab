"""Kite login from the Instruments page: what the routes say, and what they never say."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from eulerlab.api import kite_routes
from eulerlab.broker import kite_session

SECRET = "api-secret-never-shown"
TOKEN = "access-token-never-shown"


@pytest.fixture
def _configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(kite_routes.KEY_ENV, "the-key")
    monkeypatch.setenv(kite_routes.SECRET_ENV, SECRET)
    monkeypatch.setattr("eulerlab.env.load_env", lambda path=None: {})
    session_file = tmp_path / ".kite_session.json"
    monkeypatch.setattr(kite_session, "SESSION_FILE", session_file)
    real_load = kite_session.load
    monkeypatch.setattr(kite_session, "load", lambda path=session_file: real_load(session_file))
    return session_file


def _session() -> kite_session.Session:
    fields = kite_session.Session.__dataclass_fields__
    values: dict[str, object] = {"access_token": TOKEN, "user_id": "AB1234"}
    for name in fields:
        if name not in values:
            values[name] = datetime.now(UTC).isoformat()
    return kite_session.Session(**values)  # type: ignore[arg-type]


def test_without_credentials_the_status_says_which_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(kite_routes.KEY_ENV, raising=False)
    monkeypatch.delenv(kite_routes.SECRET_ENV, raising=False)
    monkeypatch.setattr("eulerlab.env.load_env", lambda path=None: {})
    status = kite_routes.kite_status()
    assert status["configured"] is False and status["fresh"] is False
    assert kite_routes.KEY_ENV in status["reason"]
    assert kite_routes.kite_login(kite_routes.LoginRequest(pasted="x"))["ok"] is False


@pytest.mark.usefixtures("_configured")
def test_not_logged_in_gives_the_login_link_and_no_secret() -> None:
    status = kite_routes.kite_status()
    assert status["configured"] and not status["fresh"]
    assert status["login_url"] == kite_session.login_url("the-key")
    assert SECRET not in json.dumps(status)


def test_a_login_saves_the_session_and_returns_neither_token_nor_secret(
    _configured: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, str] = {}

    def exchange(*, api_key: str, api_secret: str, request_token: str) -> kite_session.Session:
        seen.update(key=api_key, secret=api_secret, token=request_token)
        return _session()

    monkeypatch.setattr(kite_session, "exchange", exchange)
    monkeypatch.setattr(
        kite_session, "save", lambda session, path: path.write_text(session.to_json())
    )
    reply = kite_routes.kite_login(
        kite_routes.LoginRequest(
            pasted="https://example.test/cb?request_token=abc123&status=success"
        )
    )
    assert reply["ok"] is True and reply["user"] == "AB1234"
    # The token is pulled out of the pasted address, and the secret goes only to the exchange.
    assert seen == {"key": "the-key", "secret": SECRET, "token": "abc123"}
    assert _configured.exists()
    assert TOKEN not in json.dumps(reply) and SECRET not in json.dumps(reply)

    status = kite_routes.kite_status()
    assert status["fresh"] is True and status["user"] == "AB1234"
    assert TOKEN not in json.dumps(status) and SECRET not in json.dumps(status)


@pytest.mark.usefixtures("_configured")
def test_a_bad_paste_and_a_refused_exchange_are_messages_not_crashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad = kite_routes.kite_login(kite_routes.LoginRequest(pasted="https://example.test/cb?x=1"))
    assert bad["ok"] is False and "request_token" in bad["error"]

    def refuse(**_: str) -> kite_session.Session:
        raise kite_session.SessionError("Token is invalid or has expired.")

    monkeypatch.setattr(kite_session, "exchange", refuse)
    refused = kite_routes.kite_login(kite_routes.LoginRequest(pasted="abc123"))
    assert refused == {"ok": False, "error": "Token is invalid or has expired."}


@pytest.mark.usefixtures("_configured")
def test_the_callback_page_escapes_what_it_echoes() -> None:
    page = kite_routes.kite_callback(request_token="", status="<script>x</script>")
    assert "<script>" not in page and "&lt;script&gt;" in page


def test_the_minute_step_uses_angel_without_a_fresh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eulerlab.ingest import backfill_minute, daily_feed

    def never(*_: object, **__: object) -> int:
        raise AssertionError("the ingest ran without a token")

    monkeypatch.setattr(kite_session, "load", lambda *a, **k: None)
    monkeypatch.setattr(backfill_minute, "main", never)
    # Without a token the step fetches from Angel One instead (2026-11-09).
    monkeypatch.setattr(daily_feed, "angel_minute_fill", lambda: "from Angel One")
    assert daily_feed._india_minute() == "from Angel One"
    assert "India minute bars" in dict(daily_feed.STEPS)
    assert "daily-minute" not in daily_feed.TERMINAL_ONLY
