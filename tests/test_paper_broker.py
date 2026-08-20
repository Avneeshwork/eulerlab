"""The simulated broker, and the faults it can be made to inject.

The tests that matter most here are the two ambiguity cases. They look
identical from the caller's side — both raise `BrokerUnreachable` — and they
mean opposite things about whether an order is live at an exchange. If the
simulator could not produce both, the OMS's handling of them would be
untestable, and `UNKNOWN` would be a state nothing ever exercised.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from eulerlab.backtest.events import Order, client_order_id
from eulerlab.costs.schedule import Side
from eulerlab.oms.broker import (
    BrokerRejected,
    BrokerUnreachable,
    DuplicateOrder,
)
from eulerlab.oms.paper_broker import PaperBroker, PaperFaults

DAY = date(2026, 8, 20)


def _order(symbol: str = "RELIANCE", seq: int = 1, side: Side = Side.BUY, qty: int = 10) -> Order:
    return Order(
        client_order_id=client_order_id("t", DAY, symbol, seq),
        strategy_id="t",
        signal_day=DAY,
        symbol=symbol,
        side=side,
        quantity=qty,
    )


def _broker(tmp_path: Path, **kwargs: object) -> PaperBroker:
    return PaperBroker(tmp_path / "paper_broker.json", **kwargs)  # type: ignore[arg-type]


def test_a_placed_order_fills_and_is_queryable(tmp_path: Path) -> None:
    broker = _broker(tmp_path)
    broker.place(_order(), price=100.0)
    view = broker.query(_order().client_order_id)
    assert view is not None
    assert view.status == "complete"
    assert view.filled_quantity == 10
    assert view.average_price == 100.0


def test_the_broker_remembers_across_objects(tmp_path: Path) -> None:
    """A broker whose state died with the process could not be a source of
    truth, and every reconciliation test against it would be circular."""
    _broker(tmp_path).place(_order(), price=100.0)
    assert _broker(tmp_path).query(_order().client_order_id) is not None


def test_a_duplicate_client_order_id_is_refused(tmp_path: Path) -> None:
    """The property that makes deterministic ids protective rather than tidy."""
    broker = _broker(tmp_path)
    broker.place(_order(), price=100.0)
    with pytest.raises(DuplicateOrder, match="already exists"):
        broker.place(_order(), price=100.0)


def test_an_unpriced_instrument_is_rejected_not_filled(tmp_path: Path) -> None:
    broker = _broker(tmp_path)
    with pytest.raises(BrokerRejected, match="did not trade"):
        broker.place(_order(), price=None)
    view = broker.query(_order().client_order_id)
    assert view is not None and view.status == "rejected"


def test_an_unreachable_place_still_records_the_order(tmp_path: Path) -> None:
    """The dangerous half of the ambiguity: it IS live and we were not told."""
    broker = _broker(tmp_path, faults=PaperFaults(unreachable_on_place=1))
    with pytest.raises(BrokerUnreachable):
        broker.place(_order(), price=100.0)
    view = broker.query(_order().client_order_id)
    assert view is not None and view.status == "complete"


def test_a_lost_place_records_nothing(tmp_path: Path) -> None:
    """The other half. Same exception at the call site, opposite truth."""
    broker = _broker(tmp_path, faults=PaperFaults(lost_on_place=1))
    with pytest.raises(BrokerUnreachable):
        broker.place(_order(), price=100.0)
    assert broker.query(_order().client_order_id) is None


def test_faults_are_counted_down_not_permanent(tmp_path: Path) -> None:
    broker = _broker(tmp_path, faults=PaperFaults(lost_on_place=1))
    with pytest.raises(BrokerUnreachable):
        broker.place(_order(seq=1), price=100.0)
    broker.place(_order(seq=2, symbol="TCS"), price=100.0)
    assert broker.query(_order(seq=2, symbol="TCS").client_order_id) is not None


def test_a_failing_query_raises_rather_than_returning_none(tmp_path: Path) -> None:
    """`None` means the broker positively has no record, which is what turns
    an UNKNOWN order into UNSENT. A failed query must never say that."""
    broker = _broker(tmp_path, faults=PaperFaults(unreachable_on_query=1))
    with pytest.raises(BrokerUnreachable):
        broker.query("anything")


def test_slippage_is_adverse_on_both_sides(tmp_path: Path) -> None:
    broker = _broker(tmp_path, slippage_bps=100.0)
    assert broker.fill_price(Side.BUY, 100.0) == pytest.approx(101.0)
    assert broker.fill_price(Side.SELL, 100.0) == pytest.approx(99.0)


def test_slippage_is_deterministic(tmp_path: Path) -> None:
    """CLAUDE.md requires byte-identical output from identical input. A random
    fill price would make every paper comparison unrepeatable."""
    a = _broker(tmp_path / "a", slippage_bps=17.0).fill_price(Side.BUY, 512.3)
    b = _broker(tmp_path / "b", slippage_bps=17.0).fill_price(Side.BUY, 512.3)
    assert a == b


def test_positions_net_across_sides(tmp_path: Path) -> None:
    broker = _broker(tmp_path)
    broker.place(_order(seq=1, qty=10), price=100.0)
    broker.place(_order(seq=2, side=Side.SELL, qty=4), price=101.0)
    assert broker.positions() == {"RELIANCE": 6}


def test_a_flat_position_disappears(tmp_path: Path) -> None:
    broker = _broker(tmp_path)
    broker.place(_order(seq=1, qty=10), price=100.0)
    broker.place(_order(seq=2, side=Side.SELL, qty=10), price=101.0)
    assert broker.positions() == {}


def test_rejected_orders_do_not_become_positions(tmp_path: Path) -> None:
    broker = _broker(tmp_path, faults=PaperFaults(reject_symbols={"RELIANCE"}))
    with pytest.raises(BrokerRejected):
        broker.place(_order(), price=100.0)
    assert broker.positions() == {}


def test_an_injected_trade_appears_as_a_position(tmp_path: Path) -> None:
    """The only way to build the case reconciliation exists for."""
    broker = _broker(tmp_path)
    broker.inject("manual", "INFY", Side.BUY, 40, 1500.0)
    assert broker.positions() == {"INFY": 40}
