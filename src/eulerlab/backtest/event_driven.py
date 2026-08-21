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
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from functools import partial
from zoneinfo import ZoneInfo

from eulerlab.backtest.events import Fill as EventFill
from eulerlab.backtest.events import (
    Order,
    Portfolio,
    Rejection,
    plan_orders,
    target_quantities,
)
from eulerlab.backtest.execution import Executor, SimulatedExecutor
from eulerlab.backtest.strategy import MarketView, Strategy, normalise
from eulerlab.costs.model import Brokerage
from eulerlab.features.panel import (
    PanelRow,
    assert_adjustable,
    by_symbol,
    load_price_factor_store,
    trading_days,
)

IST = ZoneInfo("Asia/Kolkata")
FAR_FUTURE = datetime(2999, 1, 1, tzinfo=IST)


@dataclass
class TierBResult:
    strategy: str
    days: list[date] = field(default_factory=list)
    equity: list[float] = field(default_factory=list)
    portfolio: Portfolio | None = None
    starting_cash: float = 1_000_000.0
    cost_mode: str = "realistic"
    orders: list[Order] = field(default_factory=list)
    final_marks: dict[str, float] = field(default_factory=dict)
    """The prices open positions were valued at on the last day.

    Returned rather than left for a caller to reconstruct. The report's
    per-instrument attribution has to mark open positions at exactly what the
    equity curve marked them at, and rebuilding those prices from the panel
    got it wrong twice — raw closes instead of adjusted, then an index whose
    symbol set did not match. Handing back the dict the engine already has
    removes the whole class of mismatch.
    """

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
    adjusted_index: dict[str, dict[date, float]] | None = None,
    cost_multiplier: float = 1.0,
    executor: Executor | None = None,
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

    # Marking and execution use a **fully back-adjusted** series, adjusted once
    # as of the end of the run, and the reason is a bug this replaced.
    #
    # Position marking needs a *consistent* series. Prices are raw in the panel
    # and a corporate action moves them violently: VIVIDHA prints 1,290.55 then
    # 140.75 the next day on an 11:1 action. The share count a holder owns rises
    # by the same factor, but the engine holds a fixed integer, so marking from
    # the raw series booked an 89% loss where a holder lost nothing. Measured on
    # the real panel, this dragged an eleven-year buy-and-hold to -3.3%.
    #
    # Point-in-time adjustment cannot fix marking, only signals: if the divisor
    # changes as time passes, a position's value jumps on the day the
    # adjustment updates rather than on the ex-date. So the series used for
    # money is adjusted uniformly.
    #
    # The trade-off, stated rather than hidden: this means knowing that a split
    # is coming. A split is a change of units, not information about returns —
    # it cannot tell a strategy which way a price will move — which is why this
    # is standard practice. Signals still see point-in-time adjusted prices via
    # `_view_history`, so nothing about *ranking* uses future knowledge.
    _events: dict[str, list[tuple[date, float]]] = {}
    for record in load_price_factor_store().query(as_of=FAR_FUTURE):
        _events.setdefault(record.key, []).append((record.event_time.date(), record.value))
    for _ev in _events.values():
        _ev.sort()

    def _adjusted(rows_: list[PanelRow]) -> dict[date, float]:
        events = _events.get(rows_[-1].isin, []) if rows_ else []
        if not events:
            return {row.day: row.close for row in rows_}
        out: dict[date, float] = {}
        cumulative = 1.0
        cursor = len(events) - 1
        for row in reversed(rows_):
            while cursor >= 0 and events[cursor][0] > row.day:
                cumulative *= events[cursor][1]
                cursor -= 1
            out[row.day] = row.close / cumulative
        return out

    price_index: dict[str, dict[date, float]] = (
        adjusted_index
        if adjusted_index is not None
        else {symbol: _adjusted(rows_) for symbol, rows_ in histories.items()}
    )
    ordered_days: dict[str, list[date]] = {
        symbol: [row.day for row in rows_] for symbol, rows_ in histories.items()
    }

    assert_adjustable(rows)
    lookback = strategy.lookback
    # Indexed once per run. `factor_as_of` scans the whole store per call, and
    # calling it per row per symbol per rebalance took the test suite from 5
    # seconds to nearly nine minutes. The factors for one instrument are a
    # short sorted list, so one pass builds what every lookup needs.
    _factor_events: dict[str, list[tuple[date, float]]] = {}
    for record in load_price_factor_store().query(as_of=FAR_FUTURE):
        _factor_events.setdefault(record.key, []).append((record.event_time.date(), record.value))
    for events in _factor_events.values():
        events.sort()

    def _view_history(today: date) -> dict[str, list[PanelRow]]:
        """Rows up to `today`, capped at the lookback and **adjusted as of today**.

        Sliced by bisect on the pre-sorted day list rather than filtered, and
        capped rather than complete: handing a 253-day feature 2,869 days of
        history was costing ~90% of the run time for data it never reads.

        The adjustment happens here, not in the panel, because the correct
        adjustment depends on the date you are standing on. A strategy deciding
        on 2018-01-15 must see prices adjusted for corporate actions up to that
        date and **not** for a bonus that goes ex in May. Baking it into a
        static panel cannot express that, which is why the first attempt
        silently applied no adjustment at all.
        """
        out: dict[str, list[PanelRow]] = {}
        for symbol, rows_ in histories.items():
            end = bisect_right(ordered_days[symbol], today)
            if end == 0:
                continue
            start = max(0, end - lookback) if lookback else 0
            window = rows_[start:end]

            # Only actions already knowable on `today`. One still in the future
            # is exactly what a strategy standing here must not see.
            events = [e for e in _events.get(window[-1].isin, []) if e[0] <= today]
            if not events:
                out[symbol] = window
                continue

            # Walk backwards accumulating the divisor: a price is divided by
            # every action strictly after it. One pass instead of a full store
            # query per row.
            adjusted: list[PanelRow] = []
            cumulative = 1.0
            cursor = len(events) - 1
            for row in reversed(window):
                while cursor >= 0 and events[cursor][0] > row.day:
                    cumulative *= events[cursor][1]
                    cursor -= 1
                adjusted.append(
                    row if cumulative == 1.0 else replace(row, close=row.close / cumulative)
                )
            adjusted.reverse()
            out[symbol] = adjusted
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

    engine: Executor = executor or SimulatedExecutor(
        cost_mode=cost_mode, brokerage=brokerage, cost_multiplier=cost_multiplier
    )
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

            desired = target_quantities(equity, targets, partial(traded_price, day=fill_day))

            # --- create orders ---
            # `plan_orders` is shared verbatim with paper trading and live.
            # Two implementations of "what do I have to trade to get there"
            # would put a difference of our own making into every reality-gap
            # report, which is the one number that must be about the market.
            orders: list[Order]
            orders, sequence = plan_orders(
                strategy_id=strategy.describe(),
                signal_day=today,
                holdings=portfolio.holdings(),
                desired=desired,
                seq_start=sequence,
            )
            result.orders.extend(orders)

            # --- fill or reject ---
            # The executor is the only part of this loop that paper trading
            # replaces. Everything above it — the view, the weights, the
            # sizing, the orders — is shared code, so any difference between a
            # backtest and a paper run is the executor's doing and nothing else.
            for order in orders:
                outcome = engine.execute(
                    order, day=fill_day, price=traded_price(order.symbol, fill_day)
                )
                if isinstance(outcome, Rejection):
                    portfolio.rejections.append(outcome)
                    continue
                portfolio.apply(outcome)

        # --- mark to market ---
        marks = {
            symbol: price
            for symbol in portfolio.holdings()
            if (price := mark_price(symbol, fill_day)) is not None
        }
        result.days.append(fill_day)
        result.equity.append(portfolio.equity(marks))
        result.final_marks = marks

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
