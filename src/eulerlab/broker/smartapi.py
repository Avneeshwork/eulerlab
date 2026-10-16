"""Angel One SmartAPI broker adapter and historical candle client.

The SDK client is injected so the order and candle paths can be exercised
without account credentials or network access. SmartAPI orders do not expose
an idempotency guarantee through the SDK; the adapter sends a deterministic
``ordertag`` and treats ambiguous sends as unreachable so callers reconcile
before retrying.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from eulerlab.backtest.events import Order
from eulerlab.costs.schedule import Side
from eulerlab.oms.broker import BrokerError, BrokerOrderView, BrokerRejected, BrokerUnreachable

SMARTAPI_TAG_LENGTH = 20
"""SmartAPI ordertag length used for the deterministic client id marker."""

INTERVAL_MAX_DAYS: dict[str, int] = {
    "ONE_MINUTE": 30,
    "THREE_MINUTE": 60,
    "FIVE_MINUTE": 100,
    "TEN_MINUTE": 100,
    "FIFTEEN_MINUTE": 200,
    "THIRTY_MINUTE": 200,
    "ONE_HOUR": 400,
    "ONE_DAY": 2000,
}
_INDIA = ZoneInfo("Asia/Kolkata")


def _local_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("SmartAPI candle datetimes must include a timezone")
    return value.astimezone(_INDIA)


class SmartAPIClient(Protocol):
    """Methods used from Angel One's ``SmartConnect`` client."""

    def placeOrderFullResponse(self, orderparams: dict[str, Any]) -> Any: ...
    def orderBook(self) -> Any: ...
    def position(self) -> Any: ...
    def cancelOrder(self, order_id: str, variety: str) -> Any: ...
    def getCandleData(self, historicDataParams: dict[str, str]) -> Any: ...


def _data(response: Any, operation: str) -> Any:
    """Unwrap a SmartAPI response, preserving failures for the caller."""
    if not isinstance(response, Mapping):
        raise BrokerUnreachable(f"{operation} returned an invalid response")
    if response.get("status") is not True:
        message = response.get("message") or response.get("errorcode") or "request failed"
        raise BrokerUnreachable(f"SmartAPI {operation}: {message}")
    return response.get("data")


def _order_tag(client_order_id: str) -> str:
    """Encode the full engine id into SmartAPI's bounded tag field."""
    return hashlib.sha256(client_order_id.encode("utf-8")).hexdigest()[:SMARTAPI_TAG_LENGTH]


def _view(row: Mapping[str, Any], client_order_id: str | None = None) -> BrokerOrderView:
    raw_status = str(row.get("orderstatus") or row.get("status") or "").upper()
    filled = int(row.get("filledshares") or row.get("filled_quantity") or 0)
    status = {
        "COMPLETE": "complete",
        "COMPLETED": "complete",
        "CANCELLED": "cancelled",
        "REJECTED": "rejected",
    }.get(raw_status, "partial" if filled else "open")
    raw_tag = str(row.get("ordertag") or row.get("tag") or "")
    return BrokerOrderView(
        client_order_id=client_order_id or raw_tag,
        broker_order_id=str(row.get("orderid") or row.get("order_id") or ""),
        status=status,
        filled_quantity=filled,
        average_price=float(row.get("averageprice") or row.get("average_price") or 0.0),
        reason=str(row.get("text") or row.get("statusmessage") or ""),
    )


class SmartAPIBroker:
    """``BrokerAdapter`` implementation backed by Angel One SmartAPI.

    ``symbol_tokens`` maps the engine's symbol names to Angel One symbol
    tokens. Futures and options need expiry-specific mappings, so they should
    be refreshed from the Angel One scrip master rather than guessed here.
    """

    name = "smartapi"

    def __init__(
        self,
        client: SmartAPIClient,
        *,
        symbol_tokens: Mapping[str, str],
        exchange: str = "NSE",
        product_type: str = "INTRADAY",
        variety: str = "NORMAL",
    ) -> None:
        self._client = client
        self.symbol_tokens = {symbol: str(token) for symbol, token in symbol_tokens.items()}
        self.exchange = exchange.upper()
        self.product_type = product_type.upper()
        self.variety = variety.upper()

    def place(self, order: Order, *, price: float | None = None) -> str:
        del price  # The engine currently models market orders.
        token = self.symbol_tokens.get(order.symbol)
        if not token:
            raise BrokerRejected(f"no SmartAPI symbol token configured for {order.symbol}")
        params: dict[str, Any] = {
            "variety": self.variety,
            "tradingsymbol": order.symbol,
            "symboltoken": token,
            "transactiontype": "BUY" if order.side is Side.BUY else "SELL",
            "exchange": self.exchange,
            "ordertype": "MARKET",
            "producttype": self.product_type,
            "duration": "DAY",
            "price": "0",
            "squareoff": "0",
            "stoploss": "0",
            "quantity": str(int(abs(order.quantity))),
            "ordertag": _order_tag(order.client_order_id),
        }
        try:
            response = self._client.placeOrderFullResponse(params)
        except (ValueError, KeyError, TypeError) as exc:
            raise BrokerRejected(f"malformed SmartAPI order: {exc}") from exc
        except Exception as exc:
            raise BrokerUnreachable(
                f"ambiguous SmartAPI send: {type(exc).__name__}: {exc}"
            ) from exc

        # Some SDK versions return the order id directly; FullResponse returns
        # the status/data envelope. Empty or malformed success is ambiguous.
        if isinstance(response, str) and response:
            return response
        if isinstance(response, Mapping):
            if response.get("status") is False:
                message = response.get("message") or response.get("errorcode") or "rejected"
                raise BrokerRejected(f"SmartAPI order: {message}")
            data = response.get("data")
            if isinstance(data, Mapping):
                order_id = data.get("orderid")
                if order_id:
                    return str(order_id)
        raise BrokerUnreachable("SmartAPI returned no order id")

    def query(self, client_order_id: str) -> BrokerOrderView | None:
        try:
            rows = _data(self._client.orderBook(), "order lookup") or []
        except BrokerError:
            raise
        except Exception as exc:
            raise BrokerUnreachable(f"order lookup failed: {exc}") from exc
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise BrokerUnreachable("SmartAPI order book returned invalid data")
        wanted = _order_tag(client_order_id)
        for row in rows:
            if (
                isinstance(row, Mapping)
                and str(row.get("ordertag") or row.get("tag") or "") == wanted
            ):
                return _view(row, client_order_id)
        return None

    def cancel(self, client_order_id: str) -> None:
        view = self.query(client_order_id)
        if view is None or not view.broker_order_id:
            return
        try:
            _data(self._client.cancelOrder(view.broker_order_id, self.variety), "cancel")
        except BrokerError:
            raise
        except Exception as exc:
            raise BrokerUnreachable(f"cancel failed: {exc}") from exc

    def positions(self) -> dict[str, int]:
        try:
            rows = _data(self._client.position(), "positions") or []
        except BrokerError:
            raise
        except Exception as exc:
            raise BrokerUnreachable(f"positions lookup failed: {exc}") from exc
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise BrokerUnreachable("SmartAPI positions returned invalid data")
        result: dict[str, int] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            symbol = str(row.get("tradingsymbol") or "")
            quantity = int(row.get("netqty") or row.get("quantity") or 0)
            if symbol and quantity:
                result[symbol] = quantity
        return result

    def open_orders(self) -> list[BrokerOrderView]:
        try:
            rows = _data(self._client.orderBook(), "open orders") or []
        except BrokerError:
            raise
        except Exception as exc:
            raise BrokerUnreachable(f"open order lookup failed: {exc}") from exc
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise BrokerUnreachable("SmartAPI order book returned invalid data")
        terminal = {"COMPLETE", "COMPLETED", "CANCELLED", "REJECTED"}
        return [
            _view(row)
            for row in rows
            if isinstance(row, Mapping)
            and str(row.get("orderstatus") or row.get("status") or "").upper() not in terminal
        ]

    def candles(
        self,
        *,
        symbol_token: str,
        start: datetime,
        end: datetime,
        interval: str = "ONE_MINUTE",
        exchange: str | None = None,
    ) -> list[list[Any]]:
        """Fetch one bounded candle range; use ``candle_windows`` to backfill.

        Returned rows are ``[timestamp, open, high, low, close, volume]`` as
        supplied by SmartAPI. Minute requests are also subject to SmartAPI's
        8,000-record cap, so callers may need shorter windows than 30 days.
        """
        normalized = interval.upper()
        if normalized not in INTERVAL_MAX_DAYS:
            raise ValueError(f"unsupported SmartAPI candle interval: {interval}")
        if end < start:
            raise ValueError("candle end must not be before start")
        if end - start > timedelta(days=INTERVAL_MAX_DAYS[normalized]):
            raise ValueError(
                f"{normalized} requests are limited to {INTERVAL_MAX_DAYS[normalized]} days"
            )
        params = {
            "exchange": (exchange or self.exchange).upper(),
            "symboltoken": str(symbol_token),
            "interval": normalized,
            "fromdate": _local_datetime(start).strftime("%Y-%m-%d %H:%M"),
            "todate": _local_datetime(end).strftime("%Y-%m-%d %H:%M"),
        }
        try:
            rows = _data(self._client.getCandleData(params), "historical candles")
        except BrokerError:
            raise
        except Exception as exc:
            raise BrokerUnreachable(f"historical candle request failed: {exc}") from exc
        if rows is None:
            return []
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise BrokerUnreachable("SmartAPI candle response returned invalid data")
        return [list(row) for row in rows if isinstance(row, Sequence)]


def candle_windows(
    start: datetime, end: datetime, interval: str = "ONE_MINUTE"
) -> list[tuple[datetime, datetime]]:
    """Split a long history range into SmartAPI's documented maximum windows."""
    normalized = interval.upper()
    if normalized not in INTERVAL_MAX_DAYS:
        raise ValueError(f"unsupported SmartAPI candle interval: {interval}")
    if end < start:
        raise ValueError("candle end must not be before start")
    start = _local_datetime(start)
    end = _local_datetime(end)
    maximum = timedelta(days=INTERVAL_MAX_DAYS[normalized])
    step = {
        "ONE_MINUTE": timedelta(minutes=1),
        "THREE_MINUTE": timedelta(minutes=3),
        "FIVE_MINUTE": timedelta(minutes=5),
        "TEN_MINUTE": timedelta(minutes=10),
        "FIFTEEN_MINUTE": timedelta(minutes=15),
        "THIRTY_MINUTE": timedelta(minutes=30),
        "ONE_HOUR": timedelta(hours=1),
        "ONE_DAY": timedelta(days=1),
    }[normalized]
    windows: list[tuple[datetime, datetime]] = []
    cursor = start
    while cursor < end:
        stop = min(cursor + maximum, end)
        windows.append((cursor, stop))
        cursor = stop + step
    if not windows:
        windows.append((start, end))
    return windows
