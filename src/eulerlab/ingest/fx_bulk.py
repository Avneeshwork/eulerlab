"""FX minute bars in bulk, from FXCM's public candle server.

### Why this exists alongside `fx.py`

`fx.py` reads Dukascopy's tick feed one hour at a time. It works, and it is
unusable at this scale: measured over a real run, **810 seconds per pair-day**,
which is 245 days for ten pairs over ten years. The per-hour URL is the problem,
not the throttle.

FXCM publishes the same thing already aggregated, one **week** per file:

    https://candledata.fxcorporate.com/m1/{PAIR}/{YEAR}/{WEEK}.csv.gz

Ten pairs over twelve years is about 6,360 requests instead of 624,000 — a
hundredfold reduction that turns months into an afternoon. All ten pairs and
every year from 2015 to 2026 were confirmed present on 2026-08-22.

### It also gives more than the tick feed did

FXCM serves **bid and ask OHLC separately**:

    DateTime,BidOpen,BidHigh,BidLow,BidClose,AskOpen,AskHigh,AskLow,AskClose

Where the Dukascopy path had to build a mid from ticks and average the spread
across them, here both sides are already stated. The stored shape stays the same
`Bar` so one reader serves both sources — mid per field, spread as the mean gap
across the four points — but the numbers behind it are firmer.

### What a missing week means

Week 1 is absent for several years (2019, 2020, 2024, 2025) and week 53 for
most. That is the ISO week falling outside the year's trading, not a gap in the
data, so a 404 here is an ordinary answer and is counted rather than retried.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from eulerlab.ingest.fx import LANDING, USER_AGENT, Bar

FEED = "https://candledata.fxcorporate.com/m1/{pair}/{year}/{week}.csv.gz"
STAMP = "%m/%d/%Y %H:%M:%S.%f"
"""FXCM writes US-order dates with milliseconds. Parsed explicitly rather than
inferred: 03/06/2016 is the 6th of March here and the 3rd of June elsewhere,
and nothing in the file says which."""

FIRST_YEAR = 2015
"""Earliest year confirmed present, checked 2026-08-22."""


def week_url(pair: str, year: int, week: int) -> str:
    return FEED.format(pair=pair, year=year, week=week)


def parse_week(payload: bytes) -> list[Bar]:
    """One weekly CSV into minute bars on the mid.

    Rows that cannot be parsed are dropped rather than defaulted. A bar with a
    guessed price is worse than an absent one: the absence is visible in the
    count, the guess is not.
    """
    text = gzip.decompress(payload).decode("utf-8", errors="replace")
    out: list[Bar] = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            ts = datetime.strptime(row["DateTime"].strip(), STAMP).replace(tzinfo=UTC)
            bid = [float(row[f"Bid{k}"]) for k in ("Open", "High", "Low", "Close")]
            ask = [float(row[f"Ask{k}"]) for k in ("Open", "High", "Low", "Close")]
        except (KeyError, ValueError, TypeError):
            continue
        mid = [(b + a) / 2.0 for b, a in zip(bid, ask, strict=True)]
        out.append(
            Bar(
                ts=ts,
                open=mid[0],
                high=mid[1],
                low=mid[2],
                close=mid[3],
                # FXCM publishes aggregated candles, not ticks, so there is no
                # tick count to report. Zero is honest; inventing one from the
                # bar's range would be a fabricated field.
                ticks=0,
                volume=0.0,
                mean_spread=sum(a - b for b, a in zip(bid, ask, strict=True)) / 4.0,
            )
        )
    return out


def _fetch(url: str, *, timeout: int = 60, retries: int = 4) -> bytes | None:
    """One weekly file, or None when the week does not exist."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return bytes(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if attempt == retries - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries - 1:
                raise
        time.sleep(3 * (attempt + 1))
    return None


def land_week(pair: str, year: int, week: int, *, root: Path = LANDING) -> tuple[int, int, bool]:
    """Fetch one week and write it out as day files.

    Returns (days written, bars written, week already complete). Split by day on
    write so the storage layout matches the Dukascopy path exactly and
    `fx.read_day` serves both without knowing which source produced a file.
    """
    from eulerlab.ingest.fx import day_path

    payload = _fetch(week_url(pair, year, week))
    if payload is None:
        return 0, 0, False

    bars = parse_week(payload)
    if not bars:
        return 0, 0, False

    by_day: dict[object, list[Bar]] = {}
    for bar in bars:
        by_day.setdefault(bar.ts.date(), []).append(bar)

    days = written = 0
    for day, rows in sorted(by_day.items()):
        path = day_path(pair, day, root=root)  # type: ignore[arg-type]
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".partial")
        with gzip.open(tmp, "wt", encoding="utf-8") as handle:
            for bar in sorted(rows, key=lambda b: b.ts):
                handle.write(json.dumps(bar.to_row()) + "\n")
        tmp.replace(path)
        days += 1
        written += len(rows)
    return days, written, days == 0
