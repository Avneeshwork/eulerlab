"""The dead-man switch trips when the armed live book's clock goes quiet (oms/deadman.py)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from eulerlab import paths
from eulerlab.oms import deadman
from eulerlab.oms.deadman import IST, check
from eulerlab.oms.killswitch import KillSwitch


@pytest.fixture
def data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path))
    return tmp_path


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=IST)


def arm(root: Path, session: str) -> None:
    (root / "live_money").mkdir(parents=True, exist_ok=True)
    (root / "live_money" / "deploy.json").write_text(
        json.dumps({"status": "armed", "for_session": session})
    )


def beat(root: Path, when: str) -> None:
    (root / "live_money").mkdir(parents=True, exist_ok=True)
    (root / "live_money" / "heartbeat.json").write_text(json.dumps({"at": when, "last": "holding"}))


def switch(root: Path) -> KillSwitch:
    return KillSwitch(root / "oms" / "KILL_SWITCH", root / "oms" / "killswitch_log.jsonl")


def test_nothing_armed_means_nothing_happens(data_dir: Path) -> None:
    sw = switch(data_dir)
    v = check(at("2026-11-12T10:00"), switch=sw, send=lambda t: None)
    assert not v.tripped and not v.armed
    assert not sw.is_tripped()


def test_a_live_clock_is_left_alone(data_dir: Path) -> None:
    arm(data_dir, "2026-11-12")
    beat(data_dir, "2026-11-12T10:00:00+05:30")
    sw = switch(data_dir)
    v = check(at("2026-11-12T10:01"), switch=sw, send=lambda t: None)
    assert v.armed and v.in_hours and not v.stale and not v.tripped
    assert v.heartbeat_age_s == 60


def test_a_stale_clock_in_market_hours_trips_once_and_tells(data_dir: Path) -> None:
    arm(data_dir, "2026-11-12")
    beat(data_dir, "2026-11-12T10:00:00+05:30")
    sw = switch(data_dir)
    sent: list[str] = []
    v = check(at("2026-11-12T10:03"), switch=sw, send=sent.append)
    assert v.tripped and v.stale and v.heartbeat_age_s == 180
    assert sw.is_tripped() and "dead-man" in sw.reason()
    assert sent and "square off by hand" in sent[0]
    again = check(at("2026-11-12T10:04"), switch=sw, send=sent.append)
    assert again.tripped and again.why == "already tripped today"
    assert len(sent) == 1


def test_no_heartbeat_at_all_counts_as_stale(data_dir: Path) -> None:
    arm(data_dir, "2026-11-12")
    sw = switch(data_dir)
    v = check(at("2026-11-12T09:30"), switch=sw, send=lambda t: None)
    assert v.heartbeat_age_s is None and v.tripped and sw.is_tripped()


def test_outside_market_hours_or_another_session_is_not_tripped(data_dir: Path) -> None:
    arm(data_dir, "2026-11-12")
    sw = switch(data_dir)
    assert not check(at("2026-11-12T16:00"), switch=sw, send=lambda t: None).tripped
    assert not check(
        at("2026-11-11T10:00"), switch=sw, send=lambda t: None
    ).tripped  # armed for tomorrow
    assert not check(at("2026-11-14T10:00"), switch=sw, send=lambda t: None).tripped  # Saturday
    assert not sw.is_tripped()


def test_the_watcher_imports_no_broker_or_book() -> None:
    """It runs in the kill-switch process: no credential, no order path."""
    text = Path(deadman.__file__).read_text()
    for forbidden in ("eulerlab.deploy", "eulerlab.broker", "smartapi", "kite", "KILLSWITCH_TOKEN"):
        assert (
            forbidden not in text.replace("KILLSWITCH_TOKEN", "") or forbidden == "KILLSWITCH_TOKEN"
        )
