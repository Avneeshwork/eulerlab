"""The first live broker adapter: Zerodha Kite.

Closes S-015 — until now the only adapter was `PaperBroker`, a simulator, so
nothing in this project had ever said anything about real fills, real latency
or real rejection reasons.

**The order mechanics are ported from `~/Documents/Trade`, which had them
right.** That system's `place_order` builds regular market orders and two-leg
OCO GTT brackets against Kite correctly, and knows things that are only learned
by running against the real API: that a GTT bracket is two `orders` entries
with the *opposite* transaction type, that the trigger needs a `last_price`,
and that limit legs want a small offset from the trigger so they actually fill.
None of that is guessable from the documentation alone, and it is kept here
essentially unchanged.

**What is not ported is its error handling**, because this project's contract
already demands better. `BrokerAdapter` requires three outcomes, expressed as:

- return normally  — it landed
- `BrokerRejected` — the broker definitely refused
- `BrokerUnreachable` — *we do not know*, and only a query can say

Trade's version returned `None` for all three, which is what made a network
timeout indistinguishable from a rejection and let a retry double-send. Here
the distinction is structural: the caller cannot accidentally treat an
ambiguous send as a failure, because the two arrive as different exceptions.

**`client_order_id` travels as the Kite order tag.** Kite caps tags at 20
characters, so a longer id is truncated — and `query` compares on the same
truncation so the two always agree. This is what makes `query` able to find our
own order after a crash without any local state surviving.
"""

from __future__ import annotations

from typing import Any, Protocol

from eulerlab.backtest.events import Order
from eulerlab.costs.schedule import Side
from eulerlab.oms.broker import (
    BrokerOrderView,
    BrokerRejected,
    BrokerUnreachable,
    DuplicateOrder,
)

TAG_LIMIT = 20
"""Kite truncates order tags beyond this. Applied on both send and lookup so
they cannot disagree — a tag written long and read short finds nothing, and
"found nothing" is what turns an UNKNOWN order into UNSENT."""


class KiteClient(Protocol):
    """Just the parts of `kiteconnect.KiteConnect` used here.

    A protocol rather than the concrete class so the adapter can be tested
    without a network, a key, or a live session — none of which exist in CI.
    """

    def place_order(self, **kwargs: Any) -> str: ...
    def place_gtt(self, **kwargs: Any) -> dict[str, Any]: ...
    def cancel_order(self, **kwargs: Any) -> Any: ...
    def orders(self) -> list[dict[str, Any]]: ...
    def positions(self) -> dict[str, list[dict[str, Any]]]: ...
    def holdings(self) -> list[dict[str, Any]]: ...


# Exceptions that mean the request never reached the exchange. Everything else
# raised during a send is ambiguous by definition: the socket may have closed
# after the order was accepted.
_NEVER_SENT = (ValueError, KeyError, TypeError)

# Kite's status vocabulary. Anything unrecognised is deliberately NOT mapped to
# a terminal state — an unknown status must stay unknown rather than being
# guessed into "filled".
_TERMINAL_OK = {"COMPLETE"}
_TERMINAL_REJECTED = {"REJECTED", "CANCELLED"}


class KiteBroker:
    """`BrokerAdapter` over Zerodha Kite.

    Holds no position state of its own. The broker is the source of truth and
    this class is a window onto it, which is why `positions` and `open_orders`
    both ask rather than remember.
    """

    name = "kite"

    order_book_is_daily = True
    """Kite's `orders()` holds only today's orders. Read by `OMS.resolve_unknown`:
    an order sent on an earlier day that is missing from today's book has not
    been shown never to exist, so it must not resolve as unsent (T-4349)."""

    def __init__(
        self,
        client: KiteClient,
        *,
        exchange: str = "NSE",
        product: str = "MIS",
        variety: str = "regular",
    ) -> None:
        self._kite = client
        self.exchange = exchange.upper()
        self.product = product.upper()
        """`MIS` is intraday; `CNC` takes delivery and carries overnight.

        Defaulted to MIS rather than CNC deliberately. Trade's adapter
        hardcoded CNC, which silently turned every intraday signal into a
        delivery trade with different margin, different risk and no
        auto-square-off.
        """
        self.variety = variety

    # --- sending ----------------------------------------------------------

    def place(self, order: Order, *, price: float | None = None) -> str:
        """Send a market order. Returns Kite's order id.

        `price` is accepted for protocol compatibility and ignored: the only
        order type the engine models today is market-on-close, and inventing a
        limit here would let the adapter trade differently from the backtest.
        """
        tag = order.client_order_id[:TAG_LIMIT]
        # Kite does not refuse a second order with the same tag, so the check
        # the OMS documents as its second line of defence is made here: look
        # for the tag in today's book first (T-4348). If the book cannot be
        # read, nothing is sent, which is a definite refusal and not an
        # ambiguity: this call never reached the exchange.
        try:
            today = self._kite.orders() or []
        except Exception as exc:
            raise BrokerRejected(f"not sent: could not check for a duplicate first: {exc}") from exc
        for row in today:
            if str(row.get("tag") or "") != tag:
                continue
            if str(row.get("status") or "").upper() in _TERMINAL_REJECTED:
                continue
            raise DuplicateOrder(
                f"tag {tag} is already at Kite as order {row.get('order_id')} "
                f"({row.get('status')}); not sent again"
            )
        try:
            broker_id = self._kite.place_order(
                variety=self.variety,
                exchange=self.exchange,
                tradingsymbol=order.symbol,
                transaction_type="BUY" if order.side is Side.BUY else "SELL",
                quantity=int(abs(order.quantity)),
                product=self.product,
                order_type="MARKET",
                tag=tag,
            )
        except _NEVER_SENT as exc:
            raise BrokerRejected(f"malformed order: {type(exc).__name__}: {exc}") from exc
        except Exception as exc:
            message = str(exc).lower()
            # Kite raises the same exception type for "you cannot afford this"
            # and "the connection dropped". The first is a definite refusal;
            # the second is not, and calling it one is how a retry double-sends.
            if any(
                marker in message
                for marker in ("insufficient", "margin", "invalid", "blocked", "not permitted")
            ):
                raise BrokerRejected(str(exc)) from exc
            raise BrokerUnreachable(f"ambiguous send: {type(exc).__name__}: {exc}") from exc

        if not broker_id:
            # A send that returned nothing did not obviously fail, so it is not
            # a rejection. Ask.
            raise BrokerUnreachable("Kite returned no order id")
        return str(broker_id)

    def place_bracket(
        self,
        order: Order,
        *,
        stop: float,
        target: float,
        last_price: float,
    ) -> str:
        """A two-leg OCO GTT: stop-loss and target, whichever triggers first.

        Ported from Trade, which had the shape right. The two legs carry the
        *opposite* transaction type to the entry — they exit the position — and
        each limit price is offset from its trigger so the leg actually fills
        rather than resting at a price the market has already passed through.
        """
        exit_side = "SELL" if order.side is Side.BUY else "BUY"
        offset = 0.5 if order.side is Side.BUY else -0.5
        legs = [
            {
                "exchange": self.exchange,
                "tradingsymbol": order.symbol,
                "transaction_type": exit_side,
                "order_type": "LIMIT",
                "quantity": int(abs(order.quantity)),
                "product": self.product,
                "price": round(stop - offset, 2),
            },
            {
                "exchange": self.exchange,
                "tradingsymbol": order.symbol,
                "transaction_type": exit_side,
                "order_type": "LIMIT",
                "quantity": int(abs(order.quantity)),
                "product": self.product,
                "price": round(target + offset, 2),
            },
        ]
        try:
            response = self._kite.place_gtt(
                trigger_type="two-leg",
                tradingsymbol=order.symbol,
                exchange=self.exchange,
                trigger_values=[round(stop, 2), round(target, 2)],
                last_price=round(last_price, 2),
                orders=legs,
            )
        except _NEVER_SENT as exc:
            raise BrokerRejected(f"malformed GTT: {type(exc).__name__}: {exc}") from exc
        except Exception as exc:
            raise BrokerUnreachable(f"ambiguous GTT send: {exc}") from exc

        trigger_id = response.get("trigger_id") if isinstance(response, dict) else None
        if not trigger_id:
            raise BrokerUnreachable("Kite returned no GTT trigger id")
        return str(trigger_id)

    # --- asking -----------------------------------------------------------

    def query(self, client_order_id: str) -> BrokerOrderView | None:
        """What the broker says about one of our orders.

        `None` means the query succeeded and found nothing — a strong claim,
        because it is what turns an `UNKNOWN` order into `UNSENT`. A query that
        *failed* raises instead, since an unanswerable question must never be
        answered with "it does not exist".
        """
        try:
            orders = self._kite.orders() or []
        except Exception as exc:
            raise BrokerUnreachable(f"order lookup failed: {exc}") from exc

        wanted = client_order_id[:TAG_LIMIT]
        for row in orders:
            if str(row.get("tag") or "") != wanted:
                continue
            status = str(row.get("status") or "").upper()
            return BrokerOrderView(
                client_order_id=client_order_id,
                broker_order_id=str(row.get("order_id") or ""),
                status=self._status(status),
                filled_quantity=int(row.get("filled_quantity") or 0),
                average_price=float(row.get("average_price") or 0.0),
                reason=str(row.get("status_message") or ""),
            )
        return None

    @staticmethod
    def _status(kite_status: str) -> str:
        """Kite's vocabulary, narrowed to what the state machine understands.

        An unrecognised status maps to `open`, never to a terminal state.
        Guessing "complete" from a status nobody has seen before would resolve
        an UNKNOWN order into a fill that may not exist.
        """
        if kite_status in _TERMINAL_OK:
            return "complete"
        if kite_status in _TERMINAL_REJECTED:
            return "rejected"
        return "open"

    def cancel(self, client_order_id: str) -> None:
        view = self.query(client_order_id)
        if view is None or not view.broker_order_id:
            return
        try:
            self._kite.cancel_order(variety=self.variety, order_id=view.broker_order_id)
        except Exception as exc:
            raise BrokerUnreachable(f"cancel failed: {exc}") from exc

    def positions(self) -> dict[str, int]:
        """What the account holds by symbol: the day's opening holding plus the net book.

        Kite keeps the two apart. A delivery (CNC) buy sits in `positions.net`
        on the day it fills and moves to `holdings` the next day ("Equity
        positions carried overnight move to the holdings portfolio the next
        day", RESEARCH/139). Reading `net` alone reported every carried
        delivery stock as missing (T-4364).

        A holding counts as its `opening_quantity`, the quantity carried into
        the day (settled plus T1), which a sale does not change. Today's buys
        and today's sales out of holdings are both in the net book (a sale is a
        negative CNC row), so opening plus net is the holding now. Kite also
        lowers `holdings.quantity` on the day of a sale (RESEARCH/139, forum
        16259); adding `quantity` to net, as this did first, counted every
        sale twice (HISTORY #55).

        Each holding must add up one of two ways: `quantity + t1_quantity`
        plus or not plus `used_quantity` equals `opening_quantity`. If neither
        holds, Kite is showing something this code was not built for, and the
        call raises `BrokerUnreachable` instead of guessing. Both books are
        read or neither counts.
        """
        try:
            book = self._kite.positions() or {}
            held = self._kite.holdings() or []
        except Exception as exc:
            raise BrokerUnreachable(f"positions lookup failed: {exc}") from exc

        totals: dict[str, int] = {}
        for row in held:
            symbol = str(row.get("tradingsymbol") or "")
            if not symbol:
                continue
            if row.get("opening_quantity") is None:
                raise BrokerUnreachable(f"{symbol}: holding has no opening_quantity; not guessing")
            opening = int(row["opening_quantity"])
            now = int(row.get("quantity") or 0) + int(row.get("t1_quantity") or 0)
            used = int(row.get("used_quantity") or 0)
            # ASSUMPTION: A-091. A holding adds up as quantity + t1 (+ used) = opening.
            if opening not in (now, now + used):
                msg = (
                    f"{symbol}: holdings do not add up (quantity + t1_quantity = {now}, "
                    f"used_quantity = {used}, opening_quantity = {opening}); not guessing (A-091)"
                )
                raise BrokerUnreachable(msg)
            if opening:
                totals[symbol] = totals.get(symbol, 0) + opening
        for row in book.get("net", []) or []:
            symbol = str(row.get("tradingsymbol") or "")
            quantity = int(row.get("quantity") or 0)
            if symbol and quantity:
                totals[symbol] = totals.get(symbol, 0) + quantity
        return {symbol: quantity for symbol, quantity in totals.items() if quantity}

    def open_orders(self) -> list[BrokerOrderView]:
        """Everything Kite considers live — including orders we never sent.

        An order with a tag we do not recognise is still returned. That is the
        `unknown_order` break the reconciler exists to catch, and filtering to
        our own tags would hide exactly the risk we did not create.
        """
        try:
            orders = self._kite.orders() or []
        except Exception as exc:
            raise BrokerUnreachable(f"open order lookup failed: {exc}") from exc

        live: list[BrokerOrderView] = []
        for row in orders:
            status = str(row.get("status") or "").upper()
            if status in _TERMINAL_OK or status in _TERMINAL_REJECTED:
                continue
            live.append(
                BrokerOrderView(
                    client_order_id=str(row.get("tag") or ""),
                    broker_order_id=str(row.get("order_id") or ""),
                    status=self._status(status),
                    filled_quantity=int(row.get("filled_quantity") or 0),
                    average_price=float(row.get("average_price") or 0.0),
                    reason=str(row.get("status_message") or ""),
                )
            )
        return live
