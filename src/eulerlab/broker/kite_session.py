"""Obtain and cache a Kite access token.

Kite's access token expires at **6 AM the next day** — a regulatory requirement,
not a Kite choice — so it cannot be stored in `.env` alongside the durable
credentials. It would always be stale. It lives in a gitignored session file
instead, stamped with when it was minted.

**The login itself is the operator's job and cannot be automated.** It needs a
password and a 2FA code on Zerodha's own page. What this module does is the part
that follows: exchange the short-lived `request_token` from the redirect for an
`access_token`, using the API secret that is already in `.env`. That means no
credential has to be pasted into a chat window or handed to anyone.

Flow:
    1. `make kite-login` prints the login URL
    2. you log in; Zerodha redirects to your registered URL carrying
       `?request_token=...`
    3. paste that whole URL back; the exchange happens locally
"""

from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

LOGIN_URL = "https://kite.zerodha.com/connect/login?v=3&api_key={api_key}"
TOKEN_URL = "https://api.kite.trade/session/token"
SESSION_FILE = Path(".kite_session.json")


class SessionError(RuntimeError):
    """Login could not be completed."""


class TokenExchange(Protocol):
    """The one HTTP call, isolated so tests need no network."""

    def post(self, url: str, form: dict[str, str]) -> dict[str, object]: ...


@dataclass(frozen=True)
class Session:
    access_token: str
    user_id: str
    minted_at: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "access_token": self.access_token,
                "user_id": self.user_id,
                "minted_at": self.minted_at,
                "note": "Expires at 06:00 IST the day after minted_at. Re-run `make kite-login`.",
            },
            indent=2,
        )


def login_url(api_key: str) -> str:
    return LOGIN_URL.format(api_key=api_key)


def extract_request_token(pasted: str) -> str:
    """Pull `request_token` out of whatever the operator pastes.

    Accepts the full redirect URL or the bare token, because after logging in
    the obvious thing to do is copy the address bar.
    """
    text = pasted.strip()
    if not text:
        msg = "nothing pasted"
        raise SessionError(msg)

    if "request_token=" in text:
        query = urllib.parse.urlparse(text).query or text.split("?", 1)[-1]
        values = urllib.parse.parse_qs(query).get("request_token")
        if not values or not values[0]:
            msg = f"no request_token value found in {text[:80]!r}"
            raise SessionError(msg)
        return values[0]

    if "://" in text or "/" in text:
        msg = "that looks like a URL but has no request_token= in it"
        raise SessionError(msg)
    return text


def checksum(api_key: str, request_token: str, api_secret: str) -> str:
    """Kite's required SHA-256 of api_key + request_token + api_secret."""
    return hashlib.sha256(f"{api_key}{request_token}{api_secret}".encode()).hexdigest()


class UrllibExchange:
    def post(self, url: str, form: dict[str, str]) -> dict[str, object]:
        body = urllib.parse.urlencode(form).encode()
        request = urllib.request.Request(
            url,
            data=body,
            headers={"X-Kite-Version": "3", "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            parsed: dict[str, object] = json.load(response)
            return parsed


def exchange(
    *,
    api_key: str,
    api_secret: str,
    request_token: str,
    transport: TokenExchange | None = None,
) -> Session:
    """Swap a request_token for an access_token. The secret never leaves here."""
    client = transport or UrllibExchange()
    payload = client.post(
        TOKEN_URL,
        {
            "api_key": api_key,
            "request_token": request_token,
            "checksum": checksum(api_key, request_token, api_secret),
        },
    )

    data = payload.get("data")
    if not isinstance(data, dict):
        message = payload.get("message") or payload
        msg = f"Kite rejected the exchange: {message}"
        raise SessionError(msg)

    token = data.get("access_token")
    if not isinstance(token, str) or not token:
        msg = "Kite returned no access_token"
        raise SessionError(msg)

    user = data.get("user_id")
    return Session(
        access_token=token,
        user_id=user if isinstance(user, str) else "unknown",
        minted_at=datetime.now(UTC).isoformat(),
    )


def save(session: Session, path: Path = SESSION_FILE) -> Path:
    path.write_text(session.to_json(), encoding="utf-8")
    path.chmod(0o600)
    return path


def load(path: Path = SESSION_FILE) -> Session | None:
    """Read a cached session, or None when there is none or it is unreadable."""
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    token = raw.get("access_token")
    if not isinstance(token, str) or not token:
        return None
    return Session(
        access_token=token,
        user_id=str(raw.get("user_id", "unknown")),
        minted_at=str(raw.get("minted_at", "")),
    )


EXPIRY_HOUR_IST = 6
"""Kite tokens expire at 06:00 IST the day after they are minted."""


def last_expiry(now: datetime | None = None) -> datetime:
    """The most recent 06:00 IST at or before `now`, in UTC."""
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    ist = (now or datetime.now(UTC)).astimezone(ZoneInfo("Asia/Kolkata"))
    cut = ist.replace(hour=EXPIRY_HOUR_IST, minute=0, second=0, microsecond=0)
    if cut > ist:
        cut -= timedelta(days=1)
    return cut.astimezone(UTC)


def is_fresh(session: Session | None, now: datetime | None = None) -> bool:
    """Minted after the most recent 06:00 IST, so Kite still accepts it.

    The Makefile compared the UTC calendar dates of minting and now. That is
    not the rule: a token minted at 07:00 IST on the 9th is good until 06:00 on
    the 10th, which is 00:30 UTC on the 10th, and the date comparison called it
    stale from 05:30 IST (UTC midnight) while one minted at 05:00 IST read as
    good for its last hour after Kite had already expired it.
    """
    if session is None or not session.minted_at:
        return False
    try:
        minted = datetime.fromisoformat(session.minted_at)
    except ValueError:
        return False
    if minted.tzinfo is None:
        minted = minted.replace(tzinfo=UTC)
    return minted >= last_expiry(now)


def expires_at(session: Session) -> datetime:
    """When this session's token stops working (06:00 IST after minting)."""
    from datetime import timedelta

    minted = datetime.fromisoformat(session.minted_at)
    if minted.tzinfo is None:
        minted = minted.replace(tzinfo=UTC)
    return last_expiry(minted) + timedelta(days=1)


def check_fresh() -> int:
    """`make kite-fresh`: 0 when today's token is usable, 1 with a reason."""
    if is_fresh(load()):
        return 0
    print(
        "kite token is stale or absent - log in: Tools -> Instruments -> Log in to Kite, or make kite-login"
    )
    return 1
