"""A delivery spike on an up day, followed the next session (research 112, H-0024).

No academic source: Indian brokers' guidance (research 112) holds that a rise
on unusually high *delivery*, shares taken home rather than day-traded, shows
conviction that carries on. Fixed rule: when a stock's delivery percentage is
at least twice its average over the previous 20 sessions and it closed at least
2% up, buy it the next day at 09:20 if the 09:19 close is above the prior
close; flat at 15:10. Long only.

Delivery is published after the close (knowledge time 20:00, `delivery.jsonl`),
so a session's figure is used only from the next session.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from eulerlab.intraday import cross_section as cs
from eulerlab.intraday import india_papers as ip
from eulerlab.paths import data_path

RUN_ID = "nse_delivery_spike_next_day_long"
DELIVERY = data_path("derived/delivery.jsonl")
AVERAGE_OVER = 20
SPIKE = 2.0
UP = 0.02
SIGNAL_MINUTE = 4
MIN_SLOTS = 10


def context(symbols: Sequence[str], start: date, end: date) -> dict[str, dict[date, float]]:
    """{symbol: {day: delivery %}} for the universe, from `start` to `end`."""
    wanted = set(symbols)
    out: dict[str, dict[date, float]] = defaultdict(dict)
    low, high = start.isoformat(), end.isoformat()
    with DELIVERY.open(encoding="utf-8") as handle:
        for line in handle:
            stamp = line[7:17]
            if not low <= stamp <= high:
                continue
            row = json.loads(line)
            day = date.fromisoformat(row["d"])
            for symbol, values in row["stocks"].items():
                if symbol in wanted and len(values) >= 3 and values[2] is not None:
                    out[symbol][day] = float(values[2])
    return dict(out)


def spikes(percentages: Mapping[date, float]) -> set[date]:
    """Days whose delivery % is at least `SPIKE` times the previous 20 days' mean."""
    ordered = sorted(percentages)
    out = set()
    for index in range(AVERAGE_OVER, len(ordered)):
        before = [percentages[d] for d in ordered[index - AVERAGE_OVER : index]]
        average = statistics.fmean(before)
        if average > 0 and percentages[ordered[index]] >= SPIKE * average:
            out.add(ordered[index])
    return out


@dataclass(frozen=True)
class Mark:
    """A candidate day; `traded` False when the 09:19 close was not above the prior close."""

    traded: bool
    entry_minute: int
    entry: float
    exit_minute: int
    exit: float


def extractor(delivery: Mapping[str, Mapping[date, float]]) -> cs.Extractor:
    def extract(symbol: str, days: Sequence[ip.Day]) -> dict[date, Mark]:
        spiked = spikes(delivery.get(symbol, {}))
        out = {}
        for index in range(2, len(days)):
            yesterday = days[index - 1]
            if yesterday.day not in spiked:
                continue
            before = cs.previous_close(days, index)
            earlier = cs.previous_close(days, index - 1)
            if before is None or earlier is None or before < cs.MIN_PRICE:
                continue
            if before / earlier - 1.0 < UP:
                continue
            day = days[index]
            entry = day.fill_at(cs.ENTRY_OPEN)
            leave = day.fill_at(cs.EXIT)
            if entry is None or leave is None or entry[0] >= cs.EXIT:
                continue
            holds = day.close[SIGNAL_MINUTE] > before
            out[day.day] = Mark(holds, entry[0], entry[1], leave[0], leave[1])
        return out

    return extract


def evaluate(marks: Mapping[str, Mapping[date, Mark]], sessions: Sequence[date]) -> dict[str, Any]:
    by_day: dict[date, list[tuple[str, Mark]]] = defaultdict(list)
    for symbol, days in marks.items():
        for day, found in days.items():
            by_day[day].append((symbol, found))
    trades = []
    for day, candidates in by_day.items():
        each = cs.CAPITAL / max(len(candidates), MIN_SLOTS)
        for symbol, found in candidates:
            if not found.traded:
                continue
            quantity = cs.sized(each, found.entry)
            if quantity:
                trades.append(
                    cs.Trade(
                        symbol,
                        day,
                        1,
                        quantity,
                        found.entry_minute,
                        found.entry,
                        found.exit_minute,
                        found.exit,
                        "time_exit",
                    )
                )
    return cs.report(
        RUN_ID,
        trades,
        sessions,
        params={
            "setup": f"delivery % >= {SPIKE}x its previous {AVERAGE_OVER}-day mean, close >= +{UP:.0%}",
            "confirm": "09:19 close above the prior close",
            "entry": "09:20 open, long",
            "exit": "15:10",
            "sizing": f"capital split equally over the day's candidates, at least {MIN_SLOTS} ways",
            "slippage_bps_per_side": cs.SLIPPAGE_BPS,
        },
    )
