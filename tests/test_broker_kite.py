"""The Kite adapter, exercised entirely against fakes.

No network, no API key, no live session — none of which exist in CI, and all of
which would make these tests skip exactly when they matter.

Every test here is about a failure mode. The happy path is one line; the rest is
what the adapter does when Kite times out, returns nothing, or reports a status
nobody has seen before. That ratio is deliberate: the mechanics were ported from
a system that already had them right, and the error handling is the part being
added.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from eulerlab.backtest.events import Order
from eulerlab.broker.kite import TAG_LIMIT, KiteBroker
from eulerlab.costs.schedule import Side
from eulerlab.oms.broker import BrokerRejected, BrokerUnreachable


class FakeKite:
    """Records what it was asked and returns what it was told to."""

    def __init__(
        self,
        *,
        order_id: str | None = "240821000123",
        raises: Exception | None = None,
        orders_rows: list[dict[str, Any]] | None = None,
        positions_book: dict[str, list[dict[str, Any]]] | None = None,
        gtt: dict[str, Any] | None = None,
    ) -> None:
        self.order_id = order_id
        self.raises = raises
        self.orders_rows = orders_rows or []
        self.positions_book = positions_book or {"net": []}
        self.gtt = gtt if gtt is not None else {"trigger_id": 55}
        self.sent: list[dict[str, Any]] = []

    def place_order(self, **kwargs: Any) -> str:
        self.sent.append(kwargs)
        if self.raises:
            raise self.raises
        return self.order_id  # type: ignore[return-value]

    def place_gtt(self, **kwargs: Any) -> dict[str, Any]:
        self.sent.append(kwargs)
        if self.raises:
            raise self.raises
        return self.gtt

    def cancel_order(self, **kwargs: Any) -> Any:
        self.sent.append(kwargs)
        if self.raises:
            raise self.raises
        return None

    def orders(self) -> list[dict[str, Any]]:
        if self.raises:
            raise self.raises
        return self.orders_rows

    def positions(self) -> dict[str, list[dict[str, Any]]]:
        if self.raises:
            raise self.raises
        return self.positions_book


def _order(coid: str = "abc123", side: Side = Side.BUY, quantity: int = 10) -> Order:
    return Order(
        client_order_id=coid,
        strategy_id="momentum",
        signal_day=date(2026, 8, 21),
        symbol="RELIANCE",
        side=side,
        quantity=quantity,
    )


# --- the send -------------------------------------------------------------


def test_a_successful_send_returns_the_broker_id() -> None:
    kite = FakeKite()
    assert KiteBroker(kite).place(_order()) == "240821000123"


def test_the_client_order_id_travels_as_the_tag() -> None:
    """This is what lets `query` find our own order after a crash, with no
    local state surviving."""
    kite = FakeKite()
    KiteBroker(kite).place(_order("deadbeef"))
    assert kite.sent[0]["tag"] == "deadbeef"


def test_a_long_id_is_truncated_the_same_way_on_send_and_lookup() -> None:
    """Kite truncates tags past 20 characters. If we wrote long and read long,
    the lookup would find nothing — and "found nothing" is what turns an
    UNKNOWN order into UNSENT, i.e. into a retry."""
    long_id = "x" * 40
    kite = FakeKite(orders_rows=[{"tag": long_id[:TAG_LIMIT], "order_id": "1", "status": "OPEN"}])
    broker = KiteBroker(kite)

    broker.place(_order(long_id))
    assert kite.sent[0]["tag"] == long_id[:TAG_LIMIT]

    found = broker.query(long_id)
    assert found is not None
    assert found.broker_order_id == "1"


def test_a_timeout_is_unreachable_not_rejected() -> None:
    """The distinction the whole adapter exists for. A timeout means the order
    may be resting at the exchange; calling it a rejection is what lets a retry
    double-send."""
    kite = FakeKite(raises=OSError("read timed out"))
    with pytest.raises(BrokerUnreachable):
        KiteBroker(kite).place(_order())


def test_insufficient_funds_is_a_definite_rejection() -> None:
    """Kite raises the same exception type for 'cannot afford' and 'connection
    dropped'. Only the first is safe to treat as terminal."""
    kite = FakeKite(raises=RuntimeError("Insufficient funds for this order"))
    with pytest.raises(BrokerRejected):
        KiteBroker(kite).place(_order())


def test_a_malformed_order_is_rejected_not_ambiguous() -> None:
    kite = FakeKite(raises=ValueError("quantity must be positive"))
    with pytest.raises(BrokerRejected):
        KiteBroker(kite).place(_order())


def test_an_empty_order_id_is_ambiguous() -> None:
    """A send that returned nothing did not obviously fail, so it is not a
    rejection — it is a question."""
    kite = FakeKite(order_id=None)
    with pytest.raises(BrokerUnreachable):
        KiteBroker(kite).place(_order())


def test_the_product_defaults_to_intraday_not_delivery() -> None:
    """Trade's adapter hardcoded CNC, which silently turned every intraday
    signal into a delivery trade — different margin, no auto-square-off."""
    kite = FakeKite()
    KiteBroker(kite).place(_order())
    assert kite.sent[0]["product"] == "MIS"


def test_side_maps_to_kite_transaction_type() -> None:
    kite = FakeKite()
    broker = KiteBroker(kite)
    broker.place(_order(side=Side.BUY))
    broker.place(_order(side=Side.SELL))
    assert [row["transaction_type"] for row in kite.sent] == ["BUY", "SELL"]


# --- the query ------------------------------------------------------------


def test_a_failed_query_raises_rather_than_reporting_absence() -> None:
    """`None` from `query` means UNSENT, which is a strong claim. An
    unanswerable question must never be answered with 'it does not exist'."""
    kite = FakeKite(raises=OSError("connection reset"))
    with pytest.raises(BrokerUnreachable):
        KiteBroker(kite).query("abc123")


def test_a_successful_query_that_finds_nothing_returns_none() -> None:
    kite = FakeKite(orders_rows=[{"tag": "somethingelse", "order_id": "9", "status": "OPEN"}])
    assert KiteBroker(kite).query("abc123") is None


def test_an_unrecognised_status_is_open_never_terminal() -> None:
    """Guessing 'complete' from a status nobody has seen would resolve an
    UNKNOWN order into a fill that may not exist."""
    kite = FakeKite(
        orders_rows=[{"tag": "abc123", "order_id": "1", "status": "SOME_NEW_KITE_STATUS"}]
    )
    view = KiteBroker(kite).query("abc123")
    assert view is not None
    assert view.status == "open"


@pytest.mark.parametrize(
    ("kite_status", "expected"),
    [("COMPLETE", "complete"), ("REJECTED", "rejected"), ("CANCELLED", "rejected")],
)
def test_known_statuses_map_as_expected(kite_status: str, expected: str) -> None:
    kite = FakeKite(orders_rows=[{"tag": "abc123", "order_id": "1", "status": kite_status}])
    view = KiteBroker(kite).query("abc123")
    assert view is not None
    assert view.status == expected


# --- positions and open orders --------------------------------------------


def test_positions_read_the_net_book_not_the_day_book() -> None:
    """A position carried from yesterday is still a position. Reading the day
    book would report it as a break we did not create."""
    kite = FakeKite(
        positions_book={
            "net": [{"tradingsymbol": "RELIANCE", "quantity": 40}],
            "day": [{"tradingsymbol": "RELIANCE", "quantity": 0}],
        }
    )
    assert KiteBroker(kite).positions() == {"RELIANCE": 40}


def test_a_flat_position_is_omitted() -> None:
    kite = FakeKite(positions_book={"net": [{"tradingsymbol": "TCS", "quantity": 0}]})
    assert KiteBroker(kite).positions() == {}


def test_open_orders_include_ones_we_never_sent() -> None:
    """An order with a tag we do not recognise is the `unknown_order` break the
    reconciler exists to catch. Filtering to our own tags would hide exactly the
    risk we did not create."""
    kite = FakeKite(
        orders_rows=[
            {"tag": "ours", "order_id": "1", "status": "OPEN"},
            {"tag": "", "order_id": "2", "status": "OPEN"},
            {"tag": "ours2", "order_id": "3", "status": "COMPLETE"},
        ]
    )
    live = KiteBroker(kite).open_orders()
    assert {row.broker_order_id for row in live} == {"1", "2"}


# --- the bracket ----------------------------------------------------------


def test_the_bracket_legs_exit_the_position() -> None:
    """Ported from Trade, which had this right: both legs carry the OPPOSITE
    transaction type to the entry, because they close it."""
    kite = FakeKite()
    KiteBroker(kite).place_bracket(_order(side=Side.BUY), stop=90.0, target=110.0, last_price=100.0)
    legs = kite.sent[0]["orders"]
    assert [leg["transaction_type"] for leg in legs] == ["SELL", "SELL"]
    assert kite.sent[0]["trigger_values"] == [90.0, 110.0]


def test_a_gtt_with_no_trigger_id_is_ambiguous() -> None:
    kite = FakeKite(gtt={})
    with pytest.raises(BrokerUnreachable):
        KiteBroker(kite).place_bracket(_order(), stop=90.0, target=110.0, last_price=100.0)


def test_it_actually_satisfies_the_broker_adapter_protocol() -> None:
    """The point of the port. `OMS` and the reconciler accept any
    `BrokerAdapter`, so conformance is what lets the live adapter drop into the
    same order path the paper broker uses — unchanged, which is the rule the
    whole project rests on.

    Asserted as a typed binding so mypy checks it too: a missing method or a
    changed signature fails the type gate, not just this test.
    """
    from eulerlab.oms.broker import BrokerAdapter

    adapter: BrokerAdapter = KiteBroker(FakeKite())
    assert adapter.name == "kite"
