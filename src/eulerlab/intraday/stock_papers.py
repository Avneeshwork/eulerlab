"""Two cross-sectional intraday rules from US stock papers, on Indian hours (research 078).

Operator, 2026-10-13: "add all paper to research library and start coding and
backtesting". Research 077 found no Indian paper that tests an intraday rule
on single stocks beyond research 076, and chose two rules proven on US stocks.

1. **Baltussen, Da and Soebhag, "End-of-Day Reversal"** (working paper, April
   2025), H-0007. Stocks are sorted on the return from the previous close to
   an hour before the close. Half an hour is skipped. Over the last half-hour
   the losers are held long and the winners short.
2. **Heston, Korajczyk and Sadka, "Intraday Patterns in the Cross-section of
   Stock Returns"** (Journal of Finance, 2010), H-0008. Stocks are sorted on
   the return of one half-hour and held over the same half-hour of the next
   session: long the top decile, short the bottom. Only the opening half-hour
   is run, the paper's largest effect.

### What is the source's and what is this project's

- **The clock.** The paper's last half-hour ends at the close. A stock with
  derivatives leaves continuous trading at 15:15 and an intraday position is
  squared off at 15:12 (A-057), so here the sort ends at 14:10, the skipped
  half-hour is 14:10 to 14:40 and the holding window is 14:40 to 15:10, on
  every day of the history. That is a different half-hour from the paper's.
- **The previous close** is the last traded minute of the previous session,
  not the exchange's official close. The two differ by a few basis points;
  the sort is on a day's move, which is a hundred times larger.
- **The first print is never a price** (research 075). The opening half-hour
  runs from the 09:16 open to the 09:44 close, and is entered at 09:16.
- **Groups.** Quintiles and deciles of the stocks that can be measured that
  day, as the papers have them. No stock is weighted by size: the universe is
  already the largest hundred.
- **Costs and size** as `india_papers`: the cost router at NSE intraday rates
  plus an assumed slippage a side (A-056), equity split equally over the
  slots. A long-short book puts half its equity on each side, so its daily
  return is half the papers' long-minus-short spread.

Screening runs of published settings: nothing here is searched, so no trial is
recorded (the convention of `session_papers.py`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from itertools import pairwise

from eulerlab.intraday import india_papers as ip
from eulerlab.intraday import session_papers as sp

SORT_END = 295
"""14:10. The day so far is measured to the 14:09 close: an hour before the
exit, as the paper measures to an hour before the close."""
LATE_ENTRY = 325
"""14:40. The half-hour between is skipped, as in the paper, so the result is
not the bounce between a bid and an offer."""
LATE_EXIT = ip.STOCK_EXIT
"""15:10 (A-057)."""

FIRST_HALF_HOUR_END = sp.FIRST_HALF_HOUR_END
"""09:45. The opening half-hour is entered at 09:16 and left at 09:45."""


@dataclass(frozen=True)
class StockMarks:
    """What the two rules need from one stock on one day, and no more.

    A hundred stocks of full sessions do not fit in memory, so each stock is
    reduced to this as it is read (`india_papers.Marks` does the same).
    """

    day_so_far: float | None
    """Previous session's last close to today's 14:09 close."""
    late: tuple[tuple[int, float], tuple[int, float]] | None
    """Fills at 14:40 and 15:10, when both exist and are in that order."""
    first_half_hour: float | None
    """The 09:16 open to the 09:44 close."""
    early: tuple[tuple[int, float], tuple[int, float]] | None
    """Fills at 09:16 and 09:45."""


def _move(start: float, end: float) -> float | None:
    """A return, or None for a price that cannot be one (a split, a bad print)."""
    if start <= 0 or end <= 0:
        return None
    move = end / start - 1
    return move if abs(move) <= sp.MAX_OVERNIGHT_GAP else None


EXIT_GRACE = 2
"""Minutes an exit may wait for a trade. 15:10 plus two is the broker's
square-off (A-057); a stock silent for longer cannot be left at a price seen
here, so the day is not traded."""


def _pair(
    day: ip.Day, entry_at: int, exit_at: int
) -> tuple[tuple[int, float], tuple[int, float]] | None:
    """Fills at the two times, or None when either is late or missing."""
    entry, exit_ = day.fill_at(entry_at), day.fill_at(exit_at)
    if entry is None or exit_ is None or entry[0] >= exit_at or exit_[0] > exit_at + EXIT_GRACE:
        return None
    return entry, exit_


def stock_marks(days: Sequence[ip.Day]) -> dict[date, StockMarks]:
    """One stock's marks per session. The first session has no previous close."""
    out: dict[date, StockMarks] = {}
    previous: ip.Day | None = None
    for day in days:
        first = day.fill_at(ip.FIRST_TRADABLE)
        out[day.day] = StockMarks(
            day_so_far=(
                _move(previous.close[previous.last], day.close[SORT_END - 1])
                if previous is not None
                else None
            ),
            late=_pair(day, LATE_ENTRY, LATE_EXIT),
            first_half_hour=(
                _move(first[1], day.close[FIRST_HALF_HOUR_END - 1])
                if first is not None and first[0] < FIRST_HALF_HOUR_END
                else None
            ),
            early=_pair(day, ip.FIRST_TRADABLE, FIRST_HALF_HOUR_END),
        )
        previous = day
    return out


def extremes(moves: Mapping[str, float], groups: int) -> tuple[list[str], list[str]]:
    """(lowest group, highest group) when the stocks are cut into `groups`.

    Ties break on the symbol, so the answer does not depend on the order the
    stocks were read in. Too few stocks to fill two groups gives nothing.
    """
    size = len(moves) // groups
    if size < 1 or groups < 2:
        return [], []
    ordered = sorted(moves, key=lambda s: (moves[s], s))
    return ordered[:size], ordered[-size:]


def slots(stocks: int, groups: int, *, long_only: bool = False) -> int:
    """Positions a full day holds: one group, or one on each side."""
    return max(1, stocks // groups) * (1 if long_only else 2)


def end_of_day_reversal_signals(
    universe: Mapping[str, Mapping[date, StockMarks]], *, groups: int, long_only: bool = False
) -> dict[date, dict[str, ip.Signal]]:
    """Each day: buy the group that has fallen most, sell the group that has risen most.

    Sorted on the day so far at 14:10, entered at 14:40, left at 15:10. A
    stock that cannot be filled at both ends is still ranked, as it would be
    live, and simply not traded.
    """
    calendar = sorted({day for marks in universe.values() for day in marks})
    out: dict[date, dict[str, ip.Signal]] = {}
    for when in calendar:
        moves = {
            symbol: move
            for symbol, marks in universe.items()
            if when in marks and (move := marks[when].day_so_far) is not None
        }
        losers, winners = extremes(moves, groups)
        for direction, names in ((1, losers), (-1, [] if long_only else winners)):
            for symbol in names:
                fills = universe[symbol][when].late
                if fills is not None:
                    out.setdefault(when, {})[symbol] = (direction, fills[0], fills[1])
    return out


def same_time_signals(
    universe: Mapping[str, Mapping[date, StockMarks]], *, groups: int = 10
) -> dict[date, dict[str, ip.Signal]]:
    """Each day: buy yesterday's opening half-hour winners, sell its losers.

    Sorted on the previous session's 09:16 to 09:45 return, held over today's.
    A stock is ranked only if it traded in the session immediately before, so
    a lag is always one session and never a stale one.
    """
    calendar = sorted({day for marks in universe.values() for day in marks})
    out: dict[date, dict[str, ip.Signal]] = {}
    for before, when in pairwise(calendar):
        moves = {
            symbol: move
            for symbol, marks in universe.items()
            if before in marks
            and when in marks
            and (move := marks[before].first_half_hour) is not None
        }
        losers, winners = extremes(moves, groups)
        for direction, names in ((1, winners), (-1, losers)):
            for symbol in names:
                fills = universe[symbol][when].early
                if fills is not None:
                    out.setdefault(when, {})[symbol] = (direction, fills[0], fills[1])
    return out


def spread(result: sp.Result, *, sides: int) -> dict[str, float | int | None]:
    """The papers' own measure, from a run without costs.

    `bps_a_day` is the average long-minus-short return (or the long return,
    for one side) in basis points; `t` is its t-statistic over the days. The
    book holds 1/`sides` of its equity on each side, so a day's return is
    scaled back up by `sides`.
    """
    moves = [r * sides for _, r in result.days]
    if len(moves) < 2:
        return {"days": len(moves), "bps_a_day": None, "t": None}
    mean = sum(moves) / len(moves)
    variance = sum((m - mean) ** 2 for m in moves) / (len(moves) - 1)
    t = mean / (variance / len(moves)) ** 0.5 if variance > 0 else None
    return {
        "days": len(moves),
        "bps_a_day": round(mean * 1e4, 3),
        "t": round(t, 2) if t is not None else None,
    }
