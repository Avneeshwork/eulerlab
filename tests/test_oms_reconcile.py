"""Reconciliation: find the disagreement, correct the record, place no order.

The last of those is the one worth a test of its own. "Trade to fix the break"
is the intuitive behaviour and it is wrong: a break means we do not know what
happened, and the most common cause is a fill we failed to record — so trading
the difference doubles the position exactly when we are least able to tell.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from eulerlab.backtest.events import Order, client_order_id
from eulerlab.costs.schedule import Side
from eulerlab.oms import ems, reconcile
from eulerlab.oms.journal import Journal
from eulerlab.oms.killswitch import KillSwitch
from eulerlab.oms.oms import OMS
from eulerlab.oms.paper_broker import PaperBroker

DAY = date(2026, 8, 20)


def _order(symbol: str, seq: int, side: Side = Side.BUY, qty: int = 10) -> Order:
    return Order(
        client_order_id=client_order_id("t", DAY, symbol, seq),
        strategy_id="t",
        signal_day=DAY,
        symbol=symbol,
        side=side,
        quantity=qty,
    )


def _oms(tmp_path: Path) -> OMS:
    return OMS(
        PaperBroker(tmp_path / "paper_broker.json"),
        journal=Journal(tmp_path / "orders.jsonl"),
        governor=ems.Governor(100),
        kill_switch=KillSwitch(tmp_path / "KILL_SWITCH", tmp_path / "ks.jsonl"),
    )


def test_agreement_produces_no_breaks(tmp_path: Path) -> None:
    oms = _oms(tmp_path)
    oms.submit(_order("TCS", 1), price=100.0)
    oms.submit(_order("INFY", 2, qty=5), price=200.0)
    result = reconcile.reconcile(oms)
    assert result.clean
    assert sorted(result.matched) == ["INFY", "TCS"]


def test_a_position_only_the_broker_has_is_the_worst_break(tmp_path: Path) -> None:
    """Unmanaged risk: no stop and no limit in this system applies to it."""
    oms = _oms(tmp_path)
    oms.submit(_order("TCS", 1), price=100.0)
    PaperBroker(tmp_path / "paper_broker.json").inject("manual", "INFY", Side.BUY, 40, 1500.0)

    result = reconcile.reconcile(oms)
    assert not result.clean
    break_ = next(b for b in result.breaks if b.symbol == "INFY")
    assert break_.kind == "broker_only"
    assert break_.local == 0
    assert break_.broker == 40
    assert reconcile.SEVERITY["broker_only"] == min(reconcile.SEVERITY.values())


def test_a_quantity_mismatch_is_reported_with_the_difference(tmp_path: Path) -> None:
    oms = _oms(tmp_path)
    oms.submit(_order("TCS", 1, qty=10), price=100.0)
    PaperBroker(tmp_path / "paper_broker.json").inject("extra", "TCS", Side.BUY, 3, 100.0)

    result = reconcile.reconcile(oms)
    break_ = next(b for b in result.breaks if b.symbol == "TCS")
    assert break_.kind == "quantity"
    assert break_.local == 10
    assert break_.broker == 13
    assert "+3" in break_.detail


def test_a_position_only_we_think_we_have(tmp_path: Path) -> None:
    oms = _oms(tmp_path)
    oms.submit(_order("TCS", 1), price=100.0)
    # The broker forgets it: the shape of an order we recorded as filled that
    # was really rejected.
    (tmp_path / "paper_broker.json").write_text('{"orders": {}, "next_id": 9}', encoding="utf-8")

    result = reconcile.reconcile(oms)
    break_ = next(b for b in result.breaks if b.symbol == "TCS")
    assert break_.kind == "local_only"
    assert break_.local == 10
    assert break_.broker == 0


def test_reconciliation_places_no_orders(tmp_path: Path) -> None:
    """The rule stated as a test: it corrects the record, never the market."""
    oms = _oms(tmp_path)
    oms.submit(_order("TCS", 1), price=100.0)
    PaperBroker(tmp_path / "paper_broker.json").inject("manual", "INFY", Side.BUY, 40, 1500.0)

    before = len(oms.journal.read())
    reconcile.reconcile(oms)
    assert len(oms.journal.read()) == before, "reconciliation wrote order events"
    assert PaperBroker(tmp_path / "paper_broker.json").positions() == {"TCS": 10, "INFY": 40}


def test_local_positions_come_from_the_journal(tmp_path: Path) -> None:
    """Not from a running total in memory: the comparison has to be against
    the record we would actually have after a restart."""
    _oms(tmp_path).submit(_order("TCS", 1), price=100.0)
    assert reconcile.local_positions(_oms(tmp_path)) == {"TCS": 10}


def test_a_closed_position_does_not_linger(tmp_path: Path) -> None:
    oms = _oms(tmp_path)
    oms.submit(_order("TCS", 1, qty=10), price=100.0)
    oms.submit(_order("TCS", 2, side=Side.SELL, qty=10), price=110.0)
    assert reconcile.local_positions(oms) == {}
    assert reconcile.reconcile(oms).clean


def test_the_report_says_what_it_will_not_do(tmp_path: Path) -> None:
    oms = _oms(tmp_path)
    PaperBroker(tmp_path / "paper_broker.json").inject("manual", "INFY", Side.BUY, 40, 1500.0)
    text = reconcile.reconcile(oms).render()
    assert "No order is placed" in text


def test_a_partial_fill_then_the_full_fill_counts_the_order_once(tmp_path: Path) -> None:
    """Fill entries carry the broker's cumulative quantity (HISTORY #51).

    Partial seen at 4 of 10, the process restarts, the complete fill is seen
    at 10 of 10: the position is 10, not 14.
    """
    from eulerlab.oms.states import Event, OrderState

    oms = _oms(tmp_path)
    order = _order("TCS", 1, qty=10)
    coid = order.client_order_id
    fill = {"symbol": "TCS", "side": "buy", "signal_day": DAY.isoformat()}
    oms.journal.append(coid, Event.CREATED, OrderState.INTENT, {"symbol": "TCS"})
    state = oms._apply(coid, OrderState.INTENT, Event.SEND_OK, {})
    state = oms._apply(coid, state, Event.PROCESS_RESTART, {})
    state = oms._apply(
        coid,
        state,
        Event.QUERY_FOUND_PARTIAL,
        {**fill, "filled_quantity": 4, "average_price": 99.0},
    )
    state = oms._apply(coid, state, Event.PROCESS_RESTART, {})
    oms._apply(
        coid,
        state,
        Event.QUERY_FOUND_FILLED,
        {**fill, "filled_quantity": 10, "average_price": 99.5},
    )

    executions = oms.executions()
    assert [(e.quantity, e.price) for e in executions] == [(10, 99.5)]
    assert reconcile.local_positions(oms) == {"TCS": 10}
