"""The kill switch: easy to trip, deliberately awkward to clear.

Two of these are structural checks on the source tree rather than on
behaviour, in the same spirit as the test that keeps thresholds out of
`gates.py`. A rule that is only written in a docstring survives exactly until
someone adds a convenience function.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eulerlab.oms import killswitch
from eulerlab.oms.killswitch import (
    TOKEN_VAR,
    DayState,
    KillSwitch,
    KillSwitchTripped,
    Limits,
    breaches,
    load_limits,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "eulerlab"


def _switch(tmp_path: Path) -> KillSwitch:
    return KillSwitch(tmp_path / "KILL_SWITCH", tmp_path / "log.jsonl")


# --- structural -------------------------------------------------------------


def test_no_module_but_the_switch_itself_mentions_the_reset_credential() -> None:
    """CLAUDE.md: kill switches use separate credentials from the strategies.
    The trading process must not be able to authenticate a reset even by
    accident, so nothing else may even name the variable."""
    offenders = [
        path.relative_to(SRC)
        for path in SRC.rglob("*.py")
        if path.name != "killswitch.py" and TOKEN_VAR in path.read_text(encoding="utf-8")
    ]
    assert not offenders, f"{offenders} reference {TOKEN_VAR}"


def test_there_is_no_importable_reset_function() -> None:
    """A `reset()` on the object would be called in a retry loop at 3 a.m.
    Clearing lives behind a command-line flag and a credential, on purpose."""
    assert not hasattr(KillSwitch, "reset")
    assert not hasattr(KillSwitch, "clear")
    assert not hasattr(killswitch, "reset")


# --- behaviour --------------------------------------------------------------


def test_tripping_stops_the_next_send(tmp_path: Path) -> None:
    switch = _switch(tmp_path)
    switch.require_clear()  # clear: no exception
    switch.trip("daily loss", by="test")
    with pytest.raises(KillSwitchTripped, match="daily loss"):
        switch.require_clear()


def test_require_clear_raises_rather_than_returning_a_bool(tmp_path: Path) -> None:
    """A boolean gets ignored. An exception does not."""
    switch = _switch(tmp_path)
    switch.trip("x", by="test")
    with pytest.raises(KillSwitchTripped):
        switch.require_clear()


def test_the_first_reason_survives_later_trips(tmp_path: Path) -> None:
    """The first trip is the informative one. Everything after it is a
    consequence of having stopped."""
    switch = _switch(tmp_path)
    switch.trip("daily loss limit", by="limits")
    switch.trip("5 rejections in a row", by="limits")
    assert switch.reason() == "daily loss limit"


def test_every_trip_is_logged_even_the_redundant_ones(tmp_path: Path) -> None:
    switch = _switch(tmp_path)
    switch.trip("first", by="a")
    switch.trip("second", by="b")
    lines = (tmp_path / "log.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["reason"] for line in lines] == ["first", "second"]


def test_an_unreadable_trip_file_still_reads_as_tripped(tmp_path: Path) -> None:
    """Failing to parse the reason must never read as 'not tripped'."""
    switch = _switch(tmp_path)
    switch.trip("x", by="test")
    switch.path.write_text("{{{ not json", encoding="utf-8")
    assert switch.is_tripped()
    assert switch.reason() == "unreadable trip file"
    with pytest.raises(KillSwitchTripped):
        switch.require_clear()


# --- automatic limits -------------------------------------------------------


def test_a_clean_day_breaches_nothing() -> None:
    assert breaches(DayState(realised_pnl=500.0, orders_today=12), Limits()) == []


def test_the_loss_limit_counts_unrealised_too() -> None:
    """A position that has lost the money but has not been sold has still lost
    the money."""
    limits = Limits(max_daily_loss=1000.0)
    assert breaches(DayState(realised_pnl=0.0, unrealised_pnl=-1500.0), limits)


def test_every_breach_is_reported_not_just_the_first() -> None:
    """When a system goes wrong it usually breaks several limits at once."""
    limits = Limits(max_daily_loss=100.0, max_orders_per_day=1, max_consecutive_rejections=2)
    found = breaches(
        DayState(realised_pnl=-500.0, orders_today=9, consecutive_rejections=3), limits
    )
    assert len(found) == 3


def test_too_many_unknown_orders_is_a_breach() -> None:
    """More than a handful means the broker link is unhealthy, and sending
    into an unhealthy link is how one ambiguous order becomes twenty."""
    found = breaches(DayState(unresolved_orders=99), Limits(max_unresolved_orders=3))
    assert found and "UNKNOWN" in found[0]


def test_check_trips_the_switch_when_a_limit_breaks(tmp_path: Path) -> None:
    switch = _switch(tmp_path)
    found = switch.check(DayState(realised_pnl=-1e9), Limits(max_daily_loss=100.0))
    assert found
    assert switch.is_tripped()


def test_check_leaves_a_healthy_day_alone(tmp_path: Path) -> None:
    switch = _switch(tmp_path)
    assert switch.check(DayState(realised_pnl=10.0), Limits()) == []
    assert not switch.is_tripped()


def test_limits_reject_an_unknown_key(tmp_path: Path) -> None:
    """A typo in the limits file must stop the process, not be ignored."""
    path = tmp_path / "killswitch.yaml"
    path.write_text("max_dialy_loss: 500\n", encoding="utf-8")
    with pytest.raises(ValueError, match="extra"):
        load_limits(path)


def test_the_committed_limits_file_parses() -> None:
    assert load_limits().max_daily_loss > 0
