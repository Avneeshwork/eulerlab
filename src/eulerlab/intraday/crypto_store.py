"""Crypto minute candles, read from the cloud.

The NSE equivalent (`intraday/store`) predates `prune-local` and caches
Parquet chunks itself. This one goes through `landing_reader`, so it does not
care whether the archive is on this disk: the 1,200 monthly files live in B2
and are fetched and cached on first read.

That is the point rather than a convenience. `data/landing/crypto` is 0 bytes
on this machine — pruned once the upload was verified — and without this a
crypto backtest would report "no data" for 52 million candles sitting safely in
the bucket.
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, date, datetime

from eulerlab.ingest import landing_reader
from eulerlab.intraday.tweezer import Candle

TREE = "crypto"


def symbols() -> list[str]:
    """Every landed pair, from disk and the bucket together."""
    found = {p.split("/")[1] for p in landing_reader.available(TREE, "*/*.jsonl.gz")}
    return sorted(found)


def _months(symbol: str) -> list[str]:
    prefix = f"{TREE}/{symbol}/"
    return sorted(
        p for p in landing_reader.available(TREE, f"{symbol}/*.jsonl.gz") if p.startswith(prefix)
    )


def _in_range(relative: str, start: date | None, end: date | None) -> bool:
    """Whether a monthly file can hold anything in the window.

    Filename carries the month, e.g. `BTCUSDT-1m-2021-08.jsonl.gz`. Checking it
    before downloading is what keeps a 90-day scan from pulling five years of
    archive across the network.
    """
    stem = relative.rsplit("-", 2)
    if len(stem) < 3:
        return True
    try:
        year, month = int(stem[-2]), int(stem[-1].split(".")[0])
    except ValueError:
        return True
    first = date(year, month, 1)
    last = date(year + (month == 12), (month % 12) + 1, 1)
    if start and last < start:
        return False
    return not (end and first > end)


def fetch(symbol: str, *, start: date | None = None, end: date | None = None) -> list[Candle]:
    """Minute candles for one pair, from B2 when they are not local."""
    out: list[Candle] = []
    for relative in _months(symbol):
        if not _in_range(relative, start, end):
            continue
        try:
            payload = landing_reader.read(relative)
            text = gzip.decompress(payload).decode("utf-8")
        except (OSError, ValueError, EOFError, FileNotFoundError):
            # A month that cannot be read is skipped, never half-parsed: a
            # partial month looks like a real one with a quiet stretch.
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
            day = stamp.date()
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
