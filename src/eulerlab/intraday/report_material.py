"""Turning an intraday scan into the rows `reports.build` expects.

Shared because two callers need it and they must not diverge: the batch API,
which writes a report when an operator runs a backtest from the interface, and
`adopted_run`, which writes one for each strategy's standing result. A strategy
whose report came from a different code path than its neighbour's is a strategy
whose report cannot be compared to it.

### One trade becomes several rows

A bracket trade is one entry and one or more exits — target 1, target 2, a
stop, a trailing stop. Each leg is a fill. Collapsing a trade into a single row
would report half the turnover and none of the partial exits, and the
per-instrument attribution would stop reconciling with the equity curve.

### The cost sits on the entry

`bracket.run` accumulates every leg's charge onto the trade, so the whole bill
is known per trade and not per leg. Splitting it across legs would be inventing
a breakdown; putting it all on the entry row keeps the total exact and is the
one that reconciles. The exit rows carry zero, which is a placement choice
rather than a claim that exits are free.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class IntradayFill:
    """One leg of a bracket trade, in the shape `reports.build` expects."""

    day: date
    symbol: str
    side: Any
    quantity: int
    price: float
    cost: float


def fills_and_marks(scans: list[Any]) -> tuple[list[IntradayFill], dict[str, float]]:
    """Every bracket leg as a fill, plus the last price seen per symbol.

    `marks` values positions still open at the end of a run. An intraday
    strategy is flat at every close so nothing should be open, but the report
    asks for marks and a symbol missing from them is flagged rather than
    dropped — so the last exit price is supplied and the question never arises.
    """
    from eulerlab.costs.schedule import Side

    fills: list[IntradayFill] = []
    marks: dict[str, float] = {}

    for scan in scans:
        for trade in scan.trades:
            if not trade.filled or trade.entry_ts is None:
                continue
            shares = sum(leg.shares for leg in trade.exits)
            if shares:
                fills.append(
                    IntradayFill(
                        day=trade.entry_ts.date(),
                        symbol=scan.symbol,
                        side=Side.BUY,
                        quantity=shares,
                        price=trade.entry_price,
                        cost=trade.costs,
                    )
                )
            for leg in trade.exits:
                fills.append(
                    IntradayFill(
                        day=leg.ts.date(),
                        symbol=scan.symbol,
                        side=Side.SELL,
                        quantity=leg.shares,
                        price=leg.price,
                        cost=0.0,
                    )
                )
                marks[scan.symbol] = leg.price

    return fills, marks
