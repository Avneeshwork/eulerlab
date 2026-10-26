"""Overnight-to-intraday reversal across F&O stocks (research 112, H-0020).

Branch and Ma (2006; retrospective 2018) report that a stock's overnight return
predicts the following open-to-close return with the opposite sign. Fixed rule:
each session, rank stocks by the move from the prior close to the 09:19 close,
buy the worst decile and short the best at 09:20, flat at 15:10. Equal notional,
half the capital each side.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from eulerlab.intraday import cross_section as cs
from eulerlab.intraday import india_papers as ip

RUN_ID = "nse_overnight_intraday_reversal_decile"
MIN_NAMES = 100
"""Fewer ranked names than this on a day and the day is not traded: a decile
of a thin cross-section is a handful of stocks."""

SIGNAL_MINUTE = 4
"""The 09:19 close, the last price known before the 09:20 entry."""


@dataclass(frozen=True)
class Mark:
    overnight: float
    entry_minute: int
    entry: float
    exit_minute: int
    exit: float


def extract(symbol: str, days: Sequence[ip.Day]) -> dict[date, Mark]:
    out: dict[date, Mark] = {}
    for index, day in enumerate(days):
        before = cs.previous_close(days, index)
        if before is None or before < cs.MIN_PRICE:
            continue
        entry = day.fill_at(cs.ENTRY_OPEN)
        leave = day.fill_at(cs.EXIT)
        if entry is None or leave is None or entry[0] >= cs.EXIT:
            continue
        out[day.day] = Mark(
            day.close[SIGNAL_MINUTE] / before - 1.0, entry[0], entry[1], leave[0], leave[1]
        )
    return out


def evaluate(marks: Mapping[str, Mapping[date, Mark]], sessions: Sequence[date]) -> dict[str, Any]:
    by_day: dict[date, list[tuple[str, Mark]]] = defaultdict(list)
    for symbol, days in marks.items():
        for day, mark in days.items():
            by_day[day].append((symbol, mark))
    trades: list[cs.Trade] = []
    for day, ranked in by_day.items():
        if len(ranked) < MIN_NAMES:
            continue
        ranked.sort(key=lambda item: (item[1].overnight, item[0]))
        decile = len(ranked) // 10
        each = cs.CAPITAL / (2 * decile)
        for direction, chosen in ((1, ranked[:decile]), (-1, ranked[-decile:])):
            for symbol, mark in chosen:
                quantity = cs.sized(each, mark.entry)
                if quantity:
                    trades.append(
                        cs.Trade(
                            symbol,
                            day,
                            direction,
                            quantity,
                            mark.entry_minute,
                            mark.entry,
                            mark.exit_minute,
                            mark.exit,
                            "time_exit",
                        )
                    )
    return cs.report(
        RUN_ID,
        trades,
        sessions,
        params={
            "signal": "prior close to 09:19 close",
            "long": "worst decile",
            "short": "best decile",
            "entry": "09:20 open",
            "exit": "15:10",
            "min_names": MIN_NAMES,
            "sizing": "half the capital per side, equal notional",
            "slippage_bps_per_side": cs.SLIPPAGE_BPS,
        },
    )
