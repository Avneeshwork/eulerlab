"""Five intraday rules from Indian-market sources, coded as written (research 076).

Operator, 2026-10-12: "work on 5 intraday strategy from recent paper/article
which have possibility to outperform in indian market ... on indian market
purely". Every source below studies NSE and nothing else.

1. **Rao, "All About Opening Range Breakout (ORB) - Part 1"** (Zerodha, *In The
   Money*, 2 March 2026). `late_orb`: the range is the whole first hour or two
   (09:15-10:15, 09:15-11:15); a 3-minute close beyond it is followed, with
   the stop at the other side of the range.
2. **Doraigari, "Best Intraday Breakout Strategy for Nifty 50"** (IntradayLab,
   30 March 2026). `orb_two_r`: the 09:15-09:45 range, entry on the break,
   stop at the other side, target at twice the risk, out at 14:30.
3. **Wang and Gangwar, "Optimizing Intraday Breakout Strategies on the NSE"**
   (SSRN 5198458, 2025). `orb_volume`: a 5, 15 or 30 minute opening range in
   a stock, a breakout that needs a volume surge of 1.2 or 1.5 times, held 2,
   3 or 5 bars. Only the abstract could be read; see `SURGE_LOOKBACK`.
4. **"Hedging Demand and Intraday Momentum within the Indian Stock Market"**
   (2024), the design of Baltussen, Da, Lammers and Martens (JFE 2021) applied
   to Nifty futures. `rest_of_day`: the return from the previous close to
   15:00 decides the direction of the last half-hour. The Indian paper's full
   text could not be fetched; the rule is the design it says it follows.
5. **Tripathi and Aggarwal, "Prior Return Effect in Indian Stock Market: An
   Intra-day Analysis"** (IJFM 5(1), 2015; data 2010). `extreme_reversal`: at
   09:15 and at 12:15 the three stocks with the highest and the three with
   the lowest market-adjusted half-hour return are faded. Read in full. Not
   recent; kept because it is the only Indian intraday paper found that was
   both readable and a rule.

### What is the source's and what is this project's

- **The first print is never a price.** A range, a signal and a fill all start
  from the second minute. NIFTYBEES's 09:15 print sits on average 71 bps from
  where it trades a minute later, and three opening-range results stored here
  were measuring that print (research 075, HISTORY 20). Neither ORB article
  says how it treats the first bar; both use the index, which has no such
  print.
- **Instrument.** The ORB articles and the momentum paper trade the Nifty
  index or its future. Minute history here is NIFTYBEES, the Nifty 50 ETF.
- **Exit.** NIFTYBEES at 15:24 (`session_papers.TRADABLE_EXIT`). Stocks at
  15:10 on every day of the history: since 3 August 2026 a stock with
  derivatives stops trading continuously at 15:15 and an intraday position is
  squared off at 15:12 (research 071, 076). One exit time for the whole
  history keeps the before and after comparable.
- **Costs.** `costs.router` at NSE intraday rates for the day of the trade,
  plus an assumed slippage a side (A-052, A-056).
- **Size.** 1x. A stock portfolio splits equity equally across its slots.

Screening runs of published settings: nothing here is searched, so no trial is
recorded (the convention of `session_papers.py`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from pathlib import Path

from eulerlab.costs.schedule import Segment, Side
from eulerlab.intraday import session_papers as sp
from eulerlab.paths import data_path

MINUTES = sp.SESSION_MINUTES
MINUTE_ROOT = data_path("landing/kite_minute")

FIRST_TRADABLE = 1
"""09:16. The first print is skipped everywhere; see the module docstring."""

# ASSUMPTION: A-057 — the 15:12 square-off for stocks in the closing auction.
STOCK_EXIT = 355
"""15:10, two minutes before the broker squares off a stock that closes in
the auction (research 071). Used for every day of the history."""

LAST_HALF_HOUR = sp.LAST_HALF_HOUR_START
MIN_BARS = 300
MIN_PRICE = 10.0
"""Tripathi and Aggarwal drop a stock priced at Rs 10 or less."""

# ASSUMPTION: A-056 — slippage on a stock, per side. Not measured.
STOCK_SLIPPAGE_BPS = 2.0

# ASSUMPTION: A-058 — what "volume surge" is measured against (abstract only).
SURGE_LOOKBACK = 20
"""Sessions averaged for a bar's usual volume. The abstract of Wang and
Gangwar gives the thresholds (1.2x, 1.5x) and not the base; the same bar of
the day over the last 20 sessions is the common definition and is used here."""

TICK = 30
"""Tripathi and Aggarwal measure in 30-minute intervals from 09:15."""
EXTREMES = 3
"""Stocks faded on each side, as in the paper."""


@dataclass(frozen=True)
class Day:
    """One session of one instrument, indexed by minutes after 09:15.

    `open_`, `high` and `low` are None in a minute with no trade, so nothing
    fills or triggers there. `close` is carried forward across such a minute.
    `last` is the last minute that traded: 374 normally, 359 for a stock that
    closes in the auction.
    """

    day: date
    open_: tuple[float | None, ...]
    high: tuple[float | None, ...]
    low: tuple[float | None, ...]
    close: tuple[float, ...]
    volume: tuple[float, ...]
    last: int

    def fill_at(self, minute: int) -> tuple[int, float] | None:
        """The first traded open at or after `minute`: (minute, price)."""
        for m in range(max(minute, FIRST_TRADABLE), self.last + 1):
            price = self.open_[m]
            if price is not None:
                return m, price
        return None

    def span(self, start: int, end: int) -> tuple[float, float] | None:
        """(high, low) over minutes [start, end), or None if none traded."""
        highs = [h for h in self.high[start:end] if h is not None]
        lows = [x for x in self.low[start:end] if x is not None]
        return (max(highs), min(lows)) if highs and lows else None


def days_from_rows(
    rows: Mapping[str, Mapping[int, tuple[float, float, float, float, float]]],
) -> list[Day]:
    """Normal sessions from {day: {minute: (open, high, low, close, volume)}}.

    Normal: a weekday that opens at 09:15, has at least `MIN_BARS` bars and
    trades to 15:14 or later. Muhurat and Saturday sessions fail that.
    """
    out: list[Day] = []
    for key in sorted(rows):
        bars = rows[key]
        day = date.fromisoformat(key)
        last = max(bars)
        if day.weekday() >= 5 or 0 not in bars or len(bars) < MIN_BARS or last < 359:
            continue
        opens: list[float | None] = [None] * MINUTES
        highs: list[float | None] = [None] * MINUTES
        lows: list[float | None] = [None] * MINUTES
        closes = [0.0] * MINUTES
        volumes = [0.0] * MINUTES
        carried = bars[0][0]
        for m in range(MINUTES):
            bar = bars.get(m)
            if bar is not None:
                opens[m], highs[m], lows[m], carried, volumes[m] = bar
            closes[m] = carried
        out.append(
            Day(day, tuple(opens), tuple(highs), tuple(lows), tuple(closes), tuple(volumes), last)
        )
    return out


def load(symbol: str, root: Path | None = None) -> list[Day]:
    """A symbol's normal sessions from the minute archive.

    With no `root` the files come through `landing_reader`, which downloads
    from the bucket any that were pruned from this machine: most stocks keep
    only their last year here, and a run on local files alone would quietly
    cover one year and call it five (seen 2026-10-12).

    One bar per timestamp: the 60-day files overlap, and the file that sorts
    last wins, as `intraday.store.fetch` has it. Read here column by column
    because `fetch` builds an object per bar and takes ten seconds a symbol.
    """
    import io

    import pyarrow.parquet as pq

    blobs: list[bytes]
    if root is not None:
        blobs = [path.read_bytes() for path in sorted((root / symbol).glob("*.parquet"))]
    else:
        from eulerlab.ingest import landing_reader

        blobs = [landing_reader.read(path) for path in archive_files(symbol)]
    rows: dict[str, dict[int, tuple[float, float, float, float, float]]] = {}
    for blob in blobs:
        table = pq.read_table(
            io.BytesIO(blob), columns=["ts", "open", "high", "low", "close", "volume"]
        )
        columns = [table.column(name).to_pylist() for name in table.column_names]
        for stamp, o, h, low, c, v in zip(*columns, strict=True):
            if o is None or h is None or low is None or c is None:
                continue  # a hole in the vendor's data, not a zero
            minute = (int(stamp[11:13]) - 9) * 60 + int(stamp[14:16]) - 15
            if 0 <= minute < MINUTES:
                rows.setdefault(stamp[:10], {})[minute] = (o, h, low, c, float(v or 0))
    return days_from_rows(rows)


def archive_files(symbol: str) -> list[str]:
    """Every minute file of `symbol`, here or in the bucket, oldest first."""
    from eulerlab.ingest import landing_reader

    return sorted(landing_reader.available("kite_minute", f"{symbol}/*.parquet"))


# --- costs and bookkeeping -----------------------------------------------------------


def stock_cost(price: float, shares: int, side: Side, day: date) -> float:
    """One fill in a share at NSE intraday rates, from the one cost router."""
    from eulerlab.costs.router import fill_cost

    return fill_cost(
        venue="equity",
        price=price,
        quantity=shares,
        side=side,
        day=day,
        segment=Segment.EQUITY_INTRADAY,
    )


def _trade(
    day: date,
    direction: int,
    entry: tuple[int, float],
    exit_: tuple[int, float],
    shares: int,
    cost: sp.CostFn,
    slippage_bps: float,
) -> sp.Trade:
    buy, sell = (entry[1], exit_[1]) if direction > 0 else (exit_[1], entry[1])
    costs = cost(buy, shares, Side.BUY, day) + cost(sell, shares, Side.SELL, day)
    slip = (entry[1] + exit_[1]) * shares * slippage_bps / 1e4
    return sp.Trade(day, direction, entry[0], entry[1], exit_[0], exit_[1], shares, costs, slip)


def _stopped(
    day: Day, direction: int, start: int, end: int, stop: float, target: float | None
) -> tuple[int, float] | None:
    """The first minute in [start, end) where the stop or the target is hit.

    A bar that opens beyond a level fills at its open, not at the level. When
    one bar spans both levels the stop is taken: the order inside a minute is
    not known and the worse answer is the safe one.
    """
    for m in range(start, min(end, day.last + 1)):
        open_, high, low = day.open_[m], day.high[m], day.low[m]
        if open_ is None or high is None or low is None:
            continue
        if direction > 0:
            if low <= stop:
                return m, min(open_, stop)
            if target is not None and high >= target:
                return m, max(open_, target)
        else:
            if high >= stop:
                return m, max(open_, stop)
            if target is not None and low <= target:
                return m, min(open_, target)
    return None


# --- 1. Rao (Zerodha): the long opening range ---------------------------------------


def late_orb_trade(
    day: Day, *, window_end: int, bar: int = 3, exit_at: int
) -> tuple[int, tuple[int, float], tuple[int, float]] | None:
    """(direction, entry, exit) for one day, or None when nothing breaks out."""
    held = day.span(FIRST_TRADABLE, window_end)
    if held is None:
        return None
    top, bottom = held
    for start in range(window_end, exit_at - bar, bar):
        close = day.close[start + bar - 1]
        direction = 1 if close > top else -1 if close < bottom else 0
        if direction == 0:
            continue
        entry = day.fill_at(start + bar)
        if entry is None or entry[0] >= exit_at:
            return None
        stop = bottom if direction > 0 else top
        exit_ = _stopped(day, direction, entry[0], exit_at, stop, None) or day.fill_at(exit_at)
        return (direction, entry, exit_) if exit_ is not None else None
    return None


def late_orb(
    days: Sequence[Day],
    *,
    window_end: int = 120,
    exit_at: int = sp.TRADABLE_EXIT,
    capital: float = 1_000_000.0,
    cost: sp.CostFn = sp.nse_intraday_cost,
    slippage_bps: float = sp.SLIPPAGE_BPS,
) -> sp.Result:
    """Follow the first 3-minute close outside the 09:15 to `window_end` range.

    The article states the entry and the stop. It gives no exit time and no
    target, so a position that is not stopped is closed at `exit_at`.
    """
    result = sp.Result(f"late orb, range to minute {window_end}", capital)
    equity = capital
    for day in days:
        found = late_orb_trade(day, window_end=window_end, exit_at=exit_at)
        shares = int(equity // found[1][1]) if found else 0
        if found is None or shares <= 0:
            result.days.append((day.day, 0.0))
            continue
        trade = _trade(day.day, found[0], found[1], found[2], shares, cost, slippage_bps)
        result.trades.append(trade)
        result.days.append((day.day, trade.net / equity))
        equity += trade.net
    return result


# --- 2. Doraigari (IntradayLab): 30 minutes, twice the risk -------------------------


def orb_two_r_trade(
    day: Day, *, range_end: int = 30, reward: float = 2.0, time_exit: int = 315
) -> tuple[int, tuple[int, float], tuple[int, float]] | None:
    """(direction, entry, exit). Entry is a stop order resting at the range edge."""
    held = day.span(FIRST_TRADABLE, range_end)
    if held is None or held[0] <= held[1]:
        return None
    top, bottom = held
    for m in range(range_end, min(time_exit, day.last + 1)):
        open_, high, low = day.open_[m], day.high[m], day.low[m]
        if open_ is None or high is None or low is None:
            continue
        up, down = high > top, low < bottom
        if up and down:
            return None  # both sides in one minute: which came first is unknown
        if not (up or down):
            continue
        direction = 1 if up else -1
        # A bar that opens beyond the edge fills at its open, not at the edge.
        entry = (m, max(open_, top) if up else min(open_, bottom))
        risk = top - bottom
        stop = bottom if up else top
        target = entry[1] + direction * reward * risk
        exit_ = _stopped(day, direction, m + 1, time_exit, stop, target) or day.fill_at(time_exit)
        return (direction, entry, exit_) if exit_ is not None else None
    return None


def orb_two_r(
    days: Sequence[Day],
    *,
    capital: float = 1_000_000.0,
    cost: sp.CostFn = sp.nse_intraday_cost,
    slippage_bps: float = sp.SLIPPAGE_BPS,
) -> sp.Result:
    """The 09:15-09:45 range: in on the break, out at the stop, 2R or 14:30."""
    result = sp.Result("orb 30 minutes, 2R target, out at 14:30", capital)
    equity = capital
    for day in days:
        found = orb_two_r_trade(day)
        shares = int(equity // found[1][1]) if found else 0
        if found is None or shares <= 0:
            result.days.append((day.day, 0.0))
            continue
        trade = _trade(day.day, found[0], found[1], found[2], shares, cost, slippage_bps)
        result.trades.append(trade)
        result.days.append((day.day, trade.net / equity))
        equity += trade.net
    return result


# --- 3. Wang and Gangwar: a breakout that needs volume ------------------------------


def bar_volumes(day: Day, size: int) -> list[float]:
    """Volume of each `size`-minute bar of the day, from 09:15."""
    return [sum(day.volume[m : m + size]) for m in range(0, MINUTES - size + 1, size)]


def orb_volume_trade(
    day: Day,
    usual: Sequence[float],
    *,
    size: int,
    surge: float,
    hold: int,
    exit_at: int = STOCK_EXIT,
) -> tuple[int, tuple[int, float], tuple[int, float]] | None:
    """(direction, entry, exit). `usual[k]` is bar k's average volume lately."""
    held = day.span(FIRST_TRADABLE, size)
    if held is None:
        return None
    top, bottom = held
    volumes = bar_volumes(day, size)
    for k in range(1, len(volumes)):
        start = k * size
        if start + size >= exit_at:
            return None
        close = day.close[start + size - 1]
        direction = 1 if close > top else -1 if close < bottom else 0
        if direction == 0:
            continue
        if usual[k] <= 0 or volumes[k] < surge * usual[k]:
            continue  # a breakout without the surge is not a signal; keep looking
        entry = day.fill_at(start + size)
        if entry is None or entry[0] >= exit_at:
            return None
        exit_ = day.fill_at(min(entry[0] + hold * size, exit_at))
        return (direction, entry, exit_) if exit_ is not None and exit_[0] > entry[0] else None
    return None


def orb_volume_signals(
    days: Sequence[Day], *, size: int, surge: float, hold: int
) -> dict[date, tuple[int, tuple[int, float], tuple[int, float]]]:
    """Every day's trade for one stock, using only earlier days' volume."""
    out: dict[date, tuple[int, tuple[int, float], tuple[int, float]]] = {}
    history: list[list[float]] = []
    for day in days:
        if len(history) >= SURGE_LOOKBACK:
            recent = history[-SURGE_LOOKBACK:]
            usual = [sum(v[k] for v in recent) / SURGE_LOOKBACK for k in range(len(recent[0]))]
            found = orb_volume_trade(day, usual, size=size, surge=surge, hold=hold)
            if found is not None:
                out[day.day] = found
        history.append(bar_volumes(day, size))
    return out


# --- 4. Rest-of-day momentum into the last half-hour --------------------------------


def rest_of_day(
    days: Sequence[Day],
    official: Mapping[date, float],
    *,
    exit_at: int = sp.TRADABLE_EXIT,
    capital: float = 1_000_000.0,
    cost: sp.CostFn = sp.nse_intraday_cost,
    slippage_bps: float = sp.SLIPPAGE_BPS,
) -> sp.Result:
    """Trade 15:00 to `exit_at` in the direction of the day so far.

    The day so far is the return from the previous official close to the
    14:59 close: Baltussen et al.'s "rest of day", which includes the
    overnight gap. `session_papers.gao_timing` tested a different signal on
    the same half-hour (the first half-hour alone, and 14:30 to 15:00).
    """
    result = sp.Result("rest of day into the last half-hour", capital)
    equity = capital
    for previous, day in pairwise(days):
        before = official.get(previous.day, previous.close[previous.last])
        signal = day.close[LAST_HALF_HOUR - 1] / before - 1
        entry, exit_ = day.fill_at(LAST_HALF_HOUR), day.fill_at(exit_at)
        if abs(signal) > sp.MAX_OVERNIGHT_GAP:
            result.skipped.append(f"{day.day}: move of {signal:+.1%} since the last close")
            continue
        shares = int(equity // entry[1]) if entry else 0
        if signal == 0 or entry is None or exit_ is None or exit_[0] <= entry[0] or shares <= 0:
            result.days.append((day.day, 0.0))
            continue
        trade = _trade(day.day, 1 if signal > 0 else -1, entry, exit_, shares, cost, slippage_bps)
        result.trades.append(trade)
        result.days.append((day.day, trade.net / equity))
        equity += trade.net
    return result


# --- 5. Tripathi and Aggarwal: fade the extremes ------------------------------------


def half_hour_return(previous: Day | None, day: Day, event: str) -> float | None:
    """The 30-minute return that ends at the event.

    `open`: the previous session's 15:14 close to the first minute's close
    (the paper compares 09:15 with 15:15 the day before). `midday`: 11:45 to
    12:15. None when the stock cannot be measured or is priced at Rs 10 or less.
    """
    if event == "open":
        if previous is None:
            return None
        start, end = previous.close[359], day.close[0]
    else:
        start, end = day.close[149], day.close[179]
    if start <= MIN_PRICE or end <= MIN_PRICE:
        return None
    move = end / start - 1
    return move if abs(move) <= sp.MAX_OVERNIGHT_GAP else None


def extreme_picks(moves: Mapping[str, float]) -> tuple[list[str], list[str]]:
    """(losers to buy, winners to sell): the three most extreme on each side.

    Measured against the equal-weighted average of the stocks given, which
    stands in for the Nifty the paper adjusts by. Ties break on the symbol so
    the answer does not depend on the order the stocks were read in.
    """
    if len(moves) < 2 * EXTREMES + 1:
        return [], []
    ordered = sorted(moves, key=lambda s: (moves[s], s))
    return ordered[:EXTREMES], ordered[-EXTREMES:]


Signal = tuple[int, tuple[int, float], tuple[int, float]]
"""(direction, (entry minute, price), (exit minute, price))."""


def portfolio(
    name: str,
    calendar: Sequence[date],
    signals: Mapping[date, Mapping[str, Signal]],
    *,
    slots: int,
    capital: float = 1_000_000.0,
    cost: sp.CostFn = stock_cost,
    slippage_bps: float = STOCK_SLIPPAGE_BPS,
) -> sp.Result:
    """Trade each day's signals with equity split equally over `slots`.

    A day with fewer signals than slots leaves the rest in cash; a day with
    more takes them in symbol order, which no rule here can cause.
    """
    result = sp.Result(name, capital)
    equity = capital
    for day in calendar:
        net = 0.0
        for symbol in sorted(signals.get(day, {}))[:slots]:
            direction, entry, exit_ = signals[day][symbol]
            shares = int(equity / slots // entry[1])
            if shares <= 0:
                continue
            trade = _trade(day, direction, entry, exit_, shares, cost, slippage_bps)
            result.trades.append(trade)
            net += trade.net
        result.days.append((day, net / equity))
        equity += net
    return result


REVERSAL_EVENTS = {"open": 0, "midday": 179}
"""Event name to the minute whose close decides it: 09:15 and 12:14."""
REVERSAL_HOLDS = (1, 5)
"""Half-hours held. The paper follows five; it reports that a fall corrects
within the first and a rise takes the full five."""


@dataclass(frozen=True)
class Marks:
    """What `extreme_reversal` needs from one stock on one day, and no more.

    A universe of full sessions does not fit in memory (a hundred stocks is
    238 million numbers), so each stock is reduced to this as it is read.
    """

    moves: dict[str, float | None]
    """Event name to the half-hour return that ends there."""
    fills: dict[int, tuple[int, float] | None]
    """Minute to the first traded open at or after it."""


def reversal_marks(days: Sequence[Day]) -> dict[date, Marks]:
    out: dict[date, Marks] = {}
    previous: Day | None = None
    for day in days:
        minutes = set()
        for decide in REVERSAL_EVENTS.values():
            minutes.add(decide + 1)
            minutes.update(min(decide + 1 + h * TICK - 1, STOCK_EXIT) for h in REVERSAL_HOLDS)
        out[day.day] = Marks(
            {event: half_hour_return(previous, day, event) for event in REVERSAL_EVENTS},
            {m: day.fill_at(m) for m in minutes},
        )
        previous = day
    return out


def extreme_reversal_signals(
    universe: Mapping[str, Mapping[date, Marks]], *, event: str, hold_ticks: int
) -> dict[date, dict[str, Signal]]:
    """Each day's six trades: buy the three losers, sell the three winners.

    Decided on the close of the event minute and filled at the next traded
    open; closed `hold_ticks` half-hours after the event.
    """
    decide = REVERSAL_EVENTS[event]
    leave = min(decide + hold_ticks * TICK, STOCK_EXIT)
    calendar = sorted({day for marks in universe.values() for day in marks})
    out: dict[date, dict[str, Signal]] = {}
    for when in calendar:
        moves = {
            symbol: move
            for symbol, marks in universe.items()
            if when in marks and (move := marks[when].moves[event]) is not None
        }
        losers, winners = extreme_picks(moves)
        for direction, names in ((1, losers), (-1, winners)):
            for symbol in names:
                fills = universe[symbol][when].fills
                entry, exit_ = fills[decide + 1], fills[leave]
                if entry is not None and exit_ is not None and exit_[0] > entry[0]:
                    out.setdefault(when, {})[symbol] = (direction, entry, exit_)
    return out
