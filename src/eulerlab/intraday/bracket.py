"""Executing a bracketed intraday trade, minute by minute.

`tweezer.detect` produces a `Plan`. This runs it: a buy-stop that may never
trigger, two take-profits, a stop that moves to breakeven when the first fills,
a trailing stop after 1.5R, and a forced close before the session ends.

**Why this exists rather than reusing the Tier B engine.** Tier B fills at the
daily close and holds target weights. It has no concept of a resting order, a
price touched intraday, or two exits at different levels. Bolting those on
would change the engine every daily strategy depends on, to serve one intraday
setup — the abstraction would stop meaning anything.

**Where a bar is ambiguous, the pessimistic reading wins.** When one minute's
range contains both the stop and a target, this engine takes the **stop**. It
cannot know which came first within the minute, and the alternative — assuming
the profitable one — is the single most effective way to make an intraday
backtest look good. The same rule applies to the entry: a bar that gaps through
the trigger fills at its open, not at the trigger price, because the trigger was
never available.

**Costs come from the same model as everything else.** No separate intraday
cost path; `CLAUDE.md` requires one, and the reference system this project
learned from had two and had to disable one of them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from eulerlab.costs.model import cost_of_trade
from eulerlab.costs.schedule import Segment, Side
from eulerlab.intraday.tweezer import Candle, Plan, Rules


@dataclass(frozen=True)
class Exit:
    """One leg leaving the position."""

    ts: datetime
    price: float
    shares: int
    reason: str


@dataclass
class Trade:
    """One executed plan, and everything that happened to it."""

    plan: Plan
    entry_ts: datetime | None = None
    entry_price: float = 0.0
    exits: list[Exit] = field(default_factory=list)
    costs: float = 0.0

    @property
    def filled(self) -> bool:
        return self.entry_ts is not None

    @property
    def shares_exited(self) -> int:
        return sum(e.shares for e in self.exits)

    def gross_pnl(self) -> float:
        return sum((e.price - self.entry_price) * e.shares for e in self.exits)

    def net_pnl(self) -> float:
        return self.gross_pnl() - self.costs

    def r_multiple(self) -> float:
        """Profit measured in units of the risk originally taken.

        The only comparable measure across trades of different sizes: a trade
        risking 1% and one risking 1.5% are not comparable in rupees.
        """
        risked = self.plan.r * self.plan.shares
        return self.net_pnl() / risked if risked > 0 else 0.0


def _cost(price: float, shares: int, side: Side, day: date, asset_class: str = "equity") -> float:
    """What one fill costs, on the venue it would actually trade on.

    The segment used to be hardcoded to `EQUITY_INTRADAY`, which meant a crypto
    backtest was charged STT, SEBI turnover fees, stamp duty and GST on
    brokerage — an Indian equity bill for a trade on Delta Exchange, which
    levies none of them. The Delta model has existed and been tested since the
    crypto signals were written; it was simply never wired to the engine that
    charges.

    Delta's own schedule instead: 0.05% taker, plus 18% GST **on the fee**, so
    a round trip is 0.118% of notional. Deliberately not modelled here are
    funding on perpetuals and India's 30% VDA tax — the first because these
    signals close intraday and never hold through a funding window, the second
    because a tax on outcome is not a cost of execution (A-026 to A-028).
    """
    if shares <= 0:
        return 0.0

    if asset_class == "crypto":
        from eulerlab.costs.delta_exchange import futures_fee

        fee = futures_fee(price=Decimal(str(price)), quantity=Decimal(str(shares)))
        return float(fee.total)

    return float(
        cost_of_trade(
            trade_date=day,
            segment=Segment.EQUITY_INTRADAY,
            side=side,
            price=Decimal(str(round(price, 2))),
            quantity=shares,
        ).total
    )


def run(
    plan: Plan,
    forward: Sequence[Candle],
    rules: Rules,
    *,
    session_end_index: int | None = None,
    asset_class: str = "equity",
) -> Trade:
    """Execute `plan` against the candles that followed the signal.

    `forward` starts at the candle **after** the signal, so the signal candle
    itself can never fill the order — the trigger was published on its close.
    """
    trade = Trade(plan=plan)
    remaining_1, remaining_2 = plan.shares_1, plan.shares_2
    stop = plan.stop
    breakeven_done = False
    trailing = False
    peak = 0.0
    last_index = session_end_index if session_end_index is not None else len(forward) - 1

    for index, candle in enumerate(forward):
        # The trade date of THIS candle, never "today". Costs are time-versioned
        # (STT on futures changed 4x inside the sample), so pricing a 2021 trade
        # at today's rates would be silently wrong in a way no test would catch.
        day = candle.ts.date()

        # --- entry ---
        if not trade.filled:
            if index > 0 and candle.high >= plan.entry:
                # A bar that opens above the trigger never offered the trigger
                # price. Fill at the open, which is worse and is what happened.
                fill = max(plan.entry, candle.open)
                trade.entry_ts = candle.ts
                trade.entry_price = fill
                peak = candle.high
                trade.costs += _cost(fill, plan.shares, Side.BUY, day, asset_class)
            elif index >= last_index:
                break
            else:
                continue

        if trade.shares_exited >= plan.shares:
            break

        held = remaining_1 + remaining_2
        if held <= 0:
            break

        # --- forced close at the session end (Step 9) ---
        if index >= last_index:
            trade.exits.append(Exit(candle.ts, candle.close, held, "session end"))
            trade.costs += _cost(candle.close, held, Side.SELL, day, asset_class)
            remaining_1 = remaining_2 = 0
            break

        peak = max(peak, candle.high)

        # --- stop first: the pessimistic reading of an ambiguous bar ---
        if candle.low <= stop:
            fill = min(stop, candle.open)
            reason = "breakeven stop" if breakeven_done else "stop"
            trade.exits.append(Exit(candle.ts, fill, held, reason))
            trade.costs += _cost(fill, held, Side.SELL, day, asset_class)
            remaining_1 = remaining_2 = 0
            break

        # --- trailing stop, once 1.5R has been seen ---
        if not trailing and candle.high >= plan.entry + rules.trail_activate_r * plan.r:
            trailing = True
        if trailing:
            trail = peak * (1.0 - rules.trail_giveback)
            if candle.close < trail:
                trade.exits.append(Exit(candle.ts, candle.close, held, "trailing stop"))
                trade.costs += _cost(candle.close, held, Side.SELL, day, asset_class)
                remaining_1 = remaining_2 = 0
                break

        # --- targets ---
        if remaining_1 > 0 and candle.high >= plan.target_1:
            fill = max(plan.target_1, candle.open)
            trade.exits.append(Exit(candle.ts, fill, remaining_1, "target 1"))
            trade.costs += _cost(fill, remaining_1, Side.SELL, day)
            remaining_1 = 0
            if not breakeven_done:
                stop = max(stop, trade.entry_price)
                breakeven_done = True

        if remaining_2 > 0 and candle.high >= plan.target_2:
            fill = max(plan.target_2, candle.open)
            trade.exits.append(Exit(candle.ts, fill, remaining_2, "target 2"))
            trade.costs += _cost(fill, remaining_2, Side.SELL, day)
            remaining_2 = 0
            break

    return trade
