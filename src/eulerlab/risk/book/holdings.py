"""The book as handed in: holdings, gap rules, and the roll-up of deployments' stored state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from eulerlab.risk.book.growth import growth


@dataclass(frozen=True)
class Holding:
    symbol: str
    quantity: float
    price: float
    value: float


@dataclass(frozen=True)
class GapRule:
    """A position held only from one close to the next open (ADR-072).

    The overnight futures deployment buys at the close on a signal day and
    sells at the next open. At every close its book is empty, so holdings say
    it has no risk, while on a night it trades it carries the whole gap on a
    lot worth more than most of the other deployments together.

    `gaps` and `held` are keyed by the **morning** the position is closed, so
    a gap sits on the same day as the close-to-close return it is part of.
    """

    contract: str
    lots: int
    lot_size: int
    notional: float
    """Rupees it would buy on a signal night, at today's equity and price."""
    gaps: Mapping[date, float]
    """Open over the previous close, less one, for the near contract."""
    held: frozenset[date]
    """Mornings on which the rule had been in position overnight."""
    held_now: float = 0.0
    """Rupees it holds tonight, from its own book. Zero on most nights."""
    worst: tuple[date, float] | None = None
    """The worst gap in the whole futures history, held or not: (morning, return)."""


@dataclass(frozen=True)
class Book:
    """One deployment as it stands: what it holds and where its equity has been."""

    id: str
    strategy_id: str
    title: str
    capital: float
    equity: float
    cash: float
    holdings: tuple[Holding, ...]
    curve: tuple[tuple[date, float], ...]
    status: str = "active"
    note: str = ""
    rule: GapRule | None = None
    """Set for a deployment whose risk is a gap, not a holding at the close."""
    flows: tuple[tuple[date, float], ...] = ()
    """Deposits (+) and withdrawals (-), each dated by the first curve day whose
    equity includes it. Money moved in or out, never profit or loss."""

    @property
    def deployed(self) -> float:
        """The money put in: the starting capital plus every flow so far."""
        return self.capital + sum(amount for _, amount in self.flows)

    @property
    def made(self) -> float:
        return self.equity - self.deployed

    def growth(self) -> list[tuple[date, float]]:
        return growth(self.curve, self.flows, self.capital)

    @property
    def total_return(self) -> float:
        """Time-weighted: what ₹1 held from the start would have become, less 1."""
        path = self.growth()
        return path[-1][1] - 1.0 if path else 0.0


def book_from_state(
    deployment_id: str,
    strategy_id: str,
    title: str,
    capital: float,
    status: str,
    state: Mapping[str, Any] | None,
) -> Book:
    """A `Book` from a deployment's stored state. No state yet means all cash."""
    state = state or {}
    holdings = tuple(
        Holding(
            symbol=str(row["symbol"]),
            quantity=float(row.get("quantity") or 0),
            price=float(row.get("last_price") or 0),
            value=float(row.get("value") or 0),
        )
        for row in state.get("book") or []
        if row.get("symbol") and float(row.get("value") or 0) != 0
    )
    curve = tuple(
        (date.fromisoformat(str(day)), float(value)) for day, value in state.get("curve") or []
    )
    # `applied_day` is the curve day that first includes the flow, in both the
    # rebalancing runner (the fill day) and the overnight book (the close).
    flows = tuple(
        (date.fromisoformat(str(flow["applied_day"])), float(flow["amount"]))
        for flow in state.get("flows") or []
        if flow.get("applied_day") and isinstance(flow.get("amount"), int | float)
    )
    equity = float(state.get("equity") or capital)
    return Book(
        id=deployment_id,
        strategy_id=strategy_id,
        title=title,
        capital=float(capital),
        equity=equity,
        cash=float(capital if state.get("cash") is None else state["cash"]),
        holdings=holdings,
        curve=curve,
        status=status,
        flows=flows,
    )
