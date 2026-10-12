"""US minute candles, read from the cloud, cut to the regular session.

The third source behind `paper_scan.candles_for`, after NSE and crypto. It
exists because ten of the coded signals cite papers tested on US markets —
nine on MNQ (Micro E-Mini Nasdaq 100) futures, one on ~7,000 US equities — and
without it those ten were being swept on `RELIANCE`, which is a different
question than the one their papers answer.

### Why the session is cut here rather than in the signals

Alpaca's minute bars run from roughly 08:00 to 16:53 New York — pre-market and
post-market included. Every opening-range signal in the library defines its
range from the first bars of the session, so handing it the raw file makes an
08:01 pre-market print the "open" and the 09:30 cash open just another bar in
the middle. The papers measure from the cash open, so the filter belongs at the
read, where every signal inherits it, rather than in each signal.

The window is computed in `America/New_York` rather than as a fixed UTC offset:
13:30-20:00 UTC is right from March to November and an hour wrong the rest of
the year, and a backtest that silently drops the first hour of every winter
session would still produce a plausible-looking number.

### On IEX volume

These bars come from the IEX feed, which is a single venue carrying a low
single-digit share of US consolidated volume. Prices track the consolidated
tape closely; **volume does not**. Signals keyed on volume — `volume_spike`,
`volume_dryup`, `volume_climax` — are reading one venue's participation, not
the market's, and their thresholds should be read with that in mind.
"""

from __future__ import annotations

import gzip
import json
import re
from datetime import UTC, date, datetime, time
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from eulerlab.ingest import landing_reader
from eulerlab.intraday.tweezer import Candle

TREE = "us"
SUBTREE = "minute"

LOCAL_ROOT = Path("data/landing/us")
"""Where the tree lives on disk. Only its directory names are read."""

EXCHANGE = ZoneInfo("America/New_York")
SESSION_OPEN = time(9, 30)
SESSION_CLOSE = time(16, 0)
"""Regular US cash hours. Half-days close at 13:00 and are not special-cased:
an early close simply yields fewer bars, which is the truth about that day."""


@lru_cache(maxsize=1)
def symbols() -> tuple[str, ...]:
    """Every landed US symbol, read from **directory names** rather than objects.

    The obvious form — `landing_reader.available(TREE, "minute/*/*.jsonl.gz")` —
    enumerates the whole US minute prefix, which is 71 million bars across tens
    of thousands of objects. It does not return in any time a web request can
    wait for: the instrument search timed out at ninety seconds and the picker
    showed nothing, which is what "US stock search not working" looked like.

    A prune moves the bytes to B2 and leaves the tree behind, so `us/minute/AAPL/`
    exists locally with nothing in it. That is normally a trap — T-3727 is about
    exactly this mistake — and here it is the cheap correct answer, because the
    question is *which symbols exist*, not which bytes are local. `fetch()` still
    reads through `landing_reader` and does not care where the data lives.

    Cached for the process: the universe changes when a batch is landed, not
    between two keystrokes in a search box.
    """
    root = LOCAL_ROOT / SUBTREE
    if root.exists():
        found = {p.name.upper() for p in root.iterdir() if p.is_dir()}
        if found:
            return tuple(sorted(found))

    # Nothing on disk at all — a fresh clone. Fall back to the listing, which is
    # slow but correct, rather than reporting an empty universe.
    return tuple(
        sorted(
            {
                p.split("/")[2]
                for p in landing_reader.available(TREE, f"{SUBTREE}/*/*.jsonl.gz")
                if p.count("/") >= 3
            }
        )
    )


def _months(symbol: str) -> list[str]:
    prefix = f"{TREE}/{SUBTREE}/{symbol}/"
    return sorted(
        p
        for p in landing_reader.available(TREE, f"{SUBTREE}/{symbol}/*.jsonl.gz")
        if p.startswith(prefix)
    )


def _in_range(relative: str, start: date | None, end: date | None) -> bool:
    """Whether a monthly file can hold anything in the window.

    Checked on the filename before the object is fetched, so a 90-day scan does
    not pull two years of archive across the network for one symbol.
    """
    name = relative.rsplit("/", 1)[-1].split(".")[0]
    monthly = re.search(r"(\d{4})-(\d{2})$", name)
    if not monthly:
        # An unparseable name is read rather than skipped: opening a file that
        # might hold the window is cheaper than a silent gap is to notice.
        return True
    try:
        year, month = int(monthly.group(1)), int(monthly.group(2))
        first = date(year, month, 1)
        last = date(year + (month == 12), (month % 12) + 1, 1)
    except ValueError:
        return True

    if start and last < start:
        return False
    return not (end and first > end)


def in_session(stamp: datetime) -> bool:
    """Whether a UTC timestamp falls inside regular New York cash hours."""
    local = stamp.astimezone(EXCHANGE).time()
    return SESSION_OPEN <= local < SESSION_CLOSE


def fetch(symbol: str, *, start: date | None = None, end: date | None = None) -> list[Candle]:
    """Regular-session minute candles for one US symbol."""
    out: list[Candle] = []
    for relative in _months(symbol):
        if not _in_range(relative, start, end):
            continue
        try:
            payload = landing_reader.read(relative)
            text = gzip.decompress(payload).decode("utf-8")
        except (OSError, ValueError, EOFError, FileNotFoundError):
            # A month that cannot be read is skipped whole, never half-parsed:
            # a partial month looks like a real one with a quiet stretch.
            continue

        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                stamp = datetime.fromisoformat(str(row["event_time"]))
            except (ValueError, KeyError):
                continue
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=UTC)
            if not in_session(stamp):
                continue
            day = stamp.astimezone(EXCHANGE).date()
            if (start and day < start) or (end and day > end):
                continue
            try:
                out.append(
                    Candle(
                        ts=stamp,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row.get("volume") or 0.0),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
    out.sort(key=lambda candle: candle.ts)
    return out
