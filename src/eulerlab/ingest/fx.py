"""FX minute bars, resampled from Dukascopy's public tick feed.

### Why Dukascopy and not HistData

HistData is the better-known free source and its download is a form POST to
`get.php`. Tested on 2026-08-22: the POST returns HTTP 200 with **zero bytes**
whether or not a session cookie is carried, so it is not scriptable without
driving a browser. Dukascopy's feed is a plain GET at a predictable URL with no
token, no session and no registration, and it answered for both 2016 and 2024
on the first try.

### The wire format, because nothing about it is self-describing

    https://datafeed.dukascopy.com/datafeed/{PAIR}/{YYYY}/{MM}/{DD}/{HH}h_ticks.bi5

**The month is zero-indexed.** January is `00` and December is `11`. Nothing in
the URL says so, and off-by-one here silently fetches a different month's data
rather than failing.

Each file is LZMA-compressed, and decompresses to a flat array of 20-byte
records, big-endian:

    int32   milliseconds since the top of the hour
    int32   ask, in points
    int32   bid, in points
    float32 ask volume
    float32 bid volume

Prices are integers in the instrument's points, so they need scaling: 1e5 for
most pairs, 1e3 for anything quoted in JPY. Getting that wrong produces prices
off by a factor of a hundred, which is obvious for EURUSD and *not* obvious for
USDJPY, so the scale is per-pair and explicit rather than inferred.

### What is stored

Minute bars, not ticks. A tick archive of ten years across ten pairs is
hundreds of gigabytes and no strategy here reads a tick — the intraday engine
takes `Candle`. Resampling at ingest is the same decision `alt_panel` makes for
crypto: the daily bar is what a daily strategy is entitled to see, and the
minute bar is what an intraday one is.

Mid price is used for OHLC, because a bar built from bids and a bar built from
asks are different series and mixing them silently would produce a spread-wide
error that never surfaces. The spread is kept separately, since it is the whole
cost model for FX.
"""

from __future__ import annotations

import gzip
import json
import lzma
import struct
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

LANDING = Path("data/landing/fx")
FEED = "https://datafeed.dukascopy.com/datafeed"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"

TICK_STRUCT = struct.Struct(">3i2f")
"""One tick: ms-since-hour, ask, bid, ask volume, bid volume. Big-endian."""

PAIRS: tuple[str, ...] = (
    "EURUSD",
    "USDJPY",
    "GBPUSD",
    "AUDUSD",
    "USDCAD",
    "USDCHF",
    "NZDUSD",
    "EURJPY",
    "GBPJPY",
    "EURGBP",
)
"""The ten most traded pairs, in BIS turnover order.

Six of them are USD legs because that is what the market is: the dollar is on
one side of roughly 88% of all FX trades. A "top ten by liquidity" that spread
itself evenly across currencies would be a different and less useful universe.
"""


def point_scale(pair: str) -> float:
    """Points to price. JPY crosses quote to three decimals, the rest to five.

    Explicit per pair rather than inferred from the numbers, because a wrong
    scale on EURUSD is obvious at a glance and a wrong scale on USDJPY is not.
    """
    return 1e3 if pair.endswith("JPY") else 1e5


@dataclass(frozen=True)
class Bar:
    """One minute, with both sides of the book kept.

    **Bid and ask are stored, not a mid and a spread.** Storing derived values
    and discarding the inputs meant a bug in the derivation could only be fixed
    by re-fetching ten years of data — which is exactly what happened: the
    spread was averaged across open, high, low and close, and `AskHigh -
    BidHigh` is not a spread at all. The highest ask and the highest bid occur
    at *different instants* inside the minute, so their difference is a gap
    between two unrelated moments. It went negative on real data, which is
    impossible for a real quote and was the clue.

    Only open and close pair bid against ask at the same instant, so only they
    can measure a spread. Keeping both sides means the next definition can be
    derived without another download.
    """

    ts: datetime
    bid_open: float
    bid_high: float
    bid_low: float
    bid_close: float
    ask_open: float
    ask_high: float
    ask_low: float
    ask_close: float
    ticks: int = 0
    volume: float = 0.0

    # --- the mid, derived per field ---------------------------------------
    # The high of the mid is the mid of the highs. Applying one mid to every
    # field would narrow every bar.

    @property
    def open(self) -> float:
        return (self.bid_open + self.ask_open) / 2.0

    @property
    def high(self) -> float:
        return (self.bid_high + self.ask_high) / 2.0

    @property
    def low(self) -> float:
        return (self.bid_low + self.ask_low) / 2.0

    @property
    def close(self) -> float:
        return (self.bid_close + self.ask_close) / 2.0

    @property
    def mean_spread(self) -> float:
        """Cost of crossing, from the two points where both sides are
        contemporaneous. Never from the high or the low."""
        return ((self.ask_open - self.bid_open) + (self.ask_close - self.bid_close)) / 2.0

    def to_row(self) -> dict[str, object]:
        return {
            "ts": self.ts.isoformat(),
            "bo": round(self.bid_open, 6),
            "bh": round(self.bid_high, 6),
            "bl": round(self.bid_low, 6),
            "bc": round(self.bid_close, 6),
            "ao": round(self.ask_open, 6),
            "ah": round(self.ask_high, 6),
            "al": round(self.ask_low, 6),
            "ac": round(self.ask_close, 6),
            "ticks": self.ticks,
            "volume": round(self.volume, 4),
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Bar:
        return cls(
            ts=datetime.fromisoformat(str(row["ts"])),
            bid_open=float(row["bo"]),
            bid_high=float(row["bh"]),
            bid_low=float(row["bl"]),
            bid_close=float(row["bc"]),
            ask_open=float(row["ao"]),
            ask_high=float(row["ah"]),
            ask_low=float(row["al"]),
            ask_close=float(row["ac"]),
            ticks=int(row.get("ticks", 0)),
            volume=float(row.get("volume", 0.0)),
        )


def hour_url(pair: str, when: datetime) -> str:
    """The feed URL for one pair-hour. Month is zero-indexed; see the module docstring."""
    return (
        f"{FEED}/{pair}/{when.year:04d}/{when.month - 1:02d}/"
        f"{when.day:02d}/{when.hour:02d}h_ticks.bi5"
    )


def decode_hour(
    payload: bytes, pair: str, hour: datetime
) -> list[tuple[datetime, float, float, float]]:
    """Ticks as (timestamp, bid, ask, volume).

    An empty payload is a real answer, not a failure: the feed returns zero
    bytes for hours the market was closed, and every weekend is one.
    """
    if not payload:
        return []
    try:
        raw = lzma.LZMADecompressor().decompress(payload)
    except lzma.LZMAError:
        return []

    scale = point_scale(pair)
    out: list[tuple[datetime, float, float, float]] = []
    for offset in range(0, len(raw) - TICK_STRUCT.size + 1, TICK_STRUCT.size):
        ms, ask, bid, ask_volume, bid_volume = TICK_STRUCT.unpack_from(raw, offset)
        out.append(
            (
                hour + timedelta(milliseconds=ms),
                bid / scale,
                ask / scale,
                float(ask_volume + bid_volume),
            )
        )
    return out


def to_minutes(ticks: list[tuple[datetime, float, float, float]]) -> list[Bar]:
    """Group ticks into minute bars, keeping bid and ask separate.

    Both sides are carried through rather than collapsed to a mid here, for
    the same reason `Bar` stores them: a derivation kept without its inputs
    cannot be corrected without re-fetching.
    """
    buckets: dict[datetime, list[tuple[float, float, float]]] = {}
    for ts, bid, ask, volume in ticks:
        minute = ts.replace(second=0, microsecond=0)
        buckets.setdefault(minute, []).append((bid, ask, volume))

    bars: list[Bar] = []
    for minute in sorted(buckets):
        rows = buckets[minute]
        bids = [r[0] for r in rows]
        asks = [r[1] for r in rows]
        bars.append(
            Bar(
                ts=minute,
                bid_open=bids[0],
                bid_high=max(bids),
                bid_low=min(bids),
                bid_close=bids[-1],
                ask_open=asks[0],
                ask_high=max(asks),
                ask_low=min(asks),
                ask_close=asks[-1],
                ticks=len(rows),
                volume=sum(r[2] for r in rows),
            )
        )
    return bars


def day_path(pair: str, day: date, *, root: Path = LANDING) -> Path:
    return root / pair / f"{day:%Y-%m}" / f"{day:%Y-%m-%d}.jsonl.gz"


def _fetch(url: str, *, timeout: int = 30, retries: int = 5) -> bytes | None:
    """One hour of ticks, or None if the feed does not have it.

    404 is a real answer — the feed has no file for an hour the market was shut
    — and is distinguished from a transport failure, which is retried. Treating
    the two alike would either retry every weekend hour three times or give up
    on a blip.
    """
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": "https://www.dukascopy.com/swiss/english/marketwatch/historical/",
            "Accept": "*/*",
        },
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
                return bytes(body)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            # 503 is the feed asking us to slow down, not a broken URL. It
            # arrives after a couple of dozen rapid requests and clears on its
            # own, so it is backed off hard rather than retried tightly.
            if attempt == retries - 1:
                raise
            if exc.code == 503:
                time.sleep(5 * (attempt + 1))
                continue
        except (urllib.error.URLError, TimeoutError):
            # Includes DNS failure, which under load is transient and local
            # rather than anything the feed did. Backed off longer than an
            # HTTP error because the resolver needs time, not a retry.
            if attempt == retries - 1:
                raise
            time.sleep(3 * (attempt + 1))
            continue
        time.sleep(2**attempt)
    return None


def hours_of(day: date) -> Iterator[datetime]:
    for hour in range(24):
        yield datetime(day.year, day.month, day.day, hour, tzinfo=UTC)


HOUR_WORKERS = 6
"""How many of a day's 24 hours are fetched at once.

Measured on 2026-08-22: the feed serves a single connection at roughly **10
seconds per request** - with zero 503s, so it is a throttle rather than a
defence. Sixteen concurrent connections returned in 4.7 seconds total, 0.29s
effective. The limit is therefore per-connection, not per-IP.

That distinction decides whether this is possible at all: ten pairs over ten
years is about 624,000 hourly requests, which is 72 days serially and under two
days concurrently. Six rather than the sixteen that benchmarked fastest. Twelve produced a steady
stream of `nodename nor servname provided` - DNS failures, not HTTP ones, from
too many simultaneous lookups against the local resolver. Those days were
skipped rather than landed, so the extra concurrency was buying nothing and
costing coverage. Six holds a pair-day near half a minute and lands it.
"""


def land_day(pair: str, day: date, *, root: Path = LANDING, pace: float = 0.15) -> tuple[int, bool]:
    """Fetch, resample and store one pair-day. Returns (bars, already_had_it).

    Idempotent and resumable: a day already on disk is skipped without a single
    request, which is what makes a ten-year backfill restartable. Written to
    `.partial` and renamed, so an interrupted run leaves no half file that a
    later run would mistake for complete — the same rule the crypto archive
    learned the hard way.
    """
    path = day_path(pair, day, root=root)
    if path.exists():
        return 0, True

    def one(hour: datetime) -> list[tuple[datetime, float, float, float]]:
        if pace:
            time.sleep(pace)
        payload = _fetch(hour_url(pair, hour))
        return decode_hour(payload, pair, hour) if payload else []

    hours = list(hours_of(day))
    with ThreadPoolExecutor(max_workers=HOUR_WORKERS) as pool:
        fetched = list(pool.map(one, hours))

    ticks: list[tuple[datetime, float, float, float]] = []
    for chunk in fetched:
        ticks.extend(chunk)
    ticks.sort(key=lambda row: row[0])

    bars = to_minutes(ticks)
    if not bars:
        # A weekend or a holiday. Nothing is written: an empty file would be
        # indistinguishable from a landed day with no trading, and the next run
        # would skip it forever.
        return 0, False

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".partial")
    with gzip.open(tmp, "wt", encoding="utf-8") as handle:
        for bar in bars:
            handle.write(json.dumps(bar.to_row()) + "\n")
    tmp.replace(path)
    return len(bars), False


def read_day(pair: str, day: date, *, root: Path = LANDING) -> list[Bar]:
    """Bars back off disk, or an empty list if the day was never landed."""
    path = day_path(pair, day, root=root)
    if not path.exists():
        return []
    out: list[Bar] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                out.append(Bar.from_row(json.loads(line)))
            except (KeyError, ValueError, TypeError):
                # A row written under the old mid-only format. Skipped rather
                # than half-read: a Bar with no bid or ask cannot answer what
                # the spread was, and guessing zero would understate every cost.
                continue
    return out


def landed_days(pair: str, *, root: Path = LANDING) -> int:
    return len(list((root / pair).glob("*/*.jsonl.gz"))) if (root / pair).exists() else 0
