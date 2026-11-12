"""Monthly stock-option expiry: drift toward the most-held strike (research 112, H-0021).

Ni, Pearson and Poteshman (JFE 2005) find optionable stocks close near a strike
on expiry day more often than chance, pulled by hedging of large open interest.
Fixed rule: on each monthly stock-option expiry, take the strike with the most
call-plus-put open interest at the previous day's close. At 13:30, a stock
between 0.25% and 1.5% from that strike is traded toward it; the position is
closed at the next open after the price touches the strike, or at 15:10.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from eulerlab.intraday import cross_section as cs
from eulerlab.intraday import india_papers as ip
from eulerlab.paths import data_path

RUN_ID = "nse_stock_expiry_pin_to_max_oi_strike"
CALENDAR = data_path("derived/nse_calendar.json")
SIGNAL_MINUTE = 255
"""13:30: the entry. The signal is the 13:29 close."""

NEAR = 0.0025
FAR = 0.015
"""Fixed band: nearer than 0.25% leaves less than one round trip's cost to gain;
beyond 1.5% is not 'near' a strike in Ni, Pearson and Poteshman's sense."""

MIN_SLOTS = 10
"""Capital is split across at least this many names, so one qualifying stock
never takes the whole book."""


def expiries(start: date, end: date, trading_days: Sequence[date]) -> list[date]:
    """Monthly stock-option expiries: the last Thursday, or the trading day before it."""
    traded = set(trading_days)
    out = []
    month = date(start.year, start.month, 1)
    while month <= end:
        following = date(month.year + month.month // 12, month.month % 12 + 1, 1)
        day = following - timedelta(days=1)
        while day.weekday() != 3:
            day -= timedelta(days=1)
        while day not in traded and day >= month:
            day -= timedelta(days=1)
        if start <= day <= end and day in traded:
            out.append(day)
        month = following
    return out


def max_oi_strikes(payload: bytes, expiry: date, symbols: set[str]) -> dict[str, float]:
    """{stock: strike with the most call+put open interest} for options on `expiry`."""
    from eulerlab.master.derivatives import ContractType
    from eulerlab.options.chain import quotes_from_fo_bhavcopy

    held: dict[str, dict[Decimal, float]] = defaultdict(lambda: defaultdict(float))
    for quote in quotes_from_fo_bhavcopy(payload):
        if (
            quote.contract_type == ContractType.OPTION
            and quote.expiry == expiry
            and quote.underlying in symbols
            and quote.strike is not None
        ):
            held[quote.underlying][quote.strike] += quote.open_interest
    out = {}
    for symbol, strikes in held.items():
        strike, interest = max(strikes.items(), key=lambda item: (item[1], -item[0]))
        if interest > 0:
            out[symbol] = float(strike)
    return out


def context(symbols: Sequence[str], start: date, end: date) -> dict[date, dict[str, float]]:
    """{expiry: {stock: max-OI strike}} from the bhavcopy of the day before each expiry."""
    from eulerlab.ingest import landing_reader

    trading_days = [date.fromisoformat(d) for d in json.loads(CALENDAR.read_text())["trading_days"]]
    files = {
        path.rsplit("/", 1)[-1][:10]: path
        for path in landing_reader.available("fo", "**/*.zip", stale_ok=True)
    }
    wanted = set(symbols)
    out = {}
    for expiry in expiries(start, end, trading_days):
        before = max(d for d in trading_days if d < expiry)
        path = files.get(before.isoformat())
        if path is None:
            continue
        found = max_oi_strikes(landing_reader.read(path), expiry, wanted)
        if found:
            out[expiry] = found
    return out


@dataclass(frozen=True)
class Mark:
    direction: int
    entry_minute: int
    entry: float
    exit_minute: int
    exit: float
    reason: str


def mark(day: ip.Day, strike: float) -> Mark | None:
    price = day.close[SIGNAL_MINUTE - 1]
    distance = abs(price / strike - 1.0)
    if not NEAR <= distance <= FAR:
        return None
    direction = 1 if price < strike else -1
    entry = day.fill_at(SIGNAL_MINUTE)
    if entry is None or entry[0] >= cs.EXIT:
        return None
    for minute in range(entry[0], cs.EXIT):
        high, low = day.high[minute], day.low[minute]
        if high is None or low is None:
            continue
        if (direction > 0 and high >= strike) or (direction < 0 and low <= strike):
            leave = day.fill_at(minute + 1)
            if leave is not None and leave[0] <= cs.EXIT:
                return Mark(direction, entry[0], entry[1], leave[0], leave[1], "touched_strike")
            break
    leave = day.fill_at(cs.EXIT)
    if leave is None:
        return None
    return Mark(direction, entry[0], entry[1], leave[0], leave[1], "time_exit")


def extractor(pins: Mapping[date, Mapping[str, float]]) -> cs.Extractor:
    def extract(symbol: str, days: Sequence[ip.Day]) -> dict[date, Mark]:
        out = {}
        for day in days:
            strike = pins.get(day.day, {}).get(symbol)
            if strike is None:
                continue
            found = mark(day, strike)
            if found is not None:
                out[day.day] = found
        return out

    return extract


def evaluate(marks: Mapping[str, Mapping[date, Mark]], sessions: Sequence[date]) -> dict[str, Any]:
    by_day: dict[date, list[tuple[str, Mark]]] = defaultdict(list)
    for symbol, days in marks.items():
        for day, found in days.items():
            by_day[day].append((symbol, found))
    trades = []
    for day, chosen in by_day.items():
        each = cs.CAPITAL / max(len(chosen), MIN_SLOTS)
        for symbol, found in chosen:
            quantity = cs.sized(each, found.entry)
            if quantity:
                trades.append(
                    cs.Trade(
                        symbol,
                        day,
                        found.direction,
                        quantity,
                        found.entry_minute,
                        found.entry,
                        found.exit_minute,
                        found.exit,
                        found.reason,
                    )
                )
    return cs.report(
        RUN_ID,
        trades,
        sessions,
        params={
            "expiry": "monthly stock options; last Thursday or the trading day before",
            "strike": "most call+put open interest at the previous close",
            "signal": f"13:29 close {NEAR:.2%} to {FAR:.1%} from that strike",
            "entry": "13:30 open, toward the strike",
            "exit": "next open after touching the strike, else 15:10",
            "sizing": f"capital split equally, at least {MIN_SLOTS} ways",
            "slippage_bps_per_side": cs.SLIPPAGE_BPS,
        },
    )
