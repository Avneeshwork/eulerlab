"""Who fills an order — the one thing that differs between backtest and paper.

`CLAUDE.md`: *One `Strategy` interface, used unchanged by Tier A backtest,
Tier B backtest, paper and live. If those diverge, stop and fix the
abstraction.*

The obvious way to build paper trading is to write a second loop that walks
the days, asks the strategy for weights, and sends orders. That loop would be
a copy of the Tier B engine, and copies drift. Six months later the paper
system and the backtest disagree, and the reality-gap report — whose entire
job is to explain differences between the two — is measuring a difference we
introduced ourselves.

So there is no second loop. `event_driven.run` is the only loop, and it takes
an executor. The backtest passes `SimulatedExecutor`, which fills at the next
close. Paper passes `OMSExecutor`, which sends the order through the order
manager to a broker and reports what came back. Everything else — the
strategy, the market view, the weights, the sizing, the order construction,
the portfolio accounting — is the same object graph running the same code.

That makes the reality gap **exactly** the executor's behaviour and nothing
else, which is the only way the attribution in `paper/attribution.py` means
anything.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from eulerlab.backtest import vector
from eulerlab.backtest.events import Fill, Order, Rejection
from eulerlab.costs.model import Brokerage


@runtime_checkable
class Executor(Protocol):
    """Turn one order into a fill or a rejection."""

    name: str

    def execute(self, order: Order, *, day: date, price: float | None) -> Fill | Rejection:
        """`price` is the engine's traded price for the day, or `None` if the
        instrument did not print. What an executor does with it is its own
        business — the simulated one fills at it, a live one treats it as a
        reference and reports whatever the exchange actually gave."""
        ...


class SimulatedExecutor:
    """Fill at the engine's price. The backtest's assumption, made explicit.

    This is the behaviour Tier B always had; naming it as an assumption is the
    point of extracting it. "Every order fills completely at the closing price
    with no delay and no market impact" is a strong claim, and it is now a
    named object that something else can be substituted for, rather than an
    invisible property of the loop.
    """

    name = "simulated"

    def __init__(
        self,
        *,
        cost_mode: str = "realistic",
        asset_class: str,
        brokerage: Brokerage | None = None,
        cost_multiplier: float = 1.0,
        fund_symbols: frozenset[str] = frozenset(),
    ) -> None:
        self.cost_mode = cost_mode
        self.fund_symbols = fund_symbols
        # Required, not defaulted. The venue decides the bill, and a default
        # here is how US trades came to be charged Indian delivery costs while
        # the routing code above them said otherwise.
        self.asset_class = asset_class
        self.brokerage = brokerage
        self.cost_multiplier = cost_multiplier

    def execute(self, order: Order, *, day: date, price: float | None) -> Fill | Rejection:
        if price is None or price <= 0:
            # Modelled, not assumed away: an instrument that did not print
            # cannot be traded, and live would have rejected it.
            return Rejection(
                client_order_id=order.client_order_id,
                day=day,
                symbol=order.symbol,
                reason="no trade on fill day",
            )
        cost = (
            0.0
            if self.cost_mode == "replication"
            else vector._costs_for(
                day,
                price,
                order.quantity,
                order.side,
                self.brokerage,
                self.asset_class,
                fund_unit=order.symbol in self.fund_symbols,
            )
            * self.cost_multiplier
        )
        return Fill(
            client_order_id=order.client_order_id,
            day=day,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=price,
            cost=cost,
        )
