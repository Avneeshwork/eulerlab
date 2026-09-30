"""Failure notification — what it sends, and what it refuses to do."""

from __future__ import annotations

from pathlib import Path

import pytest

from eulerlab import notify


def test_a_missing_destination_is_reported_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    """A notifier that throws would turn "the backfill failed" into "the
    backfill failed and then the failure handler failed", losing the original
    error — which is the one worth having."""
    monkeypatch.chdir(Path(__file__).parent)  # no .env here
    monkeypatch.delenv(notify.TOKEN_ENV, raising=False)
    monkeypatch.delenv(notify.CHAT_ENV, raising=False)

    outcome = notify.send("anything")
    assert outcome.sent is False
    assert notify.TOKEN_ENV in outcome.reason


def test_a_long_message_is_trimmed_rather_than_rejected() -> None:
    """Telegram caps a message at 4096 characters. A truncated traceback is
    readable; a rejected one is another silent failure on top of the first."""
    assert notify.MAX_BODY < 4096


def test_the_failure_message_carries_the_error_not_a_path(tmp_path: Path) -> None:
    """A message saying "check the log" needs the reader at a machine. One
    carrying the actual error can be read on a phone."""
    log = tmp_path / "daily.err"
    log.write_text("step one fine\nmake: *** [daily] Error 2\n", encoding="utf-8")

    sent: dict[str, str] = {}

    def capture(text: str, *, timeout: int = 15) -> notify.Delivery:
        sent["text"] = text
        return notify.Delivery(True)

    original = notify.send
    notify.send = capture
    try:
        notify.job_failed("make daily", code=2, log=log)
    finally:
        notify.send = original

    assert "exit 2" in sent["text"]
    assert "Error 2" in sent["text"], "the actual failing line, not a path"
    assert str(log) not in sent["text"]


def test_an_unreadable_log_still_sends_something(tmp_path: Path) -> None:
    """The exit code alone is worth delivering. Failing to read the log must
    not swallow the fact that the job failed."""
    sent: dict[str, str] = {}

    def capture(text: str, *, timeout: int = 15) -> notify.Delivery:
        sent["text"] = text
        return notify.Delivery(True)

    original = notify.send
    notify.send = capture
    try:
        notify.job_failed("make daily", code=2, log=tmp_path / "absent.log")
    finally:
        notify.send = original

    assert "make daily" in sent["text"] and "exit 2" in sent["text"]
