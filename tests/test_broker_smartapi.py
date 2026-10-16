"""SmartAPI adapter behavior using an in-memory fake client."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest

from eulerlab.backtest.events import Order
from eulerlab.broker.smartapi import SmartAPIBroker, _order_tag, candle_windows
from eulerlab.costs.schedule import Side
from eulerlab.oms.broker import BrokerAdapter, BrokerRejected, BrokerUnreachable

IST = timezone(timedelta(hours=5, minutes=30))


class FakeSmartAPI:
    def __init__(self) -> None:
        self.order_response: Any = {"status": True, "data": {"orderid": "A123"}}
        self.order_rows: list[dict[str, Any]] = []
        self.position_rows: list[dict[str, Any]] = []
        self.candle_rows: list[list[Any]] = []
        self.sent: list[dict[str, Any]] = []
        self.cancelled: list[tuple[str, str]] = []
        self.raise_on: str | None = None

    def _check(self, operation: str) -> None:
        if self.raise_on == operation:
            raise TimeoutError("socket timed out")

    def placeOrderFullResponse(self, orderparams: dict[str, Any]) -> Any:
        self._check("place")
        self.sent.append(orderparams)
        return self.order_response

    def orderBook(self) -> dict[str, Any]:
        self._check("orders")
        if self.raise_on == "orders-refused":
            return {"status": False, "message": "session expired"}
        return {"status": True, "data": self.order_rows}

    def position(self) -> dict[str, Any]:
        self._check("positions")
        return {"status": True, "data": self.position_rows}

    def cancelOrder(self, order_id: str, variety: str) -> dict[str, Any]:
        self._check("cancel")
        self.cancelled.append((order_id, variety))
        return {"status": True, "data": None}

    def getCandleData(self, params: dict[str, str]) -> dict[str, Any]:
        self._check("candles")
        self.sent.append(params)
        return {"status": True, "data": self.candle_rows}


def _order(coid: str = "engine-order-123", side: Side = Side.BUY) -> Order:
    return Order(
        client_order_id=coid,
        strategy_id="momentum",
        signal_day=date(2026, 8, 21),
        symbol="GOLD26DECFUT",
        side=side,
        quantity=2,
    )


def _broker(client: FakeSmartAPI) -> SmartAPIBroker:
    return SmartAPIBroker(
        client,
        symbol_tokens={"GOLD26DECFUT": "555001"},
        exchange="MCX",
        product_type="CARRYFORWARD",
    )


def test_place_sends_mcxtoken_and_deterministic_order_tag() -> None:
    client = FakeSmartAPI()
    assert _broker(client).place(_order()) == "A123"
    sent = client.sent[0]
    assert sent["exchange"] == "MCX"
    assert sent["symboltoken"] == "555001"
    assert sent["producttype"] == "CARRYFORWARD"
    assert sent["ordertag"] == _order_tag("engine-order-123")
    assert sent["transactiontype"] == "BUY"


def test_missing_symbol_token_is_rejected_before_sending() -> None:
    client = FakeSmartAPI()
    broker = SmartAPIBroker(client, symbol_tokens={}, exchange="MCX")
    with pytest.raises(BrokerRejected, match="no SmartAPI symbol token"):
        broker.place(_order())
    assert client.sent == []


def test_ambiguous_order_send_is_unreachable() -> None:
    client = FakeSmartAPI()
    client.raise_on = "place"
    with pytest.raises(BrokerUnreachable, match="ambiguous SmartAPI send"):
        _broker(client).place(_order())


def test_empty_order_id_is_ambiguous_and_api_refusal_is_rejected() -> None:
    client = FakeSmartAPI()
    client.order_response = {"status": True, "data": {}}
    with pytest.raises(BrokerUnreachable):
        _broker(client).place(_order())

    client.order_response = {"status": False, "message": "Insufficient funds"}
    with pytest.raises(BrokerRejected, match="Insufficient funds"):
        _broker(client).place(_order())


def test_query_maps_partial_fills_and_matches_order_tag() -> None:
    client = FakeSmartAPI()
    client.order_rows = [
        {
            "ordertag": _order_tag("engine-order-123"),
            "orderid": "A123",
            "orderstatus": "open",
            "filledshares": "1",
            "averageprice": "80200.5",
        }
    ]
    view = _broker(client).query("engine-order-123")
    assert view is not None
    assert view.status == "partial"
    assert view.filled_quantity == 1
    assert view.average_price == 80200.5


def test_query_failure_is_not_reported_as_absence() -> None:
    client = FakeSmartAPI()
    client.raise_on = "orders"
    with pytest.raises(BrokerUnreachable):
        _broker(client).query("not-found")

    client.raise_on = "orders-refused"
    with pytest.raises(BrokerUnreachable, match="session expired"):
        _broker(client).query("not-found")


def test_cancel_queries_then_uses_smartapi_argument_order() -> None:
    client = FakeSmartAPI()
    client.order_rows = [
        {"ordertag": _order_tag("engine-order-123"), "orderid": "A123", "orderstatus": "open"}
    ]
    _broker(client).cancel("engine-order-123")
    assert client.cancelled == [("A123", "NORMAL")]


def test_positions_and_open_orders_use_broker_book() -> None:
    client = FakeSmartAPI()
    client.position_rows = [{"tradingsymbol": "GOLD26DECFUT", "netqty": "2"}]
    client.order_rows = [
        {"orderid": "open", "orderstatus": "open", "ordertag": "other"},
        {"orderid": "done", "orderstatus": "complete"},
    ]
    broker = _broker(client)
    assert broker.positions() == {"GOLD26DECFUT": 2}
    assert [row.broker_order_id for row in broker.open_orders()] == ["open"]


def test_minute_candle_fetch_uses_documented_request_shape() -> None:
    client = FakeSmartAPI()
    client.candle_rows = [["2026-10-15T09:00:00+05:30", 1, 2, 0.5, 1.5, 100]]
    rows = _broker(client).candles(
        symbol_token="555001",
        start=datetime(2026, 10, 15, 9, 0, tzinfo=IST),
        end=datetime(2026, 10, 15, 9, 1, tzinfo=IST),
    )
    assert len(rows) == 1
    assert client.sent[0] == {
        "exchange": "MCX",
        "symboltoken": "555001",
        "interval": "ONE_MINUTE",
        "fromdate": "2026-10-15 09:00",
        "todate": "2026-10-15 09:01",
    }


def test_candle_request_limit_and_multi_year_windows() -> None:
    client = FakeSmartAPI()
    with pytest.raises(ValueError, match="limited to 30 days"):
        _broker(client).candles(
            symbol_token="1",
            start=datetime(2026, 1, 1, tzinfo=IST),
            end=datetime(2026, 2, 1, tzinfo=IST),
        )
    windows = candle_windows(datetime(2021, 1, 1, tzinfo=IST), datetime(2026, 1, 1, tzinfo=IST))
    assert len(windows) == 61
    assert windows[0][1] - windows[0][0] == timedelta(days=30)


def test_adapter_matches_broker_protocol() -> None:
    adapter: BrokerAdapter = _broker(FakeSmartAPI())
    assert adapter.name == "smartapi"
