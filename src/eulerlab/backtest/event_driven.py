"""Tier B: event-driven, explicit fills, same `Strategy` unchanged.

Tier A answers "is this worth looking at". Tier B answers "what would actually
have happened", and the difference is that every step is separated:

    bar -> strategy decides -> orders created -> filled or rejected -> portfolio

Tier A does all of that in one expression. Keeping them apart is what lets
this engine reject an order, fill it partially, or later fill it at a limit —
and, more importantly, it is the same sequence a live session runs. The order
object created here is the one an OMS will submit in Sprint 19.

**The strategy is not adapted.** It is the same object Tier A runs, called the
same way, receiving the same `MarketView`. That is the acceptance test for
`CLAUDE.md`'s "one interface" rule: if Tier B needed a wrapper, the interface
would already have failed.

**Costs come from `eulerlab.costs` through the same helper Tier A uses.** Tier
B does not get its own cost model. The operator's earlier system had two cost
paths and had to disable one with a comment; here there is one function and
both engines call it.

## Reconciliation with Tier A

Configured identically — market-on-close, no impact, no partial fills — the
two engines should produce the same equity curve. `reconcile()` measures it,
and the asymmetry matters: **Tier A must be the pessimistic one**. If Tier B
is ever more conservative than Tier A, that is a Tier A bug, because Tier A's
whole job is to reject things cheaply without wrongly passing them on.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from eulerlab.backtest.events import Fill as EventFill
from eulerlab.backtest.events import (
    Order,
    OrderType,
    Portfolio,
    Rejection,
    client_order_id,
)
from eulerlab.backtest.strategy import MarketView, Strategy, normalise
from eulerlab.backtest.vector import _costs_for
from eulerlab.costs.model import Brokerage
from eulerlab.costs.schedule import Side
from eulerlab.features.panel import PanelRow, by_symbol, trading_days


@dataclass
class TierBResult:
    strategy: str
    days: list[date] = field(default_factory=list)
    equity: list[float] = field(default_factory=list)
    portfolio: Portfolio | None = None
    starting_cash: float = 1_000_000.0
    cost_mode: str = "realistic"
    orders: list[Order] = field(default_factory=list)

    @property
    def final_equity(self) -> float:
        return self.equity[-1] if self.equity else self.starting_cash

    @property
    def total_return(self) -> float:
        return self.final_equity / self.starting_cash - 1.0

    @property
    def total_cost(self) -> float:
        return self.portfolio.total_costs if self.portfolio else 0.0

    @property
    def fills(self) -> list[EventFill]:
        return self.portfolio.fills if self.portfolio else []

    @property
    def rejections(self) -> list[Rejection]:
        return self.portfolio.rejections if self.portfolio else []

    def daily_returns(self) -> list[float]:
        return [b / a - 1.0 for a, b in zip(self.equity, self.equity[1:], strict=False) if a > 0]


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
) -> TierBResult:
    """Run `strategy` event by event.

    Deliberately the same signature as `vector.run` so a caller can swap
    engines without changing anything else — including the argument order, so
    a positional call cannot silently mean something different.
    """
    histories = by_symbol(rows)
    days = trading_days(rows)
    if len(days) <= warmup + 2:
        return TierBResult(strategy=strategy.describe(), starting_cash=starting_cash)

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
        return price_index.get(symbol, {}).get(day)

    def mark_price(symbol: str, day: date) -> float | None:
        """Last known price at or before `day`. Same rule as Tier A: a holding
        that did not print is worth roughly what it was worth yesterday, not
        nothing."""
        if (price := price_index.get(symbol, {}).get(day)) is not None:
            return price
        days_ = ordered_days.get(symbol)
        if not days_:
            return None
        position = bisect_right(days_, day) - 1
        return price_index[symbol][days_[position]] if position >= 0 else None

    portfolio = Portfolio(cash=starting_cash)
    result = TierBResult(
        strategy=strategy.describe(), starting_cash=starting_cash, cost_mode=cost_mode
    )
    sequence = 0

    for index in range(warmup, len(days) - 1):
        today = days[index]
        fill_day = days[index + 1]

        if (index - warmup) % rebalance_every == 0:
            # --- decide ---
            view = MarketView(as_of=today, history=_view_history(today))
            targets = normalise(strategy.target_weights(view), gross_cap=gross_cap)

            marks = {
                symbol: price
                for symbol in set(portfolio.holdings()) | set(targets)
                if (price := mark_price(symbol, today)) is not None
            }
            equity = portfolio.equity(marks)

            desired: dict[str, int] = {}
            for symbol, weight in targets.items():
                price = traded_price(symbol, fill_day)
                if price and price > 0:
                    desired[symbol] = int((equity * weight) / price)

            # --- create orders ---
            orders: list[Order] = []
            for symbol in sorted(set(portfolio.holdings()) | set(desired)):
                delta = desired.get(symbol, 0) - portfolio.holdings().get(symbol, 0)
                if delta == 0:
                    continue
                sequence += 1
                orders.append(
                    Order(
                        client_order_id=client_order_id(
                            strategy.describe(), today, symbol, sequence
                        ),
                        strategy_id=strategy.describe(),
                        signal_day=today,
                        symbol=symbol,
                        side=Side.BUY if delta > 0 else Side.SELL,
                        quantity=abs(delta),
                        order_type=OrderType.MARKET_ON_CLOSE,
                    )
                )
            result.orders.extend(orders)

            # --- fill or reject ---
            for order in orders:
                price = traded_price(order.symbol, fill_day)
                if price is None or price <= 0:
                    # Modelled, not assumed away: an instrument that did not
                    # print cannot be traded, and live would have rejected it.
                    portfolio.rejections.append(
                        Rejection(
                            client_order_id=order.client_order_id,
                            day=fill_day,
                            symbol=order.symbol,
                            reason="no trade on fill day",
                        )
                    )
                    continue
                cost = (
                    0.0
                    if cost_mode == "replication"
                    else _costs_for(fill_day, price, order.quantity, order.side, brokerage)
                )
                portfolio.apply(
                    EventFill(
                        client_order_id=order.client_order_id,
                        day=fill_day,
                        symbol=order.symbol,
                        side=order.side,
                        quantity=order.quantity,
                        price=price,
                        cost=cost,
                    )
                )

        # --- mark to market ---
        marks = {
            symbol: price
            for symbol in portfolio.holdings()
            if (price := mark_price(symbol, fill_day)) is not None
        }
        result.days.append(fill_day)
        result.equity.append(portfolio.equity(marks))

    result.portfolio = portfolio
    return result


@dataclass(frozen=True)
class Reconciliation:
    """How far the two engines disagree, and in which direction."""

    days: int
    max_abs_diff: float
    final_diff: float
    tier_a_final: float
    tier_b_final: float

    @property
    def max_relative(self) -> float:
        base = max(abs(self.tier_a_final), 1.0)
        return self.max_abs_diff / base

    @property
    def agrees(self) -> bool:
        """Whether the two engines match to within floating-point noise.

        The tolerance is relative and generous at 1e-9, because the honest
        measured difference on a real three-year run is **7e-16** — machine
        epsilon. An exact `==` here produced a false alarm on identical
        curves, which is worse than no check: a property that cries wolf on
        arithmetic noise teaches its reader to skip it.
        """
        return self.max_relative <= 1e-9

    @property
    def tier_a_is_pessimistic(self) -> bool:
        """Tier A must not be the *optimistic* one.

        The asymmetry is the whole point of having a cheap screen: Tier A may
        reject something Tier B would have liked, but it must never pass
        something Tier B would have rejected. Agreement counts as satisfying
        this — the requirement is that Tier A is never higher, not that it is
        strictly lower.
        """
        return self.agrees or self.tier_a_final <= self.tier_b_final


def reconcile(tier_a_equity: Sequence[float], tier_b_equity: Sequence[float]) -> Reconciliation:
    """Compare two equity curves produced from identical configuration."""
    n = min(len(tier_a_equity), len(tier_b_equity))
    if n == 0:
        return Reconciliation(0, 0.0, 0.0, 0.0, 0.0)
    diffs = [abs(tier_a_equity[i] - tier_b_equity[i]) for i in range(n)]
    return Reconciliation(
        days=n,
        max_abs_diff=max(diffs),
        final_diff=tier_a_equity[n - 1] - tier_b_equity[n - 1],
        tier_a_final=tier_a_equity[n - 1],
        tier_b_final=tier_b_equity[n - 1],
    )
