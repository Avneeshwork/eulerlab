"""One pass over every F&O stock's minute history, for cross-sectional screens.

A full session is 375 minutes of six series; 400 stocks of them do not fit in
memory (`india_papers` notes a hundred do not). So each symbol is loaded,
reduced by every screen's `extract` to the few numbers it needs per day, and
dropped before the next is held. Loading is downloads from the bucket (about
15 s a symbol, 17 of 17.3 s of it waiting on the network, measured
2026-10-16), so symbols are fetched on a few threads at once.

Also here: the trade record, its costs, and the report every screen in
research 112 writes, so the five are measured exactly alike.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from functools import cached_property
from pathlib import Path
from typing import Any

from eulerlab.intraday import india_papers as ip
from eulerlab.intraday import research_screen as rs
from eulerlab.intraday import screen_common as sc

RESEARCH_START, DATA_END = rs.RESEARCH_START, rs.DATA_END
"""The research window's end, the constitution's `backtest_end` (ADR-184).
Minute files that cross it are never opened (`research_screen`), and the 2026
forward test is refused outright (`constitution.sealed`)."""

CAPITAL = 1_000_000.0
SLIPPAGE_BPS = 2.0
"""Assumed per side, on top of NSE intraday charges, as in research 076-111."""

ENTRY_OPEN = 5
"""09:20. The 09:15 print sits far from the next minute's trade (research 075),
so nothing is decided on it or filled at it."""

EXIT = ip.STOCK_EXIT
"""15:10, before the broker squares intraday stock positions off."""

MIN_PRICE = ip.MIN_PRICE
LOAD_WORKERS = 8
TRADE_LOG_LIMIT = 2_000
"""Trades kept in the output file; every trade counts in the figures."""

Extractor = Callable[[str, Sequence[ip.Day]], Any]


def universe() -> list[str]:
    """Every stock with Kite minute files; the exchange-traded funds are left out."""
    from eulerlab.ingest import landing_reader

    found = landing_reader.available("kite_minute", "**/*.parquet", stale_ok=True)
    names = {path.split("/")[1] for path in found if path.count("/") >= 2}
    return sorted(name for name in names if not name.endswith("BEES"))


def scan(
    symbols: Sequence[str],
    extractors: Mapping[str, Extractor],
    *,
    root: Path | None = None,
    cutoff: date = DATA_END,
    workers: int = LOAD_WORKERS,
    progress: Callable[[int, int, str], None] | None = None,
    since: date | None = None,
    history: bool = False,
) -> tuple[dict[str, dict[str, Any]], list[date]]:
    """({screen: {symbol: extract(...)}}, every session any symbol traded), oldest first.

    Extraction runs on the calling thread as each symbol arrives, so at most
    `workers` symbols' sessions are held at once.
    """
    out: dict[str, dict[str, Any]] = {name: {} for name in extractors}
    sessions: set[date] = set()

    def load(symbol: str) -> tuple[str, list[ip.Day]]:
        # Not cached: every stock's history would not fit on this disk (it
        # filled it on 2026-10-16). A file already local is still read from disk.
        # `since`: a paper book's holdout end, so no holdout file is opened.
        return symbol, rs.load_days(
            symbol, root=root, cutoff=cutoff, cache=False, since=since, history=history
        )

    with ThreadPoolExecutor(workers) as pool:
        futures = [pool.submit(load, symbol) for symbol in symbols]
        for done, future in enumerate(as_completed(futures), start=1):
            symbol, days = future.result()
            sessions.update(day.day for day in days)
            for name, extract in extractors.items():
                out[name][symbol] = extract(symbol, days)
            if progress is not None:
                progress(done, len(symbols), symbol)
    return out, sorted(sessions)


def previous_close(days: Sequence[ip.Day], index: int) -> float | None:
    """The prior session's last traded close, if that session is the one just before."""
    if index == 0:
        return None
    before = days[index - 1]
    if (days[index].day - before.day).days > 7:
        return None
    return before.close[before.last]


# --- trades and the report -----------------------------------------------------------


@dataclass(frozen=True)
class Trade:
    symbol: str
    day: date
    direction: int
    """+1 long, -1 short."""
    quantity: int
    entry_minute: int
    entry: float
    exit_minute: int
    exit: float
    reason: str

    @property
    def gross(self) -> float:
        return self.direction * (self.exit - self.entry) * self.quantity

    @cached_property
    def costs(self) -> float:
        """Read five or more times a trade by the screen and its checks; computed once (#167)."""
        return sc.round_trip_cost(
            self.entry,
            self.exit,
            self.quantity,
            self.day,
            self.direction,
            slippage_bps=SLIPPAGE_BPS,
        )

    @property
    def notional(self) -> float:
        return self.entry * self.quantity


def sized(notional: float, price: float) -> int:
    """Whole shares worth `notional` at `price`; 0 when not even one share fits."""
    return int(notional / price) if price > 0 else 0


def report(
    run_id: str,
    trades: Iterable[Trade],
    sessions: Sequence[date],
    *,
    params: Mapping[str, Any],
    capital: float = CAPITAL,
) -> dict[str, Any]:
    """The run every research-112 screen writes: gross and net, by year, per trade.

    Every session in the window counts, so a day the rule did not trade is a
    zero return, not a missing one.
    """
    book = sorted(trades, key=lambda t: (t.day, t.entry_minute, t.symbol))
    gross: dict[date, float] = defaultdict(float)
    net: dict[date, float] = defaultdict(float)
    for trade in book:
        gross[trade.day] += trade.gross / capital
        net[trade.day] += (trade.gross - trade.costs) / capital
    years: dict[int, list[float]] = defaultdict(list)
    for day in sessions:
        years[day.year].append(net[day])
    gross_bps = [t.gross / t.notional * 10_000 for t in book if t.notional]
    net_bps = [(t.gross - t.costs) / t.notional * 10_000 for t in book if t.notional]
    return {
        "id": run_id,
        "params": dict(params),
        "window": [sessions[0].isoformat(), sessions[-1].isoformat()] if sessions else [],
        "capital_rupees": capital,
        "sessions": len(sessions),
        "active_sessions": len({t.day for t in book}),
        "trades": len(book),
        "fills": 2 * len(book),
        "gross": sc.daily_stats([gross[day] for day in sessions]),
        "net": sc.daily_stats([net[day] for day in sessions]),
        "net_by_year": {
            str(year): sc.daily_stats(values) for year, values in sorted(years.items())
        },
        "per_trade_bps": {
            "gross_mean": round(statistics.fmean(gross_bps), 2) if gross_bps else None,
            "net_mean": round(statistics.fmean(net_bps), 2) if net_bps else None,
            "net_win_rate": round(sum(1 for x in net_bps if x > 0) / len(net_bps), 4)
            if net_bps
            else None,
        },
        "estimated_costs_rupees": round(sum(t.costs for t in book), 2),
        "daily": [[day.isoformat(), round(net[day], 8)] for day in sessions],
        "trade_log": [
            {
                "symbol": t.symbol,
                "day": t.day.isoformat(),
                "side": "long" if t.direction > 0 else "short",
                "quantity": t.quantity,
                "entry_minute": t.entry_minute,
                "entry": round(t.entry, 4),
                "exit_minute": t.exit_minute,
                "exit": round(t.exit, 4),
                "reason": t.reason,
                "gross_pnl": round(t.gross, 2),
                "costs": round(t.costs, 2),
            }
            for t in book[:TRADE_LOG_LIMIT]
        ],
    }
