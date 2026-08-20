"""Tier A: a fast, approximate, deliberately pessimistic backtester.

**For screening only.** Its job is to reject most ideas cheaply so Tier B
never has to look at them. That purpose dictates every design choice here,
including the ones that look like laziness.

## What it cannot do, stated up front

A vectorised engine steps bar to bar and never sees inside a bar. So it
**cannot** model a stop-loss, a limit fill, an intrabar reversal, or any order
that depends on the path a price took during the day. Simulating them anyway
is the standard way a fast backtester produces results the event-driven one
cannot reproduce — and by then the discrepancy is a research project rather
than a bug. `Approximations` lists them, and the tear sheet prints them, so a
number from this engine is never read as though it came from Tier B.

## Conservative by construction

Where a choice exists, this engine takes the worse one, so that when Tier A
and Tier B disagree in Sprint 11 the *fast* one is pessimistic:

- Decisions use data through day *t*; the trade fills at day *t+1*'s close,
  never *t*'s. Filling at the close of the day you decided on is the most
  common lookahead in a vectorised backtest and it is worth several percent a
  year of imaginary return.
- Every rebalance pays full costs on the traded notional, both legs.
- No borrowing: gross exposure is capped, and the cap belongs to the engine
  rather than the strategy.

## One cost path

Costs are applied in exactly one place, from `eulerlab.costs`. The reference
system in `~/Documents/Trade` had two — a `commission` on the engine and a
cost model inside the strategy's state machine — and had to neutralise one
with a comment reading *"so it can't compute a second, inconsistent cost
basis"*. A comment is not a mechanism. Here the strategy has no way to express
a cost, so there is nothing to disable.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from eulerlab.backtest.strategy import MarketView, Strategy, normalise
from eulerlab.costs.model import Brokerage, cost_of_trade
from eulerlab.costs.schedule import Segment, Side
from eulerlab.features.panel import PanelRow, by_symbol, trading_days

APPROXIMATIONS: tuple[str, ...] = (
    "no intrabar prices: stops, limits and intrabar reversals cannot be modelled",
    "fills at the next bar's close, never at the decision bar's",
    "no partial fills, no queue position, no rejected orders",
    "no borrow cost, no margin, no financing",
    "costs charged on traded notional; no impact or slippage beyond that",
)
"""Printed with every result. A Tier A number that is read as a Tier B number
is worse than no number, so the caveats travel with it rather than living in
documentation someone may not open."""


@dataclass(frozen=True)
class Fill:
    day: date
    symbol: str
    side: Side
    price: float
    quantity: int
    notional: float
    cost: float


@dataclass
class BacktestResult:
    strategy: str
    days: list[date] = field(default_factory=list)
    equity: list[float] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    starting_cash: float = 1_000_000.0
    cost_mode: str = "realistic"

    @property
    def total_cost(self) -> float:
        return sum(f.cost for f in self.fills)

    @property
    def final_equity(self) -> float:
        return self.equity[-1] if self.equity else self.starting_cash

    @property
    def total_return(self) -> float:
        return self.final_equity / self.starting_cash - 1.0

    @property
    def turnover(self) -> float:
        return sum(f.notional for f in self.fills)

    def daily_returns(self) -> list[float]:
        out: list[float] = []
        for previous, current in zip(self.equity, self.equity[1:], strict=False):
            if previous > 0:
                out.append(current / previous - 1.0)
        return out


def _costs_for(
    day: date, price: float, quantity: int, side: Side, brokerage: Brokerage | None
) -> float:
    """The single cost path. Delivery rates: Tier A holds overnight."""
    breakdown = cost_of_trade(
        trade_date=day,
        segment=Segment.EQUITY_DELIVERY,
        side=side,
        price=Decimal(str(round(price, 2))),
        quantity=quantity,
        brokerage=brokerage,
    )
    return float(breakdown.total)


def run(
    rows: Sequence[PanelRow],
    strategy: Strategy,
    *,
    starting_cash: float = 1_000_000.0,
    rebalance_every: int = 21,
    gross_cap: float = 1.0,
    cost_mode: str = "realistic",
    brokerage: Brokerage | None = None,
    warmup: int = 253,
) -> BacktestResult:
    """Run the strategy over the panel.

    `cost_mode="replication"` zeroes costs, for reproducing a published result
    before asking whether it survives reality. Borrowed from the reference
    system, where it is the one flag that makes "does this survive costs?" a
    single switch rather than a rebuild.

    `warmup` skips the leading period so a 12-month feature is not evaluated
    on three months of history. Without it the early portfolio is built from
    features that mean something different from their name.
    """
    histories = by_symbol(rows)
    days = trading_days(rows)
    if len(days) <= warmup + 2:
        return BacktestResult(strategy=strategy.describe(), starting_cash=starting_cash)

    result = BacktestResult(
        strategy=strategy.describe(), starting_cash=starting_cash, cost_mode=cost_mode
    )
    cash = starting_cash
    holdings: dict[str, int] = {}

    # Indexed once. The naive version rescanned each symbol's whole history
    # per lookup, which is quadratic and made a three-year run slower than the
    # data fetch that produced it.
    price_index: dict[str, dict[date, float]] = {
        symbol: {row.day: row.close for row in rows_} for symbol, rows_ in histories.items()
    }
    ordered_days: dict[str, list[date]] = {
        symbol: [row.day for row in rows_] for symbol, rows_ in histories.items()
    }

    lookback = strategy.lookback

    def _view_history(today: date) -> dict[str, list[PanelRow]]:
        """Rows up to `today`, capped at the strategy's declared lookback.

        Sliced by bisect on the pre-sorted day list rather than filtered, and
        capped rather than complete: handing a 253-day feature 2,869 days of
        history was costing ~90% of the run time for data it never reads.
        """
        out: dict[str, list[PanelRow]] = {}
        for symbol, rows_ in histories.items():
            end = bisect_right(ordered_days[symbol], today)
            if end == 0:
                continue
            start = max(0, end - lookback) if lookback else 0
            out[symbol] = rows_[start:end]
        return out

    def traded_price(symbol: str, day: date) -> float | None:
        """The price if the symbol actually traded that day, else None.

        Execution uses this: a position cannot be opened or closed on a day the
        instrument did not print.
        """
        return price_index.get(symbol, {}).get(day)

    def mark_price(symbol: str, day: date) -> float | None:
        """The last known price at or before `day` — the valuation price.

        The distinction from `traded_price` is not pedantry, it is a bug fix.
        Measured on the real panel: **31 of 400 symbols have at least one
        missing day inside their own listed span**. Valuing a holding at None
        on those days silently dropped its entire value out of the portfolio
        and restored it the next day, which produced a **-50% maximum
        drawdown** that was pure artefact.

        A stock that did not trade today is still worth roughly what it was
        worth yesterday, which is what every real portfolio system marks it at.
        """
        if (price := price_index.get(symbol, {}).get(day)) is not None:
            return price
        days_ = ordered_days.get(symbol)
        if not days_:
            return None
        position = bisect_right(days_, day) - 1
        if position < 0:
            return None
        return price_index[symbol][days_[position]]

    def portfolio_value(day: date) -> float:
        total = cash
        for symbol, quantity in holdings.items():
            price = mark_price(symbol, day)
            if price is not None:
                total += price * quantity
        return total

    for index in range(warmup, len(days) - 1):
        today = days[index]
        # Fills land on the NEXT bar's close. Using today's close would let a
        # decision made from today's data trade at today's price, which is the
        # most common lookahead in a vectorised backtest.
        fill_day = days[index + 1]

        if (index - warmup) % rebalance_every == 0:
            view = MarketView(as_of=today, history=_view_history(today))
            targets = normalise(strategy.target_weights(view), gross_cap=gross_cap)
            equity = portfolio_value(today)

            desired: dict[str, int] = {}
            for symbol, weight in targets.items():
                price = traded_price(symbol, fill_day)
                if price and price > 0:
                    desired[symbol] = int((equity * weight) / price)

            for symbol in set(holdings) | set(desired):
                delta = desired.get(symbol, 0) - holdings.get(symbol, 0)
                if delta == 0:
                    continue
                price = traded_price(symbol, fill_day)
                if price is None or price <= 0:
                    # Cannot trade an instrument that did not print today. The
                    # position simply carries; it is not silently revalued to
                    # zero or force-closed at a made-up price.
                    continue
                side = Side.BUY if delta > 0 else Side.SELL
                quantity = abs(delta)
                notional = price * quantity
                cost = (
                    0.0
                    if cost_mode == "replication"
                    else _costs_for(fill_day, price, quantity, side, brokerage)
                )
                cash -= delta * price
                cash -= cost
                result.fills.append(Fill(fill_day, symbol, side, price, quantity, notional, cost))
                if desired.get(symbol, 0) == 0:
                    holdings.pop(symbol, None)
                else:
                    holdings[symbol] = desired[symbol]

        result.days.append(fill_day)
        result.equity.append(portfolio_value(fill_day))

    return result
