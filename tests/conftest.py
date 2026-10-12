"""Test-wide defaults.

The suite runs offline. Tests reached the bucket only transitively — calling
`catalog.search` listed 34,000 remote keys — and one stalled connection hung a
run for 33 minutes instead of failing it. A hang is worse than a failure: it
looks the same as slow work, so it blocked every commit behind it without ever
saying why.

Set `EULERLAB_NO_CLOUD=0` to run a test against the real bucket deliberately.
"""

from __future__ import annotations

import os

import pytest

from eulerlab.ingest import landing_reader


@pytest.fixture(autouse=True, scope="session")
def _offline() -> None:
    os.environ.setdefault(landing_reader.OFFLINE_ENV, "1")


@pytest.fixture(autouse=True)
def _private_locks(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every test gets its own lock folder.

    The repo's `data/derived/.locks` belongs to real runs. On 2026-10-09 three
    feed tests failed because `make feed` was running and held the real `feed`
    lock; a test must not depend on what else the machine is doing.
    """
    from eulerlab.ingest import filelock

    monkeypatch.setattr(filelock, "LOCK_DIR", tmp_path_factory.mktemp("locks"))


@pytest.fixture(autouse=True)
def _private_last_seen(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No test reads or replaces the operator's last-seen prices.

    The snapshot saves live quotes to `data/derived/` and reads them back on
    its first paint, so a test of it would otherwise depend on, and overwrite,
    whatever the real dashboard last showed.
    """
    from eulerlab import last_seen

    folder = tmp_path_factory.mktemp("last_seen")
    monkeypatch.setattr(last_seen, "PATH", folder / "quotes.json")
    monkeypatch.setattr(last_seen, "MINUTE_ROOT", folder / "minute")


@pytest.fixture(autouse=True)
def _no_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test sends a Telegram message.

    `notify` reads the token from `.env`, which exists on the operator's
    machine, so a test that runs a deployment would message their phone.
    Tests of the signals themselves turn this back on with a fake sender.
    """
    monkeypatch.setenv("EULERLAB_TELEGRAM_SIGNALS", "0")
    monkeypatch.setenv("EULERLAB_TELEGRAM_BOT", "0")
