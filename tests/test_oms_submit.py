"""The OMS: submit once, recover by asking, and never guess.

Every test here wires the OMS entirely inside `tmp_path` — its own journal,
its own broker state, its own kill switch. A test that could trip the real
kill switch or write to the real journal would be a hazard in its own right.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from eulerlab.backtest.events import Order, client_order_id
from eulerlab.costs.schedule import Side
from eulerlab.oms import ems
from eulerlab.oms.journal import Journal
from eulerlab.oms.killswitch import KillSwitch, KillSwitchTripped
from eulerlab.oms.oms import OMS
from eulerlab.oms.paper_broker import PaperBroker, PaperFaults
from eulerlab.oms.states import Event, OrderState

DAY = date(2026, 8, 20)


def _order(symbol: str = "RELIANCE", seq: int = 1, qty: int = 10) -> Order:
    return Order(
        client_order_id=client_order_id("t", DAY, symbol, seq),
        strategy_id="t",
        signal_day=DAY,
        symbol=symbol,
        side=Side.BUY,
        quantity=qty,
    )


def _oms(tmp_path: Path, *, faults: PaperFaults | None = None, limit: int = 100) -> OMS:
    return OMS(
        PaperBroker(tmp_path / "paper_broker.json", faults=faults),
        journal=Journal(tmp_path / "orders.jsonl"),
        governor=ems.Governor(limit),
        kill_switch=KillSwitch(tmp_path / "KILL_SWITCH", tmp_path / "ks.jsonl"),
    )


# --- idempotency ------------------------------------------------------------


def test_a_second_submit_of_the_same_order_does_nothing(tmp_path: Path) -> None:
    oms = _oms(tmp_path)
    assert oms.submit(_order(), price=100.0) is OrderState.FILLED
    before = len(oms.journal.read())
    assert oms.submit(_order(), price=100.0) is OrderState.FILLED
    assert len(oms.journal.read()) == before, "the retry wrote new events"
    assert len(oms.executions()) == 1


def test_a_retry_after_a_restart_still_does_not_double_send(tmp_path: Path) -> None:
    """The realistic retry: a fresh process re-running the same rebalance."""
    _oms(tmp_path).submit(_order(), price=100.0)
    second = _oms(tmp_path)
    second.submit(_order(), price=100.0)
    assert len(second.executions()) == 1


def test_the_same_intention_always_gets_the_same_id() -> None:
    assert _order().client_order_id == _order().client_order_id


# --- the three outcomes -----------------------------------------------------


def test_a_good_send_reaches_filled(tmp_path: Path) -> None:
    oms = _oms(tmp_path)
    assert oms.submit(_order(), price=100.0) is OrderState.FILLED
    assert oms.executions()[0].price == 100.0


def test_a_rejection_is_a_normal_outcome_not_an_exception(tmp_path: Path) -> None:
    oms = _oms(tmp_path, faults=PaperFaults(reject_symbols={"RELIANCE"}))
    assert oms.submit(_order(), price=100.0) is OrderState.REJECTED
    assert not oms.executions()


def test_an_ambiguous_send_becomes_unknown(tmp_path: Path) -> None:
    oms = _oms(tmp_path, faults=PaperFaults(unreachable_on_place=1))
    assert oms.submit(_order(), price=100.0) is OrderState.UNKNOWN
    assert oms.unresolved() == [_order().client_order_id]


# --- resolution -------------------------------------------------------------


def test_an_unknown_order_that_did_land_resolves_to_filled(tmp_path: Path) -> None:
    oms = _oms(tmp_path, faults=PaperFaults(unreachable_on_place=1))
    oms.submit(_order(), price=100.0)
    report = oms.resolve_unknown()
    assert oms.state(_order().client_order_id) is OrderState.FILLED
    assert report.clean
    assert len(oms.executions()) == 1


def test_an_unknown_order_that_did_not_land_resolves_to_unsent(tmp_path: Path) -> None:
    oms = _oms(tmp_path, faults=PaperFaults(lost_on_place=1))
    oms.submit(_order(), price=100.0)
    oms.resolve_unknown()
    assert oms.state(_order().client_order_id) is OrderState.UNSENT
    assert not oms.executions()


def test_a_failed_query_leaves_it_unknown_forever(tmp_path: Path) -> None:
    """CLAUDE.md: resolved by querying, never by assuming. Ten failed attempts
    resolve exactly as much as one — nothing."""
    oms = _oms(tmp_path, faults=PaperFaults(unreachable_on_place=1, unreachable_on_query=20))
    oms.submit(_order(), price=100.0)
    for _ in range(10):
        report = oms.resolve_unknown()
    assert oms.state(_order().client_order_id) is OrderState.UNKNOWN
    assert report.unresolved == [_order().client_order_id]
    assert not report.resolved


def test_a_broker_denying_an_order_we_have_fills_for_is_a_break(tmp_path: Path) -> None:
    """A contradiction, not a resolution. Picking the broker's version here
    would erase a position we are actually holding."""
    oms = _oms(tmp_path)
    oms.submit(_order(), price=100.0)
    # Force it back to UNKNOWN and then wipe the broker's memory of it.
    oms.journal.append(_order().client_order_id, Event.QUERY_FAILED, OrderState.UNKNOWN, {})
    (tmp_path / "paper_broker.json").write_text('{"orders": {}, "next_id": 9}', encoding="utf-8")

    report = oms.resolve_unknown()
    assert report.breaks and "recorded fills" in report.breaks[0]
    assert oms.state(_order().client_order_id) is OrderState.UNKNOWN
    assert not report.clean


# --- recovery ---------------------------------------------------------------


def test_recovery_makes_every_live_order_unknown_first(tmp_path: Path) -> None:
    oms = _oms(tmp_path)
    oms.journal.append("stale", Event.CREATED, OrderState.INTENT, {"symbol": "X"})
    oms.journal.append("stale", Event.ACK, OrderState.ACKNOWLEDGED, {})
    oms.recover()
    assert oms.state("stale") is OrderState.UNSENT  # queried, broker never saw it


def test_recovery_leaves_terminal_orders_alone(tmp_path: Path) -> None:
    oms = _oms(tmp_path)
    oms.submit(_order(), price=100.0)
    before = len(oms.journal.read())
    oms.recover()
    assert len(oms.journal.read()) == before
    assert oms.state(_order().client_order_id) is OrderState.FILLED


def test_recovery_is_safe_to_run_twice(tmp_path: Path) -> None:
    oms = _oms(tmp_path, faults=PaperFaults(unreachable_on_place=1))
    oms.submit(_order(), price=100.0)
    oms.recover()
    oms.recover()
    assert oms.state(_order().client_order_id) is OrderState.FILLED


# --- refusals ---------------------------------------------------------------


def test_a_tripped_kill_switch_stops_the_send_and_records_the_refusal(tmp_path: Path) -> None:
    oms = _oms(tmp_path)
    oms.kill_switch.trip("test", by="test")
    with pytest.raises(KillSwitchTripped):
        oms.submit(_order(), price=100.0)
    assert oms.state(_order().client_order_id) is OrderState.UNSENT
    assert not oms.adapter.positions()


def test_a_governor_refusal_is_recorded_as_unsent(tmp_path: Path) -> None:
    oms = _oms(tmp_path, limit=1)
    oms.governor.max_wait = 0.0
    oms.submit(_order(seq=1), price=100.0)
    with pytest.raises(ems.RateLimitExceeded):
        oms.submit(_order(symbol="TCS", seq=2), price=100.0)
    assert oms.state(_order(symbol="TCS", seq=2).client_order_id) is OrderState.UNSENT


def test_intent_is_journalled_before_anything_can_stop_it(tmp_path: Path) -> None:
    """The write-ahead property. Even an order that never gets sent leaves a
    record that we meant to send it."""
    oms = _oms(tmp_path)
    oms.kill_switch.trip("test", by="test")
    with pytest.raises(KillSwitchTripped):
        oms.submit(_order(), price=100.0)
    history = oms.history(_order().client_order_id)
    assert history[0].event is Event.CREATED
    assert history[0].state is OrderState.INTENT


# --- reading ----------------------------------------------------------------


def test_executions_come_from_the_journal_not_from_memory(tmp_path: Path) -> None:
    """A fresh process must see exactly what a long-running one sees."""
    _oms(tmp_path).submit(_order(), price=100.0)
    assert len(_oms(tmp_path).executions()) == 1
