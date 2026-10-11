"""Two intraday papers on the market itself, coded for NSE hours (research 071).

Both papers trade one instrument that *is* the market (SPY) and are flat by the
close. The Indian equivalent with minute history here is NIFTYBEES.

1. **Gao, Han, Li, Zhou — "Intraday Momentum: The First Half-Hour Return
   Predicts the Last Half-Hour Return"** (working paper, Dec 2015; JFE 2018).
   `gao_timing`: at the start of the last half-hour go long if the signal is
   positive and short otherwise, close at the close. Signals: the first
   half-hour return `r1` (previous close to 30 minutes after the open, so it
   includes the overnight gap), the second-to-last half-hour `r12`, or both.

2. **Zarattini, Aziz, Barbon — "Beat the Market: An Effective Intraday
   Momentum Strategy for S&P500 ETF (SPY)"** (v. 3 Feb 2025). `noise_area`:
   a band around the open as wide as the average move by that minute over the
   last 14 days; long above it, short below it, decided only every 30 minutes.
   The base model holds until the opposite band; the final model stops out at
   the nearer of the band and the session VWAP.

### What is the paper's and what is India's

- **Clock.** NSE trades 09:15-15:30. "The first half-hour" is 09:15-09:45,
  the last is 15:00-15:30, and "HH:00 and HH:30" becomes every 30 minutes from
  the open (09:45 ... 15:15). What transfers is the distance from the open and
  the close, not the wall-clock time.
- **Exit.** The papers hold to the close. A broker squares an intraday equity
  position off at 15:25 (research 071), and a short cannot be held any other
  way, so "to the close" is not a trade a short can make. Every rule is run
  twice: `exit_at=None` (as published: the last bar's close) and
  `exit_at=TRADABLE_EXIT` (15:24, before the square-off).
- **Fills.** A decision uses the close of the last completed minute and fills
  at the *open* of the next one, as the second paper does. The first paper
  assumes the price at the half-hour mark itself.
- **Costs.** From `costs.router`, the one cost model, at NSE intraday rates —
  about 4 bps of traded value per round trip in NIFTYBEES — plus an assumed
  slippage per side (A-052). The papers pay a bid-ask spread on SPY, or
  $0.0045 a share.
- **Size.** All of equity, 1x. The second paper's headline result scales
  exposure up to 4x by recent volatility; leverage is not a signal and is not
  tested here.
- **The open is not the first print.** NIFTYBEES's 09:15 open is on average
  71 bps above where it trades a minute later (median 43) and tracks the
  Nifty's overnight gap with a correlation of 0.21; the first bar's *close*
  tracks it at 0.89 (research 071, and 066 on daily data). So a session's
  `anchor` — the "open" every rule here measures from — is the close of the
  first minute, and nothing ever fills at 09:15.
- **The close is the exchange's.** "Previous close" and the published exit use
  the official closing price from the bhavcopy when it is supplied. In India
  that is the volume-weighted price of the last half-hour, not a last trade:
  the 15:29 bar closes 4.7 bps above it on average and moves twice as much as
  an ordinary minute. With no official close the last bar stands in.

Screening runs of published settings: nothing here is searched, so no trial is
spent (the convention of `options/run_strategies.py`).
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, time
from itertools import pairwise
from typing import Any

from eulerlab.costs.schedule import Segment, Side
from eulerlab.intraday.tweezer import Candle

OPEN = time(9, 15)
LAST_BAR = time(15, 29)
SESSION_MINUTES = 375

FIRST_HALF_HOUR_END = 30
"""Minutes after the open: 09:45."""
SECOND_LAST_START = 315
"""14:30."""
LAST_HALF_HOUR_START = 345
"""15:00."""

# ASSUMPTION: A-053 — the square-off time is the broker's and may change.
TRADABLE_EXIT = 369
"""15:24, one minute before the broker's 15:25 square-off (research 071)."""

DECISION_EVERY = 30
"""Zarattini et al. decide at HH:00 and HH:30: every 30 minutes from the open."""

NOISE_LOOKBACK = 14
"""Days averaged for the noise area. The paper's setting."""

MAX_OVERNIGHT_GAP = 0.20
"""A larger gap between sessions is a corporate action or a bad print, not a
return; the day is skipped and counted."""

# ASSUMPTION: A-052 — one basis point of slippage per side, not measured.
SLIPPAGE_BPS = 1.0


def minute_of(stamp: time) -> int:
    return (stamp.hour - OPEN.hour) * 60 + (stamp.minute - OPEN.minute)


@dataclass(frozen=True)
class Session:
    """One normal trading day as arrays indexed by minutes after 09:15.

    `close[m]` is the close of the bar stamped `m`, carried forward across a
    minute with no trade. `open_[m]` is None where there was no bar, so a fill
    is never invented at a minute that did not trade. `vwap[m]` is the session
    VWAP through bar `m` on the typical price (high + low + close) / 3.
    """

    day: date
    open_: tuple[float | None, ...]
    close: tuple[float, ...]
    vwap: tuple[float, ...]
    official_close: float | None = None
    """The exchange's closing price for the day, when the caller has it."""

    @property
    def anchor(self) -> float:
        """The session's opening price for every rule: the first minute's close.

        Not `open_[0]`. An ETF's first print can come from a stray order in a
        thin opening and is not a price anyone could trade at.
        """
        return self.close[0]

    @property
    def last_close(self) -> float:
        return self.close[-1]

    @property
    def settle(self) -> float:
        """The day's close: the official one if known, else the last bar's."""
        return self.official_close if self.official_close is not None else self.close[-1]

    def fill_at(self, minute: int) -> tuple[int, float] | None:
        """The first traded open at or after `minute`: (minute, price)."""
        for m in range(max(minute, 0), SESSION_MINUTES):
            price = self.open_[m]
            if price is not None:
                return m, price
        return None


def sessions(
    candles: Sequence[Candle],
    *,
    official: Mapping[date, float] | None = None,
    min_bars: int = 300,
) -> tuple[list[Session], list[date]]:
    """Group minute bars into normal sessions. Returns (sessions, skipped days).

    `official` maps a day to the exchange's closing price (the bhavcopy close).

    A normal session opens at 09:15, ends with the 15:29 bar and has at least
    `min_bars` bars. Muhurat and special Saturday sessions fail that and are
    skipped: their "first half-hour" is not a first half-hour.
    """
    by_day: dict[date, list[Candle]] = {}
    for candle in candles:
        by_day.setdefault(candle.ts.date(), []).append(candle)

    out: list[Session] = []
    skipped: list[date] = []
    for day in sorted(by_day):
        bars = sorted(by_day[day], key=lambda c: c.ts)
        normal = (
            len(bars) >= min_bars
            and bars[0].ts.time() == OPEN
            and bars[-1].ts.time() == LAST_BAR
            and day.weekday() < 5
        )
        if not normal:
            skipped.append(day)
            continue
        opens: list[float | None] = [None] * SESSION_MINUTES
        closes: list[float] = [0.0] * SESSION_MINUTES
        vwaps: list[float] = [0.0] * SESSION_MINUTES
        at = {minute_of(c.ts.time()): c for c in bars}
        last = bars[0].open
        value = volume = 0.0
        for m in range(SESSION_MINUTES):
            bar = at.get(m)
            if bar is not None:
                opens[m] = bar.open
                last = bar.close
                value += (bar.high + bar.low + bar.close) / 3 * bar.volume
                volume += bar.volume
            closes[m] = last
            vwaps[m] = value / volume if volume else last
        out.append(
            Session(day, tuple(opens), tuple(closes), tuple(vwaps), (official or {}).get(day))
        )
    return out, skipped


# --- trades and results ---------------------------------------------------------

CostFn = Callable[[float, int, Side, date], float]


def nse_intraday_cost(price: float, shares: int, side: Side, day: date) -> float:
    """One fill's charges at NSE intraday rates, from the one cost router."""
    from eulerlab.costs.router import fill_cost

    return fill_cost(
        venue="equity",
        price=price,
        quantity=shares,
        side=side,
        day=day,
        segment=Segment.EQUITY_INTRADAY,
        fund_unit=True,
    )


def no_cost(price: float, shares: int, side: Side, day: date) -> float:
    return 0.0


@dataclass(frozen=True)
class Trade:
    day: date
    direction: int
    """+1 long, -1 short."""
    entry_minute: int
    entry: float
    exit_minute: int
    exit: float
    shares: int
    costs: float
    slippage: float

    @property
    def gross(self) -> float:
        return self.direction * self.shares * (self.exit - self.entry)

    @property
    def net(self) -> float:
        return self.gross - self.costs - self.slippage

    @property
    def notional(self) -> float:
        return self.shares * self.entry


@dataclass
class Result:
    name: str
    capital: float
    days: list[tuple[date, float]] = field(default_factory=list)
    """(day, that day's return on the equity it started with); 0.0 when flat."""
    trades: list[Trade] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def stats(self, *, start: date | None = None, end: date | None = None) -> dict[str, Any]:
        """Performance over [start, end). Sharpe is on daily returns, flat days
        included as zeros, annualised by sqrt(252)."""
        days = [(d, r) for d, r in self.days if (not start or d >= start) and (not end or d < end)]
        trades = [
            t for t in self.trades if (not start or t.day >= start) and (not end or t.day < end)
        ]
        if not days:
            return {"days": 0}
        rets = [r for _, r in days]
        equity = peak = 1.0
        worst = 0.0
        for r in rets:
            equity *= 1 + r
            peak = max(peak, equity)
            worst = min(worst, equity / peak - 1)
        mean = statistics.fmean(rets)
        sd = statistics.pstdev(rets) if len(rets) > 1 else 0.0
        years = len(rets) / 252
        notional = sum(t.notional for t in trades)
        wins = sum(1 for t in trades if t.net > 0)
        return {
            "days": len(rets),
            "days_traded": len({t.day for t in trades}),
            "trades": len(trades),
            "total_return": round(equity - 1, 5),
            "cagr": round(equity ** (1 / years) - 1, 5) if years > 0 and equity > 0 else None,
            "vol": round(sd * math.sqrt(252), 5),
            "sharpe": round(mean / sd * math.sqrt(252), 3) if sd > 0 else None,
            "max_drawdown": round(worst, 5),
            "hit_rate": round(wins / len(trades), 4) if trades else None,
            "long_trades": sum(1 for t in trades if t.direction > 0),
            "short_trades": sum(1 for t in trades if t.direction < 0),
            "gross_bps_per_trade": round(sum(t.gross for t in trades) / notional * 1e4, 3)
            if notional
            else None,
            "net_bps_per_trade": round(sum(t.net for t in trades) / notional * 1e4, 3)
            if notional
            else None,
            "long_net": round(sum(t.net for t in trades if t.direction > 0), 2),
            "short_net": round(sum(t.net for t in trades if t.direction < 0), 2),
            "costs": round(sum(t.costs for t in trades), 2),
            "slippage": round(sum(t.slippage for t in trades), 2),
        }


def _close_out(
    session: Session,
    direction: int,
    entry_minute: int,
    entry: float,
    exit_minute: int,
    exit_price: float,
    shares: int,
    cost: CostFn,
    slippage_bps: float,
) -> Trade:
    buy, sell = (entry, exit_price) if direction > 0 else (exit_price, entry)
    costs = cost(buy, shares, Side.BUY, session.day) + cost(sell, shares, Side.SELL, session.day)
    slip = (entry + exit_price) * shares * slippage_bps / 1e4
    return Trade(
        session.day, direction, entry_minute, entry, exit_minute, exit_price, shares, costs, slip
    )


def _exit_fill(session: Session, exit_at: int | None) -> tuple[int, float]:
    """Where the day's position is closed: at the close as published (the
    official close when known), or the first traded open at/after `exit_at`."""
    if exit_at is not None:
        found = session.fill_at(exit_at)
        if found is not None:
            return found
    return SESSION_MINUTES - 1, session.settle


# --- 1. Gao, Han, Li, Zhou ------------------------------------------------------


def gao_signals(previous_close: float, session: Session) -> tuple[float, float]:
    """(r1, r12): previous close to 09:45, and 14:30 to 15:00.

    Each uses the close of the last minute *before* the mark, which is what is
    known when the order for the last half-hour is placed.
    """
    r1 = session.close[FIRST_HALF_HOUR_END - 1] / previous_close - 1
    r12 = session.close[LAST_HALF_HOUR_START - 1] / session.close[SECOND_LAST_START - 1] - 1
    return r1, r12


def gao_direction(signal: str, r1: float, r12: float) -> int:
    """The paper's eq. (4) and its two-signal rule. 0 means stay out."""
    if signal == "r1":
        return 1 if r1 > 0 else -1
    if signal == "r12":
        return 1 if r12 > 0 else -1
    if signal == "both":
        if r1 > 0 and r12 > 0:
            return 1
        if r1 < 0 and r12 < 0:
            return -1
        return 0
    msg = f"unknown signal {signal!r}"
    raise ValueError(msg)


def gao_timing(
    days: Sequence[Session],
    *,
    signal: str = "r1",
    exit_at: int | None = None,
    capital: float = 1_000_000.0,
    cost: CostFn = nse_intraday_cost,
    slippage_bps: float = SLIPPAGE_BPS,
) -> Result:
    """Trade the last half-hour in the direction of the signal."""
    label = "published exit" if exit_at is None else "tradable exit"
    result = Result(f"gao {signal} ({label})", capital)
    equity = capital
    for previous, session in pairwise(days):
        gap = session.anchor / previous.settle - 1
        if abs(gap) > MAX_OVERNIGHT_GAP:
            result.skipped.append(f"{session.day}: overnight gap {gap:+.1%}")
            continue
        r1, r12 = gao_signals(previous.settle, session)
        direction = gao_direction(signal, r1, r12)
        entry = session.fill_at(LAST_HALF_HOUR_START)
        if direction == 0 or entry is None:
            result.days.append((session.day, 0.0))
            continue
        entry_minute, entry_price = entry
        exit_minute, exit_price = _exit_fill(session, exit_at)
        shares = int(equity // entry_price)
        if shares <= 0 or exit_minute <= entry_minute:
            result.days.append((session.day, 0.0))
            continue
        trade = _close_out(
            session,
            direction,
            entry_minute,
            entry_price,
            exit_minute,
            exit_price,
            shares,
            cost,
            slippage_bps,
        )
        result.trades.append(trade)
        result.days.append((session.day, trade.net / equity))
        equity += trade.net
    return result


# --- 2. Zarattini, Aziz, Barbon -------------------------------------------------


def noise_sigma(history: Sequence[Session]) -> tuple[float, ...]:
    """Average absolute move from the open by each minute, over `history`."""
    return tuple(
        statistics.fmean(abs(s.close[m] / s.anchor - 1) for s in history)
        for m in range(SESSION_MINUTES)
    )


def noise_bounds(
    session: Session, previous_close: float, sigma: Sequence[float], minute: int
) -> tuple[float, float]:
    """(lower, upper) at `minute`, with the paper's overnight-gap adjustment."""
    upper = max(session.anchor, previous_close) * (1 + sigma[minute])
    lower = min(session.anchor, previous_close) * (1 - sigma[minute])
    return lower, upper


def noise_area(
    days: Sequence[Session],
    *,
    vwap_stop: bool = True,
    exit_at: int | None = None,
    lookback: int = NOISE_LOOKBACK,
    capital: float = 1_000_000.0,
    cost: CostFn = nse_intraday_cost,
    slippage_bps: float = SLIPPAGE_BPS,
) -> Result:
    """Long above the noise area, short below, decided every 30 minutes.

    `vwap_stop=False` is the paper's base model: a position is held until the
    price crosses the *opposite* boundary, then reversed. `vwap_stop=True` is
    its final model at 1x size: a long is closed when the price is below the
    higher of the upper boundary and VWAP (a short, above the lower of the
    lower boundary and VWAP), so it is in a position only while the price is
    beyond both.
    """
    stop = "band+vwap stop" if vwap_stop else "opposite band"
    label = "published exit" if exit_at is None else "tradable exit"
    result = Result(f"noise area, {stop} ({label})", capital)
    equity = capital
    for index in range(lookback, len(days)):
        session, previous = days[index], days[index - 1]
        gap = session.anchor / previous.settle - 1
        if abs(gap) > MAX_OVERNIGHT_GAP:
            result.skipped.append(f"{session.day}: overnight gap {gap:+.1%}")
            continue
        sigma = noise_sigma(days[index - lookback : index])
        shares = int(equity // session.anchor)
        end_minute, end_price = _exit_fill(session, exit_at)
        position = 0
        entry_minute, entry_price = 0, 0.0
        day_net = 0.0

        for decide in range(DECISION_EVERY, SESSION_MINUTES, DECISION_EVERY):
            if decide >= end_minute or shares <= 0:
                break
            seen = decide - 1
            price = session.close[seen]
            lower, upper = noise_bounds(session, previous.settle, sigma, seen)
            if vwap_stop:
                vwap = session.vwap[seen]
                want = 1 if price > max(upper, vwap) else -1 if price < min(lower, vwap) else 0
            else:
                want = 1 if price > upper else -1 if price < lower else position
            if want == position:
                continue
            fill = session.fill_at(decide)
            if fill is None or fill[0] >= end_minute:
                break
            at, fill_price = fill
            if position != 0:
                trade = _close_out(
                    session,
                    position,
                    entry_minute,
                    entry_price,
                    at,
                    fill_price,
                    shares,
                    cost,
                    slippage_bps,
                )
                result.trades.append(trade)
                day_net += trade.net
            position, entry_minute, entry_price = want, at, fill_price

        if position != 0:
            trade = _close_out(
                session,
                position,
                entry_minute,
                entry_price,
                end_minute,
                end_price,
                shares,
                cost,
                slippage_bps,
            )
            result.trades.append(trade)
            day_net += trade.net
        result.days.append((session.day, day_net / equity))
        equity += day_net
    return result


def buy_and_hold(days: Sequence[Session], *, capital: float = 1_000_000.0) -> Result:
    """Close-to-close on the same sessions, uncosted: the yardstick."""
    result = Result("buy and hold (close to close, no costs)", capital)
    for previous, session in pairwise(days):
        result.days.append((session.day, session.settle / previous.settle - 1))
    return result
