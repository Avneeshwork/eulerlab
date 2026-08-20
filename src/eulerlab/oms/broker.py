"""What a broker looks like from here, and the three ways a send can end.

`CLAUDE.md`: *The broker is the source of truth. Local position state is a
cache.*

The interface is written to make that true rather than to assume it. Every
adapter must answer `query`, `open_orders` and `positions`, because a system
that can only *send* has no way to find out what it actually did, and its
local view can never be corrected — it can only drift.

**Three outcomes, three exception types.** The distinction between them is the
whole reason `UNKNOWN` exists in the state machine:

- returns normally — it landed
- `BrokerRejected` — it definitely did not land, and the broker said why
- `BrokerUnreachable` — *we do not know*

An adapter that collapses the third case into the second is actively
dangerous: the caller will retry an order that may already be resting at the
exchange. So `BrokerUnreachable` is the default for any error an adapter
cannot positively classify, and adapters are expected to be conservative about
claiming certainty.

`DuplicateOrder` is a rejection, and a welcome one. It is the broker enforcing
the idempotency that deterministic client order ids exist to make possible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from eulerlab.backtest.events import Order
from eulerlab.oms.states import Event


class BrokerError(Exception):
    """Base. Never raised directly — the subclass carries the meaning."""


class BrokerRejected(BrokerError):
    """The broker saw the order and refused it. Definite."""


class DuplicateOrder(BrokerRejected):
    """This client order id already exists at the broker.

    A rejection, and the one we want: it is the broker refusing a double-send
    that a retry would otherwise have caused. Callers treat it as evidence the
    original is live, not as a failure.
    """


class BrokerUnreachable(BrokerError):
    """We do not know whether the order landed.

    The honest default for timeouts, resets, and anything unclassifiable.
    """


@dataclass(frozen=True)
class BrokerOrderView:
    """The broker's own account of one order. Authoritative by definition."""

    client_order_id: str
    broker_order_id: str
    status: str
    filled_quantity: int
    average_price: float
    reason: str = ""

    def event(self) -> Event:
        """Translate the broker's vocabulary into a resolution event.

        Only ever used to resolve an `UNKNOWN` order, which is why every
        result maps to a `QUERY_*` event. The mapping lives here, in one
        place, so a second adapter cannot invent a different reading of the
        word "complete".
        """
        return {
            "open": Event.QUERY_FOUND_RESTING,
            "partial": Event.QUERY_FOUND_PARTIAL,
            "complete": Event.QUERY_FOUND_FILLED,
            "cancelled": Event.QUERY_FOUND_CANCELLED,
            "rejected": Event.QUERY_FOUND_REJECTED,
        }[self.status]


@runtime_checkable
class BrokerAdapter(Protocol):
    """The whole surface. Deliberately small.

    Small because every method here has to be implemented correctly by every
    future adapter, on a bad day, against a real API. `place`, `query`,
    `cancel`, `positions`, `open_orders` — anything richer belongs above this
    line, where it is written once and tested once.
    """

    name: str

    def place(self, order: Order, *, price: float | None = None) -> str:
        """Send it. Returns the broker's order id.

        Raises `BrokerRejected` when the broker definitely refused, and
        `BrokerUnreachable` when the outcome is unknown.
        """
        ...

    def query(self, client_order_id: str) -> BrokerOrderView | None:
        """The broker's account of one order, or `None` if it has never seen it.

        `None` is a strong statement — it is what turns an `UNKNOWN` order into
        `UNSENT` — so an adapter must return it only on a successful query that
        found nothing, and raise `BrokerUnreachable` if the query itself failed.
        """
        ...

    def cancel(self, client_order_id: str) -> None: ...

    def positions(self) -> dict[str, int]:
        """Holdings by symbol, as the broker has them. The source of truth."""
        ...

    def open_orders(self) -> list[BrokerOrderView]:
        """Everything the broker considers live, including orders we may not
        know about — which is the case reconciliation exists to catch."""
        ...
