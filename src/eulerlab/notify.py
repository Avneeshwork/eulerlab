"""Tell the operator when an unattended job fails.

### Why this exists

The nightly job failed at 19:30 every evening for six days and nobody knew. It
wrote its stderr to a log file and told no one, so the first signal was a human
noticing a stale date on a screen — six days and four trading sessions after
the fact.

A job that runs unattended and reports only to a file it nobody reads is not
monitored, it is merely logged. This is the difference.

### What it will not do

It does not announce success. A message every evening that everything is fine
trains the reader to ignore the channel, and then the one message that matters
is ignored too. Silence means healthy; a message means look.

It also never raises. A notifier that throws on a network blip would turn "the
backfill failed" into "the backfill failed and then the failure handler failed",
losing the original error. Delivery is best-effort and its own outcome is
returned rather than thrown.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

API = "https://api.telegram.org/bot{token}/sendMessage"
TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
CHAT_ENV = "TELEGRAM_CHAT_ID"

MAX_BODY = 3500
"""Telegram caps a message at 4096 characters. Trimmed below that so a long
traceback arrives truncated rather than rejected — a truncated error is
readable, a rejected one is another silent failure."""


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    env = Path(".env")
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            key, _, raw = line.partition("=")
            if key.strip() == name:
                return raw.strip().strip('"').strip("'")
    return ""


def configured() -> bool:
    """Whether a destination exists, without revealing it."""
    return bool(_env(TOKEN_ENV) and _env(CHAT_ENV))


@dataclass(frozen=True)
class Delivery:
    """What happened when we tried to send. Returned, never raised."""

    sent: bool
    reason: str = ""


def send(text: str, *, timeout: int = 15) -> Delivery:
    """Best-effort message. Returns the outcome instead of raising."""
    token, chat = _env(TOKEN_ENV), _env(CHAT_ENV)
    if not token or not chat:
        return Delivery(False, f"{TOKEN_ENV} or {CHAT_ENV} not set")

    body = text if len(text) <= MAX_BODY else text[: MAX_BODY - 3] + "..."
    payload = urllib.parse.urlencode({"chat_id": chat, "text": body}).encode()
    request = urllib.request.Request(
        API.format(token=token),
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            answer = json.loads(response.read().decode("utf-8"))
        return Delivery(bool(answer.get("ok")), "" if answer.get("ok") else str(answer)[:200])
    except urllib.error.HTTPError as exc:
        # The body carries Telegram's own reason ("chat not found"), which is
        # the part worth keeping. The URL is not logged: it contains the token.
        return Delivery(False, f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:160]}")
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return Delivery(False, f"{type(exc).__name__}: {exc}")


def job_failed(job: str, *, code: int, log: Path | None = None, lines: int = 12) -> Delivery:
    """Report an unattended job that exited non-zero.

    The tail of the log goes in the message rather than a path to it. A message
    saying "check the log" needs the reader at a machine; a message carrying
    the actual error can be read on a phone and often answered from there.
    """
    tail = ""
    if log is not None and log.exists():
        try:
            rows = log.read_text(encoding="utf-8", errors="replace").splitlines()
            tail = "\n".join(rows[-lines:]).strip()
        except OSError as exc:
            tail = f"(log unreadable: {type(exc).__name__})"

    message = f"❌ {job} failed (exit {code})"
    if tail:
        message += f"\n\n{tail}"
    return send(message)
