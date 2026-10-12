"""Closed trades, matched from a fill ledger and stored with the report.

Every platform surveyed in `docs/RESEARCH/061-backtest-result-storage.md`
stores a list of round trips beside the orders: LEAN's `ClosedTrades`,
vectorbt's trade records, NautilusTrader's positions report. Until this, the
report held only fills and the browser rebuilt the trades on every open, so the
trade list existed nowhere a later reader could check it.

### The matching rule

The same as `web/lib/backtestStats.ts::roundTrips`, so the stored list and the
one the report page draws cannot disagree: first in, first out per symbol, and
one trade per closing fill. A bracket exited in two legs is two trades, which
is how a broker's tradebook counts it. A fill larger than the open position
closes it and opens the remainder the other way. Whatever is still open at the
end is listed as open, at its entry price.

### MAE and MFE are on daily closes

Maximum adverse and favourable excursion — the worst and best unrealised P&L
while the trade was open — are LEAN's `MAE` and `MFE`. They are measured here
against the **same back-adjusted closes the engine marked positions at**, from
the entry day to the exit day inclusive, plus the entry and exit fill prices.
A daily close misses the intraday low, so these understate the true excursion
on any day the price moved and recovered. Where no close series is given (the
intraday paths), they are `None` rather than a guess.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from eulerlab.costs.schedule import Side

EPSILON = 1e-12


class FillLike(Protocol):
    """The fields a trade needs from a fill. Matches `reports.FillLike`."""

    @property
    def day(self) -> date: ...

    @property
    def symbol(self) -> str: ...

    @property
    def side(self) -> Side: ...

    @property
    def quantity(self) -> int: ...

    @property
    def price(self) -> float: ...

    @property
    def cost(self) -> float: ...


def _units(qty: float) -> float | int:
    """Whole numbers as ints, so a stored trade reads 25 shares, not 25.0."""
    return int(qty) if float(qty).is_integer() else qty


@dataclass
class _Lot:
    day: date
    price: float
    qty: float
    cost_per_unit: float


def _excursion(
    closes: Mapping[date, float] | None,
    *,
    entry_day: date,
    exit_day: date,
    entry_price: float,
    exit_price: float | None,
    quantity: float,
    direction: int,
) -> tuple[float | None, float | None]:
    """(MAE, MFE) in account currency, before costs. MAE ≤ 0 ≤ MFE."""
    if closes is None:
        return None, None
    path = [price for day, price in closes.items() if entry_day <= day <= exit_day]
    path.append(entry_price)
    if exit_price is not None:
        path.append(exit_price)
    moves = [(price - entry_price) * quantity * direction for price in path]
    return round(min(*moves, 0.0), 2), round(max(*moves, 0.0), 2)


def round_trips(
    fills: Sequence[FillLike],
    closes: Mapping[str, Mapping[date, float]] | None = None,
) -> list[dict[str, Any]]:
    """Closed and open trades from the fills, in the order they closed."""
    book: dict[str, tuple[int, list[_Lot]]] = {}
    trades: list[dict[str, Any]] = []
    ordered = sorted(enumerate(fills), key=lambda pair: (pair[1].day, pair[0]))

    for _, fill in ordered:
        direction = -1 if fill.side is Side.SELL else 1
        qty = float(abs(fill.quantity))
        if qty == 0:
            continue
        cost_per_unit = fill.cost / qty
        position = book.get(fill.symbol)

        if position is None or not position[1] or position[0] == direction:
            lots = position[1] if position and position[1] else []
            lots.append(_Lot(fill.day, fill.price, qty, cost_per_unit))
            book[fill.symbol] = (direction, lots)
            continue

        held_direction, lots = position
        matched = entry_value = entry_cost = 0.0
        first_day = lots[0].day
        while qty > 0 and lots:
            lot = lots[0]
            take = min(qty, lot.qty)
            matched += take
            entry_value += take * lot.price
            entry_cost += take * lot.cost_per_unit
            lot.qty -= take
            qty -= take
            if lot.qty <= EPSILON:
                lots.pop(0)

        entry_price = entry_value / matched
        gross = (fill.price - entry_price) * matched * held_direction
        net = gross - entry_cost - cost_per_unit * matched
        mae, mfe = _excursion(
            closes.get(fill.symbol) if closes is not None else None,
            entry_day=first_day,
            exit_day=fill.day,
            entry_price=entry_price,
            exit_price=fill.price,
            quantity=matched,
            direction=held_direction,
        )
        trades.append(
            {
                "symbol": fill.symbol,
                "side": "long" if held_direction == 1 else "short",
                "entry_day": first_day.isoformat(),
                "entry_price": round(entry_price, 4),
                "exit_day": fill.day.isoformat(),
                "exit_price": round(fill.price, 4),
                "quantity": _units(matched),
                "gross": round(gross, 2),
                "costs": round(entry_cost + cost_per_unit * matched, 2),
                "net": round(net, 2),
                "return_pct": round(net / entry_value, 6) if entry_value > 0 else 0.0,
                "days_held": (fill.day - first_day).days,
                "mae": mae,
                "mfe": mfe,
                "open": False,
            }
        )

        if qty > EPSILON:
            book[fill.symbol] = (direction, [_Lot(fill.day, fill.price, qty, cost_per_unit)])

    for symbol, (held_direction, lots) in book.items():
        for lot in lots:
            trades.append(
                {
                    "symbol": symbol,
                    "side": "long" if held_direction == 1 else "short",
                    "entry_day": lot.day.isoformat(),
                    "entry_price": round(lot.price, 4),
                    "exit_day": None,
                    "exit_price": None,
                    "quantity": _units(lot.qty),
                    "gross": 0.0,
                    "costs": round(lot.cost_per_unit * lot.qty, 2),
                    "net": round(-lot.cost_per_unit * lot.qty, 2),
                    "return_pct": 0.0,
                    "days_held": None,
                    "mae": None,
                    "mfe": None,
                    "open": True,
                }
            )
    for number, trade in enumerate(trades, start=1):
        trade["id"] = number
    return trades


def summary(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Counts and ratios over the closed trades. Open trades are counted, not scored."""
    closed = [t for t in trades if not t["open"]]
    wins = [float(t["net"]) for t in closed if float(t["net"]) > 0]
    losses = [float(t["net"]) for t in closed if float(t["net"]) <= 0]
    gross_profit = sum(wins)
    gross_loss = sum(losses)  # zero or negative, as the report page has it
    return {
        "closed": len(closed),
        "open": len(trades) - len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(closed), 4) if closed else None,
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(gross_profit / -gross_loss, 4) if gross_loss < 0 else None,
        "expectancy": round(sum(float(t["net"]) for t in closed) / len(closed), 2)
        if closed
        else None,
    }
