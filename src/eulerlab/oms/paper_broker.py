"""A simulated broker with its own durable state.

**Its state lives in a separate file from ours, and that is the point.** A
paper broker implemented as a dictionary inside the OMS process would make
every reconciliation test a tautology: the two sides being compared would be
the same object, so they could never disagree, and the reconciler would pass
its tests while being incapable of detecting the break it exists to detect.

Here the broker keeps `data/oms/paper_broker.json`, fsynced on every mutation
exactly as the journal is. It survives the trading process being killed,
because a real broker does. That single property is what lets the chaos tests
ask the only question that matters after a crash — *does the broker have this
order?* — and get an answer that was not written by the code being tested.

**Faults are injected deliberately, and the nasty one is the default.** When
`unreachable_on_place` fires, the order **is recorded** and *then* the send
raises. That is the genuinely dangerous case: the order is live at the broker
and the caller has no idea. A simulator that failed by not recording would
only ever exercise the easy half of the ambiguity.

Everything is deterministic. Slippage is a fixed number of basis points
applied adverse to the side, not a draw from a distribution, because
`CLAUDE.md` requires byte-identical output from identical input and a random
fill price would make every paper-trading comparison unrepeatable.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eulerlab.backtest.events import Order
from eulerlab.costs.schedule import Side
from eulerlab.oms.broker import (
    BrokerOrderView,
    BrokerRejected,
    BrokerUnreachable,
    DuplicateOrder,
)
from eulerlab.paths import data_path

PAPER_STATE_PATH = data_path("oms/paper_broker.json")


@dataclass
class PaperFaults:
    """Failures to inject, each a count of how many times to do it.

    Counts rather than booleans so a test can say "fail the next two sends and
    then behave", which is the shape of every real outage.
    """

    unreachable_on_place: int = 0
    """Record the order, then raise. The order IS live at the broker."""

    lost_on_place: int = 0
    """Raise without recording. The order is NOT live. Indistinguishable from
    the case above at the call site — which is exactly why UNKNOWN exists."""

    unreachable_on_query: int = 0
    """The query itself fails, so nothing is resolved."""

    reject_symbols: set[str] = field(default_factory=set)

    def _take(self, name: str) -> bool:
        value = int(getattr(self, name))
        if value <= 0:
            return False
        setattr(self, name, value - 1)
        return True


class PaperBroker:
    """A broker that fills at a supplied price and remembers what it did."""

    name = "paper"

    def __init__(
        self,
        path: Path = PAPER_STATE_PATH,
        *,
        slippage_bps: float = 0.0,
        faults: PaperFaults | None = None,
    ) -> None:
        self.path = path
        self.slippage_bps = slippage_bps
        self.faults = faults or PaperFaults()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._state: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"orders": {}, "next_id": 1}
        loaded = json.loads(self.path.read_text(encoding="utf-8"))
        return {
            "orders": dict(loaded.get("orders") or {}),
            "next_id": int(loaded.get("next_id", 1)),
        }

    def _persist(self) -> None:
        """Durable before returning, for the same reason the journal is.

        Written to a temporary file and renamed, so a crash mid-write leaves
        the previous state intact rather than a half-written one. The journal
        can tolerate a torn last line because it is append-only; this file is
        rewritten whole, so it needs the atomic-rename form instead.
        """
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(self._state, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)

    def _view(self, record: dict[str, Any]) -> BrokerOrderView:
        return BrokerOrderView(
            client_order_id=str(record["client_order_id"]),
            broker_order_id=str(record["broker_order_id"]),
            status=str(record["status"]),
            filled_quantity=int(record["filled_quantity"]),
            average_price=float(record["average_price"]),
            reason=str(record.get("reason", "")),
        )

    def fill_price(self, side: Side, price: float) -> float:
        """Adverse slippage, deterministic."""
        drift = price * self.slippage_bps / 10_000.0
        return price + drift if side is Side.BUY else price - drift

    def place(self, order: Order, *, price: float | None = None) -> str:
        orders: dict[str, Any] = self._state["orders"]
        if order.client_order_id in orders:
            msg = (
                f"{order.client_order_id} already exists at the broker as "
                f"{orders[order.client_order_id]['broker_order_id']}"
            )
            raise DuplicateOrder(msg)

        if self.faults._take("lost_on_place"):
            msg = f"connection reset sending {order.client_order_id}; nothing was recorded"
            raise BrokerUnreachable(msg)

        broker_order_id = f"PAPER-{self._state['next_id']:06d}"
        self._state["next_id"] = int(self._state["next_id"]) + 1

        if order.symbol in self.faults.reject_symbols:
            record = {
                "client_order_id": order.client_order_id,
                "broker_order_id": broker_order_id,
                "symbol": order.symbol,
                "side": order.side.value,
                "quantity": order.quantity,
                "status": "rejected",
                "filled_quantity": 0,
                "average_price": 0.0,
                "reason": "instrument not tradable",
            }
            orders[order.client_order_id] = record
            self._persist()
            raise BrokerRejected(f"{order.symbol}: instrument not tradable")

        if price is None:
            record = {
                "client_order_id": order.client_order_id,
                "broker_order_id": broker_order_id,
                "symbol": order.symbol,
                "side": order.side.value,
                "quantity": order.quantity,
                "status": "rejected",
                "filled_quantity": 0,
                "average_price": 0.0,
                "reason": "no price: the instrument did not trade",
            }
            orders[order.client_order_id] = record
            self._persist()
            raise BrokerRejected(f"{order.symbol}: the instrument did not trade")

        filled = self.fill_price(order.side, price)
        orders[order.client_order_id] = {
            "client_order_id": order.client_order_id,
            "broker_order_id": broker_order_id,
            "symbol": order.symbol,
            "side": order.side.value,
            "quantity": order.quantity,
            "status": "complete",
            "filled_quantity": order.quantity,
            "average_price": filled,
            "reason": "",
        }
        self._persist()

        if self.faults._take("unreachable_on_place"):
            # Recorded above, on purpose. The order is live and the caller is
            # about to be told nothing useful.
            msg = f"timeout waiting for acknowledgement of {order.client_order_id}"
            raise BrokerUnreachable(msg)
        return broker_order_id

    def query(self, client_order_id: str) -> BrokerOrderView | None:
        if self.faults._take("unreachable_on_query"):
            msg = f"query for {client_order_id} timed out"
            raise BrokerUnreachable(msg)
        self._state = self._load()
        record = self._state["orders"].get(client_order_id)
        return self._view(record) if record else None

    def cancel(self, client_order_id: str) -> None:
        self._state = self._load()
        record = self._state["orders"].get(client_order_id)
        if record is None:
            raise BrokerRejected(f"no such order {client_order_id}")
        if record["status"] in {"complete", "rejected", "cancelled"}:
            raise BrokerRejected(f"{client_order_id} is already {record['status']}")
        record["status"] = "cancelled"
        self._persist()

    def positions(self) -> dict[str, int]:
        self._state = self._load()
        out: dict[str, int] = {}
        for record in self._state["orders"].values():
            if record["status"] not in {"complete", "partial"}:
                continue
            quantity = int(record["filled_quantity"])
            signed = quantity if record["side"] == Side.BUY.value else -quantity
            out[record["symbol"]] = out.get(record["symbol"], 0) + signed
        return {symbol: qty for symbol, qty in out.items() if qty}

    def open_orders(self) -> list[BrokerOrderView]:
        self._state = self._load()
        return [
            self._view(r)
            for r in self._state["orders"].values()
            if r["status"] in {"open", "partial"}
        ]

    def inject(
        self, client_order_id: str, symbol: str, side: Side, quantity: int, price: float
    ) -> None:
        """Put an order at the broker that the OMS never sent.

        The only way to build the case reconciliation is actually for: a
        position that exists at the broker and not locally. In real life it
        arrives from a manual trade in the broker's app, a partial fill on a
        stale order, or a corporate action. There is no honest way to test the
        reconciler without being able to create it.
        """
        self._state = self._load()
        self._state["orders"][client_order_id] = {
            "client_order_id": client_order_id,
            "broker_order_id": f"PAPER-{self._state['next_id']:06d}",
            "symbol": symbol,
            "side": side.value,
            "quantity": quantity,
            "status": "complete",
            "filled_quantity": quantity,
            "average_price": price,
            "reason": "injected out of band",
        }
        self._state["next_id"] = int(self._state["next_id"]) + 1
        self._persist()
