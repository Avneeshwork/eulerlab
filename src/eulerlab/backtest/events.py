"""Orders, fills and portfolio state — the vocabulary Tier B needs and Tier A does not.

Tier A collapses "decide, trade, own" into a single step. That is what makes
it fast and what makes it unable to model a stop, a partial fill, or a
rejection. Tier B keeps the stages separate, and the reason is not
completeness for its own sake: **this is the same shape as live trading**, so
the order object that a backtest creates is the order object an OMS will
later submit. If the two diverge, every reality-gap investigation in Sprint 25
starts by asking which one was lying.

`CLAUDE.md` requires `algo_id` on the order schema from day one, and a
deterministic client order id derived from `hash(strategy_id, signal_time,
instrument_id, seq)`. Both are here from the start rather than retrofitted,
for the reason that file gives: adding a field before the OMS exists is five
minutes, and adding it after the reconciler and event log read the schema is a
week.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from eulerlab.costs.schedule import Side


class OrderType(StrEnum):
    MARKET_ON_CLOSE = "market_on_close"
    """The only type Tier B models today, chosen so it can be reconciled
    against Tier A exactly. Limit and stop belong here later; the point of the
    lifecycle is that adding them does not change the interface."""


class OrderStatus(StrEnum):
    NEW = "new"
    FILLED = "filled"
    REJECTED = "rejected"
    """Rejections are modelled, not assumed away. An instrument that did not
    trade cannot be traded, and pretending otherwise is how a backtest fills
    orders that live would have bounced."""


@dataclass(frozen=True)
class Order:
    """An intention to trade, before anything has happened."""

    client_order_id: str
    strategy_id: str
    signal_day: date
    symbol: str
    side: Side
    quantity: int
    order_type: OrderType = OrderType.MARKET_ON_CLOSE
    algo_id: str | None = None
    """Nullable and unused, per CLAUDE.md's compliance stub S-001. Present so
    the compliance sprint is a config change rather than a schema migration."""


def client_order_id(strategy_id: str, signal_day: date, symbol: str, seq: int) -> str:
    """Deterministic id: `hash(strategy_id, signal_time, instrument_id, seq)`.

    Deterministic so a retry cannot double-send — the same intention always
    produces the same id, and the broker can reject the duplicate. That
    property is worthless if it only exists in live code, because then the
    backtest is not exercising it. Hence it lives here.
    """
    material = f"{strategy_id}|{signal_day.isoformat()}|{symbol}|{seq}"
    return hashlib.sha256(material.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class Fill:
    """What actually happened."""

    client_order_id: str
    day: date
    symbol: str
    side: Side
    quantity: int
    price: float
    cost: float

    @property
    def notional(self) -> float:
        return self.price * self.quantity

    @property
    def signed_quantity(self) -> int:
        return self.quantity if self.side is Side.BUY else -self.quantity


@dataclass(frozen=True)
class Rejection:
    client_order_id: str
    day: date
    symbol: str
    reason: str


@dataclass
class Position:
    symbol: str
    quantity: int = 0
    cost_basis: float = 0.0
    """Total rupees paid for the current holding, including costs. Used for
    realised P&L, so it must move with every fill rather than being recomputed
    at the end."""

    def average_price(self) -> float:
        return self.cost_basis / self.quantity if self.quantity else 0.0


@dataclass
class Portfolio:
    """Cash, positions, and a ledger — the state Sprint 12 will assert against.

    Sprint 12 is described in the build plan as the most important gate in the
    project, and it can only check what this object chooses to record. So
    realised P&L and total costs are accumulated as they happen rather than
    derived afterwards: a derived number agrees with itself by construction and
    proves nothing.
    """

    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    fills: list[Fill] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)
    realised_pnl: float = 0.0
    total_costs: float = 0.0

    def apply(self, fill: Fill) -> None:
        """Update state for one fill. The only mutation path in the engine."""
        position = self.positions.setdefault(fill.symbol, Position(fill.symbol))
        self.cash -= fill.signed_quantity * fill.price
        self.cash -= fill.cost
        self.total_costs += fill.cost

        if fill.side is Side.BUY:
            position.cost_basis += fill.notional + fill.cost
            position.quantity += fill.quantity
        else:
            # Realise against the average price of what is being sold, so a
            # partial exit realises a proportional share of the basis rather
            # than all of it.
            average = position.average_price()
            self.realised_pnl += (
                (fill.price * fill.quantity) - (average * fill.quantity) - fill.cost
            )
            position.cost_basis -= average * fill.quantity
            position.quantity -= fill.quantity

        if position.quantity == 0:
            position.cost_basis = 0.0
        self.fills.append(fill)

    def market_value(self, prices: dict[str, float]) -> float:
        return sum(
            prices[symbol] * position.quantity
            for symbol, position in self.positions.items()
            if position.quantity and symbol in prices
        )

    def equity(self, prices: dict[str, float]) -> float:
        return self.cash + self.market_value(prices)

    def holdings(self) -> dict[str, int]:
        return {s: p.quantity for s, p in self.positions.items() if p.quantity}


def target_quantities(
    equity: float,
    targets: Mapping[str, float],
    price_of: Callable[[str], float | None],
) -> dict[str, int]:
    """Weights into share counts, truncated toward zero.

    Truncated rather than rounded, and that is a real choice: rounding up can
    ask for more capital than the portfolio has, which live would reject and a
    backtest would happily fill. Erring small is the direction that cannot
    invent buying power.

    A symbol with no price is left out entirely. It cannot be sized, and
    guessing a price here would put a made-up number at the root of a position.
    """
    out: dict[str, int] = {}
    for symbol, weight in targets.items():
        price = price_of(symbol)
        if price and price > 0:
            out[symbol] = int((equity * weight) / price)
    return out


def plan_orders(
    *,
    strategy_id: str,
    signal_day: date,
    holdings: Mapping[str, int],
    desired: Mapping[str, int],
    seq_start: int = 0,
    algo_id: str | None = None,
) -> tuple[list[Order], int]:
    """The difference between what is held and what is wanted, as orders.

    Extracted from the Tier B engine so that the backtest, paper trading and
    live share **one** implementation. `CLAUDE.md` requires the `Strategy`
    interface to be identical across all three; the translation from a
    strategy's intent into orders has to be identical too, or the reality-gap
    report in Sprint 26 ends up measuring a difference we wrote ourselves.

    Symbols are sorted so the sequence numbers — and therefore the client
    order ids — are deterministic. Returns the new sequence counter, which the
    caller carries forward: the id must be unique across a whole run, not just
    within one rebalance.
    """
    orders: list[Order] = []
    sequence = seq_start
    for symbol in sorted(set(holdings) | set(desired)):
        delta = desired.get(symbol, 0) - holdings.get(symbol, 0)
        if delta == 0:
            continue
        sequence += 1
        orders.append(
            Order(
                client_order_id=client_order_id(strategy_id, signal_day, symbol, sequence),
                strategy_id=strategy_id,
                signal_day=signal_day,
                symbol=symbol,
                side=Side.BUY if delta > 0 else Side.SELL,
                quantity=abs(delta),
                order_type=OrderType.MARKET_ON_CLOSE,
                algo_id=algo_id,
            )
        )
    return orders, sequence
