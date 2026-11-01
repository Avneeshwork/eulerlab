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
from eulerlab.oms.broker import BrokerRejected, BrokerUnreachable, DuplicateOrder


class FakeKite:
    """Records what it was asked and returns what it was told to."""

    def __init__(
        self,
        *,
        order_id: str | None = "240821000123",
        raises: Exception | None = None,
        orders_raises: Exception | None = None,
        orders_rows: list[dict[str, Any]] | None = None,
        positions_book: dict[str, list[dict[str, Any]]] | None = None,
        holdings_rows: list[dict[str, Any]] | None = None,
        holdings_raises: Exception | None = None,
        gtt: dict[str, Any] | None = None,
    ) -> None:
        self.order_id = order_id
        self.raises = raises
        self.orders_raises = orders_raises
        self.orders_rows = orders_rows or []
        self.positions_book = positions_book or {"net": []}
        self.holdings_rows = holdings_rows or []
        self.holdings_raises = holdings_raises
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
        if self.orders_raises:
            raise self.orders_raises
        return self.orders_rows

    def positions(self) -> dict[str, list[dict[str, Any]]]:
        if self.raises:
            raise self.raises
        return self.positions_book

    def holdings(self) -> list[dict[str, Any]]:
        if self.holdings_raises:
            raise self.holdings_raises
        return self.holdings_rows


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
    kite = FakeKite()
    broker = KiteBroker(kite)

    broker.place(_order(long_id))
    assert kite.sent[0]["tag"] == long_id[:TAG_LIMIT]
    kite.orders_rows = [{"tag": long_id[:TAG_LIMIT], "order_id": "1", "status": "OPEN"}]

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
    kite = FakeKite(orders_raises=OSError("connection reset"))
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


# --- the duplicate check (T-4348) ------------------------------------------


@pytest.mark.parametrize("status", ["OPEN", "COMPLETE", "TRIGGER PENDING"])
def test_a_tag_already_in_the_book_is_not_sent_again(status: str) -> None:
    """Kite accepts a second order with the same tag, so the adapter refuses
    it itself. `ems.send` reads this as "the original is fine"."""
    kite = FakeKite(orders_rows=[{"tag": "abc123", "order_id": "7", "status": status}])
    with pytest.raises(DuplicateOrder):
        KiteBroker(kite).place(_order("abc123"))
    assert kite.sent == []


def test_a_rejected_order_with_the_same_tag_does_not_block_a_send() -> None:
    kite = FakeKite(orders_rows=[{"tag": "abc123", "order_id": "7", "status": "REJECTED"}])
    assert KiteBroker(kite).place(_order("abc123")) == "240821000123"
    assert len(kite.sent) == 1


def test_an_unreadable_book_sends_nothing_and_says_so() -> None:
    """Not being able to check is a definite refusal, not an ambiguity: the
    order never left this process."""
    kite = FakeKite(orders_raises=OSError("read timed out"))
    with pytest.raises(BrokerRejected, match="not sent"):
        KiteBroker(kite).place(_order())
    assert kite.sent == []


def test_ems_reads_the_duplicate_as_the_original_landing() -> None:
    from eulerlab.oms import ems
    from eulerlab.oms.states import Event

    kite = FakeKite(orders_rows=[{"tag": "abc123", "order_id": "7", "status": "OPEN"}])
    outcome = ems.send(KiteBroker(kite), _order("abc123"))
    assert outcome.event is Event.SEND_OK
    assert kite.sent == []


# --- delivery holdings (T-4364) --------------------------------------------


def _holding(
    symbol: str, *, opening: int, quantity: int, t1: int = 0, used: int = 0
) -> dict[str, Any]:
    return {
        "tradingsymbol": symbol,
        "opening_quantity": opening,
        "quantity": quantity,
        "t1_quantity": t1,
        "used_quantity": used,
    }


def _sale(symbol: str, quantity: int) -> dict[str, Any]:
    return {"tradingsymbol": symbol, "quantity": -quantity, "product": "CNC"}


def test_a_carried_delivery_holding_is_a_position() -> None:
    """Bought CNC yesterday: Kite moved it out of `net` into `holdings` as T1."""
    kite = FakeKite(holdings_rows=[_holding("INFY", opening=25, quantity=0, t1=25)])
    assert KiteBroker(kite).positions() == {"INFY": 25}


def test_settled_and_undelivered_quantities_both_count() -> None:
    kite = FakeKite(holdings_rows=[_holding("TCS", opening=15, quantity=10, t1=5)])
    assert KiteBroker(kite).positions() == {"TCS": 15}


def test_todays_buy_adds_to_a_holding() -> None:
    kite = FakeKite(
        holdings_rows=[_holding("TCS", opening=10, quantity=10)],
        positions_book={"net": [{"tradingsymbol": "TCS", "quantity": 4, "product": "CNC"}]},
    )
    assert KiteBroker(kite).positions() == {"TCS": 14}


def test_a_partial_sale_counts_once_when_kite_lowers_quantity() -> None:
    """Forum 16259's example: 100 held, 40 sold, `quantity` 60, `used_quantity`
    40, net -40. Adding `quantity` to net gave 20 (HISTORY #55)."""
    kite = FakeKite(
        holdings_rows=[_holding("TCS", opening=100, quantity=60, used=40)],
        positions_book={"net": [_sale("TCS", 40)]},
    )
    assert KiteBroker(kite).positions() == {"TCS": 60}


def test_a_sale_shown_any_other_way_is_refused_not_guessed() -> None:
    """No source says Kite ever keeps `quantity` after a sale. If it did, the
    fields would not add up, and the adapter says so rather than picking."""
    kite = FakeKite(
        holdings_rows=[_holding("TCS", opening=100, quantity=100, used=40)],
        positions_book={"net": [_sale("TCS", 40)]},
    )
    with pytest.raises(BrokerUnreachable, match="do not add up"):
        KiteBroker(kite).positions()


def test_a_sale_from_settled_shares_with_t1_shares_held() -> None:
    """Forum 16275: 60 settled + 40 T1, sell 50: quantity 10, t1 40, used 50."""
    kite = FakeKite(
        holdings_rows=[_holding("TCS", opening=100, quantity=10, t1=40, used=50)],
        positions_book={"net": [_sale("TCS", 50)]},
    )
    assert KiteBroker(kite).positions() == {"TCS": 50}


def test_selling_a_whole_holding_today_leaves_nothing() -> None:
    kite = FakeKite(
        holdings_rows=[_holding("TCS", opening=10, quantity=0, used=10)],
        positions_book={"net": [_sale("TCS", 10)]},
    )
    assert KiteBroker(kite).positions() == {}


def test_selling_undelivered_t1_shares_counts_once() -> None:
    """A 2017 staff reply: a T1 sale is taken off `t1_quantity` at once."""
    kite = FakeKite(
        holdings_rows=[_holding("SBIN", opening=40, quantity=20, t1=0, used=20)],
        positions_book={"net": [_sale("SBIN", 20)]},
    )
    assert KiteBroker(kite).positions() == {"SBIN": 20}


def test_a_holding_that_does_not_add_up_is_unreachable_not_guessed() -> None:
    kite = FakeKite(holdings_rows=[_holding("TCS", opening=100, quantity=50, used=10)])
    with pytest.raises(BrokerUnreachable, match="do not add up"):
        KiteBroker(kite).positions()


def test_a_holding_without_an_opening_quantity_is_unreachable() -> None:
    kite = FakeKite(holdings_rows=[{"tradingsymbol": "TCS", "quantity": 10, "t1_quantity": 0}])
    with pytest.raises(BrokerUnreachable, match="opening_quantity"):
        KiteBroker(kite).positions()


def test_an_intraday_position_with_no_holdings_reads_as_before() -> None:
    kite = FakeKite(
        positions_book={"net": [{"tradingsymbol": "SBIN", "quantity": 30, "product": "MIS"}]}
    )
    assert KiteBroker(kite).positions() == {"SBIN": 30}


def test_an_unreadable_holdings_book_is_unreachable_not_empty() -> None:
    """Returning the net book alone would read as every carried stock sold."""
    kite = FakeKite(
        positions_book={"net": [{"tradingsymbol": "SBIN", "quantity": 30}]},
        holdings_raises=OSError("read timed out"),
    )
    with pytest.raises(BrokerUnreachable):
        KiteBroker(kite).positions()


def test_a_margin_traded_holding_is_refused_not_miscounted() -> None:
    """Kite's mock holdings row: quantity 1, opening_quantity 1, mtf.quantity 1000."""
    row = _holding("AARON", opening=1, quantity=1)
    row["mtf"] = {"quantity": 1000, "used_quantity": 0}
    with pytest.raises(BrokerUnreachable, match="MTF"):
        KiteBroker(FakeKite(holdings_rows=[row])).positions()


def test_kites_own_mock_holdings_read_as_expected() -> None:
    """Rows shaped like zerodha/kiteconnect-mocks holdings.json (SBIN on BSE)."""
    row = _holding("SBIN", opening=16, quantity=16)
    row.update({"realised_quantity": 16, "short_quantity": 0, "mtf": {"quantity": 0}})
    assert KiteBroker(FakeKite(holdings_rows=[row])).positions() == {"SBIN": 16}
