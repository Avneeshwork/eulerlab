"""Token exchange, without a network and without real credentials."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from eulerlab.broker.kite_session import (
    Session,
    SessionError,
    checksum,
    exchange,
    extract_request_token,
    load,
    login_url,
    save,
)

API_KEY, API_SECRET, REQ = "apikey123", "secret456", "reqtok789"


@dataclass
class FakeExchange:
    payload: dict[str, object]
    seen: list[dict[str, str]] = field(default_factory=list)

    def post(self, url: str, form: dict[str, str]) -> dict[str, object]:
        self.seen.append(form)
        return self.payload


def _ok() -> FakeExchange:
    return FakeExchange({"status": "success", "data": {"access_token": "tok", "user_id": "AB1234"}})


def test_login_url_carries_the_api_key() -> None:
    assert f"api_key={API_KEY}" in login_url(API_KEY)


def test_checksum_matches_kites_definition() -> None:
    expected = hashlib.sha256(f"{API_KEY}{REQ}{API_SECRET}".encode()).hexdigest()
    assert checksum(API_KEY, REQ, API_SECRET) == expected


@pytest.mark.parametrize(
    "pasted",
    [
        "https://example.com/redirect?request_token=abc123&action=login&status=success",
        "https://example.com/redirect?action=login&request_token=abc123",
        "?request_token=abc123",
        "abc123",
        "  abc123  ",
    ],
)
def test_request_token_is_found_however_it_is_pasted(pasted: str) -> None:
    # After logging in, the obvious thing to do is copy the address bar.
    assert extract_request_token(pasted) == "abc123"


@pytest.mark.parametrize("pasted", ["", "   ", "https://example.com/redirect?status=success"])
def test_unusable_paste_is_rejected_clearly(pasted: str) -> None:
    with pytest.raises(SessionError):
        extract_request_token(pasted)


def test_exchange_sends_the_checksum_not_the_secret() -> None:
    """The API secret must never travel as a field of its own."""
    fake = _ok()
    exchange(api_key=API_KEY, api_secret=API_SECRET, request_token=REQ, transport=fake)

    sent = fake.seen[0]
    assert sent["checksum"] == checksum(API_KEY, REQ, API_SECRET)
    assert API_SECRET not in sent.values()


def test_successful_exchange_returns_the_token() -> None:
    session = exchange(api_key=API_KEY, api_secret=API_SECRET, request_token=REQ, transport=_ok())
    assert session.access_token == "tok"
    assert session.user_id == "AB1234"
    assert session.minted_at.endswith("+00:00")


def test_a_rejected_exchange_raises_with_kites_message() -> None:
    fake = FakeExchange({"status": "error", "message": "Invalid checksum"})
    with pytest.raises(SessionError, match="Invalid checksum"):
        exchange(api_key=API_KEY, api_secret=API_SECRET, request_token=REQ, transport=fake)


def test_a_response_without_a_token_raises() -> None:
    fake = FakeExchange({"status": "success", "data": {"user_id": "AB1234"}})
    with pytest.raises(SessionError, match="no access_token"):
        exchange(api_key=API_KEY, api_secret=API_SECRET, request_token=REQ, transport=fake)


def test_session_round_trips_through_the_file(tmp_path: Path) -> None:
    path = tmp_path / ".kite_session.json"
    save(Session("tok", "AB1234", "2026-08-18T00:00:00+00:00"), path)
    loaded = load(path)
    assert loaded is not None
    assert loaded.access_token == "tok"


def test_the_session_file_is_not_world_readable(tmp_path: Path) -> None:
    path = tmp_path / ".kite_session.json"
    save(Session("tok", "AB1234", "now"), path)
    assert path.stat().st_mode & 0o077 == 0


def test_the_session_file_says_when_it_expires(tmp_path: Path) -> None:
    path = tmp_path / ".kite_session.json"
    save(Session("tok", "AB1234", "now"), path)
    assert "06:00 IST" in json.loads(path.read_text(encoding="utf-8"))["note"]


def test_missing_or_corrupt_session_returns_none(tmp_path: Path) -> None:
    assert load(tmp_path / "absent.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load(bad) is None
