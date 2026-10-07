"""Prices as the engines see them: two series, kept apart on purpose.

Shared by both engines, which carried identical copies of this code — three
copies of the back-adjustment, counting `build_adjusted_index`. One copy is
the `CLAUDE.md` rule about a single path, applied to the code whose output
every strategy and every equity curve reads.

**Money uses `back_adjusted`**: closes divided by every corporate action in
the store, so a split does not look like a crash. **Signals use
`HistoryWindows`**: adjusted only for actions knowable on the decision date,
so a strategy never learns of a split before it is announced. Why the two
differ, and why neither can stand in for the other, is in each docstring.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from datetime import date

from eulerlab.features.panel import FactorEvents, PanelRow


def back_adjusted(rows: Sequence[PanelRow], events: FactorEvents) -> dict[date, float]:
    """One symbol's closes, adjusted once as of the end of the data.

    Marking and execution use a **fully back-adjusted** series, and the reason
    is a bug this replaced.

    Position marking needs a *consistent* series. Prices are raw in the panel
    and a corporate action moves them violently: VIVIDHA prints 1,290.55 then
    140.75 the next day on an 11:1 action. The share count a holder owns rises
    by the same factor, but the engine holds a fixed integer, so marking from
    the raw series booked an 89% loss where a holder lost nothing. Measured on
    the real panel, this dragged an eleven-year buy-and-hold to -3.3%.

    Point-in-time adjustment cannot fix marking, only signals: if the divisor
    changes as time passes, a position's value jumps on the day the adjustment
    updates rather than on the ex-date. So the series used for money is
    adjusted uniformly.

    The trade-off, stated rather than hidden: this means knowing that a split
    is coming. A split is a change of units, not information about returns —
    it cannot tell a strategy which way a price will move — which is why this
    is standard practice. Signals still see point-in-time adjusted prices via
    `HistoryWindows`, so nothing about *ranking* uses future knowledge.

    `rows` is one symbol's history, oldest first; the factors are those of the
    instrument it ends on.
    """
    actions = events.get(rows[-1].isin, ()) if rows else ()
    if not actions:
        return {row.day: row.close for row in rows}
    out: dict[date, float] = {}
    cumulative = 1.0
    cursor = len(actions) - 1
    for row in reversed(rows):
        while cursor >= 0 and actions[cursor][0] > row.day:
            cumulative *= actions[cursor][1]
            cursor -= 1
        out[row.day] = row.close / cumulative
    return out


class HistoryWindows:
    """What a strategy sees on a decision date: point-in-time windows.

    Each window is a symbol's rows up to the decision date, capped at the
    strategy's lookback, and **adjusted for corporate actions as of that
    date**: a price is divided by every action already knowable that goes ex
    after it. An action still in the future is exactly what a strategy
    standing here must not see, which is why this cannot be baked into the
    panel.

    Capped rather than complete: handing a 253-day feature 2,869 days of
    history was costing ~90% of the run time for data it never reads.

    ## Why it remembers the previous window

    A backtest rebalances about a hundred times, and consecutive windows
    overlap almost entirely: a 253-day window moved by 21 days shares 232 rows
    with the last one. Those rows have the same adjusted values whenever the
    same actions are knowable, so they are reused and only the new rows are
    adjusted. Building fresh adjusted rows for the whole window on every
    rebalance was the largest single cost of a run.

    The values are identical to adjusting the window from scratch. A row's
    divisor is the product of the knowable actions dated after it, multiplied
    newest first, exactly as the backward walk this replaced multiplied them —
    so the floating-point result is bit-for-bit the same, not merely close.
    """

    def __init__(
        self,
        histories: dict[str, list[PanelRow]],
        days: dict[str, list[date]],
        lookback: int | None,
        events: FactorEvents,
    ) -> None:
        """`days[symbol]` is `[row.day for row in histories[symbol]]`, which
        the engines already hold for marking."""
        self._histories = histories
        self._days = days
        self._lookback = lookback
        self._events = events
        self._event_days = {key: [day for day, _ in series] for key, series in events.items()}
        self._divisors: dict[tuple[str, int], list[float]] = {}
        # Per symbol: the key and action count the last window was adjusted
        # with, where it started, and its adjusted rows.
        self._last: dict[str, tuple[str, int, int, list[PanelRow]]] = {}

    def _divisors_for(self, key: str, known: int) -> list[float]:
        """`out[j]` divides a row dated before action j and on or after j - 1.

        Built newest action first, the order the backward walk multiplied
        them in, so every divisor is the same float the walk produced.
        """
        cached = self._divisors.get((key, known))
        if cached is None:
            series = self._events[key]
            cached = [1.0] * (known + 1)
            cumulative = 1.0
            for j in range(known - 1, -1, -1):
                cumulative *= series[j][1]
                cached[j] = cumulative
            self._divisors[(key, known)] = cached
        return cached

    def at(self, today: date) -> dict[str, list[PanelRow]]:
        """Every symbol's window on `today`, oldest row first.

        The lists are the caller's own: the rows are frozen, and the lists
        are copies, so nothing a strategy does to its view reaches the next.
        """
        out: dict[str, list[PanelRow]] = {}
        lookback = self._lookback
        for symbol, rows in self._histories.items():
            end = bisect_right(self._days[symbol], today)
            if end == 0:
                continue
            start = max(0, end - lookback) if lookback else 0

            # The actions knowable today, for the instrument the window ends
            # on. Sorted by date, so they are a prefix of the series.
            key = rows[end - 1].isin
            dates = self._event_days.get(key)
            known = bisect_right(dates, today) if dates else 0
            if not dates or not known:
                self._last.pop(symbol, None)
                out[symbol] = rows[start:end]
                continue

            divisors = self._divisors_for(key, known)
            previous = self._last.get(symbol)
            if previous is not None and previous[0] == key and previous[1] == known:
                _, _, was_start, was_rows = previous
                overlap_from = max(start, was_start)
                overlap_to = min(end, was_start + len(was_rows))
            else:
                was_start, was_rows = 0, []
                overlap_from = overlap_to = start

            adjusted: list[PanelRow] = []
            if overlap_from < overlap_to:
                for row in rows[start:overlap_from]:
                    adjusted.append(row.adjusted(divisors[bisect_right(dates, row.day, 0, known)]))
                adjusted.extend(was_rows[overlap_from - was_start : overlap_to - was_start])
                tail = rows[overlap_to:end]
            else:
                tail = rows[start:end]
            for row in tail:
                adjusted.append(row.adjusted(divisors[bisect_right(dates, row.day, 0, known)]))

            self._last[symbol] = (key, known, start, adjusted)
            out[symbol] = adjusted[:]
        return out
