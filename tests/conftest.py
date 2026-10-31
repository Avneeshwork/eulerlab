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
def _private_listings(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No test reads or writes the real server's saved bucket listings."""
    monkeypatch.setattr(landing_reader, "LISTING_DIR", tmp_path_factory.mktemp("listings"))


@pytest.fixture(autouse=True)
def _private_panel_copy(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No test reads or writes the real panel's columnar copy."""
    from eulerlab.features import panel

    monkeypatch.setattr(panel, "COLUMNS_DIR", tmp_path_factory.mktemp("panel_copy"))


@pytest.fixture(autouse=True)
def _private_options_history(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No test reads or appends to the server's saved straddle points."""
    from eulerlab.api import server

    folder = tmp_path_factory.mktemp("options_history")
    monkeypatch.setattr(server, "OPTIONS_HISTORY_CACHE", folder / "points.jsonl")
    monkeypatch.setattr(server, "_HISTORY_POINTS", {})
    monkeypatch.setattr(server, "_history_loaded", False)


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


@pytest.fixture(autouse=True)
def _empty_request_caches() -> None:
    """Every test starts with the API's request caches empty (ADR-077), and Yahoo not backed off.

    They live for the server's life, so one test's live quotes or bucket
    listing would otherwise be served to the next. Cleared only when the server
    module is already loaded: importing it here would slow every other test.
    """
    import sys

    quotes = sys.modules.get("eulerlab.quotes")
    if quotes is not None:
        quotes._yahoo_blocked_until[0] = 0.0
    server = sys.modules.get("eulerlab.api.server")
    if server is not None:
        server._LIVE_UNIVERSE.clear()
        server._CLOUD_LISTINGS.clear()
        server._HISTORY_POINTS.clear()
        server._LANDING_COUNTS.clear()
        server._MARKET_CONTEXT.clear()
        server._BREADTH.clear()


@pytest.fixture(autouse=True)
def _simulated_order_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """The order governor waits on a simulated clock, not real seconds.

    Paper runs send many orders at 5 a second, so a test that ran one slept
    through the limit for real: 25 of `test_paper_attribution.py`'s 27 s
    (2026-10-27). The limit is still enforced and still counted; only the wait
    is simulated. `test_ems_governor.py` passes its own clock and is unaffected.
    """
    from eulerlab.oms import ems

    now = [0.0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    defaults = dict(ems.Governor.__init__.__kwdefaults__ or {})
    defaults.update(clock=lambda: now[0], sleep=sleep)
    monkeypatch.setattr(ems.Governor.__init__, "__kwdefaults__", defaults)


@pytest.fixture(autouse=True)
def _private_positions(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No test reads or appends to the real parsed participant history."""
    import sys

    from eulerlab import market_context

    folder = tmp_path_factory.mktemp("positions")
    monkeypatch.setattr(market_context, "POSITIONS_CACHE", folder / "positions.jsonl")
    server = sys.modules.get("eulerlab.api.server")
    if server is not None:
        monkeypatch.setattr(
            server, "_POSITIONS", market_context.PositionHistory(folder / "positions.jsonl")
        )


@pytest.fixture(autouse=True)
def _private_agent_files(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Agent outputs, the quarantine list, grades, timings and desk approvals go to a temp folder.

    Each of these is an append-only record the operator reads; a test run
    writing into the real ones would put fake runs in the agent log (ADR-085).
    """
    from eulerlab import desk, timings
    from eulerlab.agents import spec
    from eulerlab.quality import contract, quarantine

    base = tmp_path_factory.mktemp("agentfiles")
    monkeypatch.setattr(spec, "ROOT", base / "agents")
    monkeypatch.setattr(quarantine, "PATH", base / "quarantine.jsonl")
    monkeypatch.setattr(contract, "GRADES", base / "grades.json")
    monkeypatch.setattr(timings, "PATH", base / "timings.jsonl")
    monkeypatch.setattr(desk, "APPROVALS", base / "approvals.jsonl")
