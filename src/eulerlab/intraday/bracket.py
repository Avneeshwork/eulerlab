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


def _cost(price: float, shares: int, side: Side, day: date, asset_class: str) -> float:
    """What one fill costs, from the one router that knows every venue.

    This used to hold the routing itself, and so did `vector._costs_for` in the
    daily engine — two implementations that diverged: this one knew crypto and
    NSE *intraday*, that one knew NSE *delivery* and no crypto at all. A venue
    handled here and mishandled there produced a plausible number either way.

    `asset_class` has no default. It defaulted to `"equity"`, which billed
    crypto Indian STT, then US Indian STT, then every winning exit Indian STT
    because two of six call sites in this file kept the default after the others
    were fixed.
    """
    from eulerlab.costs.router import fill_cost

    return fill_cost(
        venue=asset_class,
        price=price,
        quantity=shares,
        side=side,
        day=day,
        # Intraday by construction: every signal in this engine is flat at the
        # close, so NSE charges the intraday rates rather than delivery.
        segment=Segment.EQUITY_INTRADAY,
    )


def run(
    plan: Plan,
    forward: Sequence[Candle],
    rules: Rules,
    *,
    session_end_index: int | None = None,
    asset_class: str,
    first_fillable: int = 1,
) -> Trade:
    """Execute `plan` against the candles that followed the signal.

    `forward` starts at the candle **after** the signal, so the signal candle
    itself can never fill the order — the trigger was published on its close.

    `asset_class` has **no default**, and the reason is a pattern rather than
    one bug. It defaulted to `"equity"`, which made this call accidentally
    correct for the NSE scanner and silently wrong everywhere else: crypto
    trades billed Indian STT, then US trades billed Indian STT, then — after
    both were fixed at `_cost` — every *winning* exit billed Indian STT, because
    two of six call sites inside this function had quietly kept the default.

    Each time the wrong number was plausible, which is what let it survive. A
    required argument turns all of that into a TypeError at import.

    `first_fillable` is the first index of `forward` allowed to trigger the
    entry. It defaults to 1, which is what this function has always done: the
    candle straight after the signal could not fill. Every caller already
    passes `forward` starting after the signal, so that skipped one real bar.
    On minute bars that is a minute; on the Tweezer report's 60-minute bars it
    is the hour in which C3 — the confirmation candle the rules define as the
    entry — trades. The Tweezer scan passes 0. The paper signals keep 1 until
    their recorded results are re-run (T-3980).
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
            if index >= first_fillable and candle.high >= plan.entry:
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
            trade.costs += _cost(fill, remaining_1, Side.SELL, day, asset_class)
            remaining_1 = 0
            # The paper signals' rules move the stop to breakeven here; the
            # Tweezer report does not, and leaves the remainder to the trail.
            if not breakeven_done and getattr(rules, "breakeven_after_t1", True):
                stop = max(stop, trade.entry_price)
                breakeven_done = True

        if remaining_2 > 0 and candle.high >= plan.target_2:
            fill = max(plan.target_2, candle.open)
            trade.exits.append(Exit(candle.ts, fill, remaining_2, "target 2"))
            trade.costs += _cost(fill, remaining_2, Side.SELL, day, asset_class)
            remaining_2 = 0
            break

    return trade
