"""Choose which instruments to record or backfill, from our own data.

**Why not a published index list.** "Nifty 250" would ordinarily mean fetching a
constituent list from NSE. Today's list applied to 2021 data is survivorship
bias in its purest form: every name that fell out of the index because it did
badly is silently absent, and the backtest inherits a universe selected on
hindsight.

Instead the universe is derived from the bhavcopy history we already hold, which
records what actually traded on each day, delisted names included. Ranking by
median traded value over a trailing window gives a universe that is
reproducible, point-in-time, and honest about what was liquid *then* rather than
what is liquid now.

The rank date is therefore an input, never "today".
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from pathlib import Path
from statistics import median

from eulerlab.ingest.landing import Landing

# UDiFF (2024+) and legacy (pre-2024) name these differently.
SYMBOL_FIELDS = ("TckrSymb", "SYMBOL")
SERIES_FIELDS = ("SctySrs", "SERIES")
VALUE_FIELDS = ("TtlTrfVal", "TOTTRDVAL")

EQUITY_SERIES = frozenset({"EQ", "BE"})

MAX_GAP_DAYS = 10
"""Largest acceptable jump between consecutive files in a lookback window.

Generous enough for Diwali or a long weekend, tight enough to catch a backfill
that has not reached the requested period yet.
"""


class DiscontiguousWindow(ValueError):
    """The lookback window has a hole in it.

    This is not pedantry. Ranking "the 60 most recent files" while a backfill is
    still running silently mixes five days of 2026 with fifty-five days of 2023
    and produces a ranking that looks entirely plausible — until you notice a
    company in it that merged out of existence three years ago. A universe is
    only point-in-time if the window it was computed over is actually contiguous.
    """


@dataclass(frozen=True)
class Ranked:
    symbol: str
    median_turnover: float
    days_seen: int


def _first(row: dict[str, str], names: tuple[str, ...]) -> str | None:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def read_turnover(payload: bytes) -> dict[str, float]:
    """Symbol → traded value for one day's cash-market bhavcopy.

    Handles both archive formats, and keeps only real equity series: including
    every instrument would let ETFs and debt series crowd out actual stocks.
    """
    out: dict[str, float] = {}
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if not names:
            return out
        with archive.open(names[0]) as handle:
            text = io.TextIOWrapper(handle, encoding="utf-8", errors="replace")
            for raw in csv.DictReader(text):
                row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
                symbol = _first(row, SYMBOL_FIELDS)
                series = _first(row, SERIES_FIELDS)
                value = _first(row, VALUE_FIELDS)
                if not symbol or series not in EQUITY_SERIES or not value:
                    continue
                try:
                    out[symbol] = float(value)
                except ValueError:
                    continue
    return out


def rank_by_liquidity(
    landing: Landing,
    *,
    as_of: date,
    lookback_days: int = 60,
    min_days: int = 20,
) -> list[Ranked]:
    """Rank equities by median daily traded value over the window ending `as_of`.

    Median rather than mean: one block deal should not promote an otherwise
    illiquid name into the tradable universe. `min_days` drops anything that
    barely traded in the window, which is the same judgement expressed as a
    filter rather than a ranking.
    """
    entries = [
        entry
        for entry in landing.entries().values()
        if entry.segment == "cm" and date.fromisoformat(entry.trade_date) <= as_of
    ]
    entries.sort(key=lambda entry: entry.trade_date, reverse=True)
    window = entries[:lookback_days]

    if not window:
        msg = f"no cash-market files at or before {as_of}"
        raise DiscontiguousWindow(msg)

    dates = [date.fromisoformat(entry.trade_date) for entry in window]
    for later, earlier in pairwise(dates):
        if (later - earlier).days > MAX_GAP_DAYS:
            msg = (
                f"the lookback window jumps from {earlier} to {later}, a gap of "
                f"{(later - earlier).days} days. Ranking across a hole mixes "
                f"different eras and produces a universe that is wrong in a way "
                f"that looks right. Finish the backfill, or pass an as_of inside "
                f"a contiguous stretch."
            )
            raise DiscontiguousWindow(msg)

    turnovers: dict[str, list[float]] = defaultdict(list)
    absent = 0
    for entry in window:
        path = landing.root / entry.path
        if not path.exists():
            # Pruned to B2 (ADR-010). Counted, then reported below - silently
            # ranking on whatever happens to remain on disk would produce a
            # confident, wrong universe, which is worse than an error.
            absent += 1
            continue
        for symbol, value in read_turnover(path.read_bytes()).items():
            turnovers[symbol].append(value)

    if absent:
        msg = (
            f"{absent} of {len(window)} files in the window are not on local disk. "
            f"They were pruned to B2 after upload (ADR-010). Ranking on the "
            f"remainder would give a confident but wrong universe. Restore them "
            f"first, or rank as_of a date whose files are still local."
        )
        raise DiscontiguousWindow(msg)

    ranked = [
        Ranked(symbol=symbol, median_turnover=median(values), days_seen=len(values))
        for symbol, values in turnovers.items()
        if len(values) >= min_days
    ]
    ranked.sort(key=lambda r: r.median_turnover, reverse=True)
    return ranked


def top_n(landing: Landing, *, n: int, as_of: date, lookback_days: int = 60) -> list[str]:
    return [
        r.symbol for r in rank_by_liquidity(landing, as_of=as_of, lookback_days=lookback_days)[:n]
    ]


def write_universe(path: Path, symbols: list[str], *, as_of: date, note: str) -> None:
    """Persist a universe with the date it was computed as of.

    A universe file without its as-of date is a survivorship bias waiting to be
    reused on the wrong period.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# {note}",
        f"# as_of: {as_of.isoformat()}",
        f"# count: {len(symbols)}",
        "# Derived from bhavcopy turnover, not a published index list.",
        *symbols,
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
