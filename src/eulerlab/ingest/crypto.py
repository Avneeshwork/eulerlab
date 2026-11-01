"""Minute-level crypto history from Binance's public data dumps.

### Why not ccxt

`ccxt` is installed and is the obvious tool, and for this job it is the wrong
one. Five years of one-minute bars is ~2.6 million candles per symbol; REST
`fetchOHLCV` returns at most 1,000 per call, so twenty symbols is roughly
**52,000 paginated requests** — many hours, rate-limited, and every one of them
a chance to fail halfway.

`data.binance.vision` is Binance's own bulk archive, published for exactly this
purpose: one ZIP per symbol per month, ~2 MB for a month of BTCUSDT. The same
five years is **1,200 downloads**. ccxt stays useful for the last few days,
which the monthly archive has not published yet — that gap is named in
`recent_gap()` rather than quietly ignored.

### The universe is measured, not listed

"Top 20 coins" is ranked by **traded volume on Binance**, then filtered to
those that actually have five years of history — probed by asking the archive,
not assumed. Ranking by today's volume alone returns names listed last year
(XPL, PUMP, ACE) which cannot have five years of anything, and the naive list
also quietly includes stablecoins whose USDT pair is not a coin at all.

**This is still survivorship bias and the file says so.** These are the coins
that survived *to today* with volume today; the top twenty of 2021 included
names now delisted. ADR-008 made the same argument for equities and solved it
by ranking as-of a date from our own history — which is possible here too once
enough archive is landed, and is not what this first pass does.

### Crypto has no trading calendar

There are no holidays, no market close, and 1,440 bars in every complete day.
That makes gap detection *stronger* than in equities: a missing minute is
always a missing minute, never a holiday. `verify_month` uses that.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import re
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

ARCHIVE = "https://data.binance.vision/data/spot/monthly/klines"
TICKER_URL = "https://api.binance.com/api/v3/ticker/24hr"

LANDING = Path("data/landing/crypto")
UNIVERSE_FILE = Path("config/universe_crypto.txt")

USER_AGENT = "EulerLab/0.1 (research; contact via repository)"

MINUTES_PER_DAY = 1440

STABLECOINS = frozenset(
    {
        "USDC",
        "FDUSD",
        "TUSD",
        "BUSD",
        "DAI",
        "USDP",
        "USDD",
        "PYUSD",
        "RLUSD",
        "AEUR",
        "USD1",
        "XUSD",
        "EURI",
        "EUR",
        "TRY",
        "BRL",
        "JPY",
        "GBP",
        "ARS",
        "ZAR",
        "MXN",
        "PLN",
        "RON",
        "CZK",
    }
)
"""Excluded because a stablecoin's USDT pair is not a coin, it is an exchange
rate between two claims on the same dollar. Fiat quote currencies are here for
the same reason."""


@dataclass(frozen=True)
class Candle:
    """One minute. Times are UTC — crypto has no local session."""

    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    trades: int

    @property
    def knowledge_time(self) -> datetime:
        """A minute bar is knowable the instant it closes.

        Unlike an equity NAV or a bhavcopy there is no publication lag: the
        exchange is the venue and the tape is the record. So knowledge_time is
        the bar's *close*, which is open + 1 minute — and emphatically not its
        open, which would hand a strategy a bar it is still inside.
        """
        return self.open_time + timedelta(minutes=1)


def _fetch(url: str, *, timeout: int = 120, retries: int = 3) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body: bytes = response.read()
                return body
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise FileNotFoundError(url) from exc
            last = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
        import time

        time.sleep(2**attempt)
    msg = f"{url} failed after {retries} attempts: {last}"
    raise RuntimeError(msg)


def archive_exists(symbol: str, year_month: str) -> bool:
    """Does the archive hold this symbol-month? Asked, never assumed."""
    url = f"{ARCHIVE}/{symbol}/1m/{symbol}-1m-{year_month}.zip"
    try:
        request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
        urllib.request.urlopen(request, timeout=30)
    except Exception:
        return False
    return True


def top_symbols(count: int = 20, *, history_from: str = "") -> list[tuple[str, str, float]]:
    """Rank USDT pairs by traded volume, keeping only those with real history.

    Returns `(base, pair, quote_volume)`. `history_from` is a `YYYY-MM` the
    symbol must already have in the archive — the filter that stops a coin
    listed last year appearing in a five-year study.
    """
    request = urllib.request.Request(TICKER_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=90) as response:
        rows = json.load(response)

    ranked: list[tuple[float, str, str]] = []
    for row in rows:
        pair = str(row.get("symbol", ""))
        if not pair.endswith("USDT"):
            continue
        base = pair[:-4]
        if base in STABLECOINS:
            continue
        # Leveraged tokens are derivatives of a coin, not the coin.
        if base.endswith(("UP", "DOWN", "BULL", "BEAR")):
            continue
        ranked.append((float(row.get("quoteVolume") or 0.0), base, pair))

    ranked.sort(reverse=True)
    kept: list[tuple[str, str, float]] = []
    for volume, base, pair in ranked:
        if history_from and not archive_exists(pair, history_from):
            continue
        kept.append((base, pair, volume))
        if len(kept) >= count:
            break
    return kept


def parse_month(payload: bytes) -> list[Candle]:
    """Read one monthly ZIP into candles.

    Binance ships a header row on newer months and not on older ones, so the
    first field is tested rather than a header being assumed either way — an
    assumption that silently drops one candle a month, or crashes.
    """
    out: list[Candle] = []
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        name = archive.namelist()[0]
        with archive.open(name) as handle:
            text = io.TextIOWrapper(handle, encoding="utf-8")
            for row in csv.reader(text):
                if not row or not row[0].strip().lstrip("-").isdigit():
                    continue  # header line
                stamp = int(row[0])
                # Binance switched open_time from milliseconds to microseconds
                # in 2025. Length is the discriminator; a wrong unit puts the
                # whole month in 1970 or 55,000 AD, and neither is obvious in
                # a row count.
                divisor = 1_000_000 if len(row[0].strip()) > 13 else 1_000
                out.append(
                    Candle(
                        open_time=datetime.fromtimestamp(stamp / divisor, tz=UTC),
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                        volume=float(row[5]),
                        trades=int(row[8]) if len(row) > 8 else 0,
                    )
                )
    return out


def month_path(symbol: str, year_month: str, *, directory: Path = LANDING) -> Path:
    return directory / symbol / f"{symbol}-1m-{year_month}.jsonl.gz"


def land_month(symbol: str, year_month: str, *, directory: Path = LANDING) -> tuple[int, bool]:
    """Fetch and land one symbol-month. Returns (candles, was_downloaded).

    Idempotent: an existing file is never refetched or rewritten, because the
    landing zone is immutable and a re-download that overwrote it could
    silently change history.
    """
    path = month_path(symbol, year_month, directory=directory)
    if path.exists():
        return 0, False

    payload = _fetch(f"{ARCHIVE}/{symbol}/1m/{symbol}-1m-{year_month}.zip")
    candles = parse_month(payload)
    if not candles:
        msg = f"{symbol} {year_month} parsed to zero candles"
        raise ValueError(msg)

    path.parent.mkdir(parents=True, exist_ok=True)
    receipt = datetime.now(UTC).isoformat()

    # Written to a temporary file and renamed, never straight to the final
    # path. A download interrupted mid-write would otherwise leave a TRUNCATED
    # file sitting exactly where a complete one belongs — and `land_month`
    # skips anything that exists, so it would be treated as landed forever
    # while being unreadable. rename() within a directory is atomic on POSIX,
    # so the final path only ever holds a whole file.
    temporary = path.with_suffix(path.suffix + ".partial")
    with gzip.open(temporary, "wt", encoding="utf-8") as handle:
        for candle in candles:
            handle.write(
                json.dumps(
                    {
                        "symbol": symbol,
                        "open": candle.open,
                        "high": candle.high,
                        "low": candle.low,
                        "close": candle.close,
                        "volume": candle.volume,
                        "trades": candle.trades,
                        "event_time": candle.open_time.isoformat(),
                        "knowledge_time": candle.knowledge_time.isoformat(),
                        "receipt_time": receipt,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
    temporary.replace(path)
    return len(candles), True


def is_readable(symbol: str, year_month: str, *, directory: Path = LANDING) -> bool:
    """Can the landed file actually be read end to end?

    `path.exists()` is not the same question. A truncated gzip exists, has a
    plausible size, and raises `EOFError` only when something reads past the
    break — which may be months after the download that produced it.
    """
    path = month_path(symbol, year_month, directory=directory)
    if not path.exists():
        return False
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for _ in handle:
                pass
    except Exception:
        # Deliberately broad. The question is "can this be read", and the
        # answer is no regardless of which layer objects — a truncated stream
        # raises zlib.error, a corrupt header gzip.BadGzipFile, a short read
        # EOFError, and none of those share a base class worth naming here.
        return False
    return True


def repair(symbol: str, year_month: str, *, directory: Path = LANDING) -> bool:
    """Re-fetch a month whose file cannot be read. Returns True if repaired.

    Deletes before re-fetching, because `land_month` skips anything that
    exists — the very behaviour that lets a truncated file persist.
    """
    if is_readable(symbol, year_month, directory=directory):
        return False
    path = month_path(symbol, year_month, directory=directory)
    path.unlink(missing_ok=True)
    path.with_suffix(path.suffix + ".partial").unlink(missing_ok=True)
    land_month(symbol, year_month, directory=directory)
    return True


def months_between(start: date, end: date) -> list[str]:
    """Every `YYYY-MM` from start to end inclusive."""
    out: list[str] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        out.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return out


@dataclass(frozen=True)
class MonthCheck:
    symbol: str
    year_month: str
    candles: int
    expected: int
    missing: int

    @property
    def complete(self) -> bool:
        return self.missing == 0


def verify_month(symbol: str, year_month: str, *, directory: Path = LANDING) -> MonthCheck:
    """Count candles against the 1,440-a-day a complete crypto month must have.

    This check is only possible because crypto trades continuously. In equities
    a missing bar might be a holiday and the calendar has to be consulted;
    here a missing minute is unambiguously a missing minute — usually a Binance
    outage, occasionally a symbol halted.
    """
    path = month_path(symbol, year_month, directory=directory)
    year, month = (int(part) for part in year_month.split("-"))
    next_month = date(year + (month == 12), (month % 12) + 1, 1)
    days = (next_month - date(year, month, 1)).days
    expected = days * MINUTES_PER_DAY

    if not path.exists():
        return MonthCheck(symbol, year_month, 0, expected, expected)

    with gzip.open(path, "rt", encoding="utf-8") as handle:
        count = sum(1 for line in handle if line.strip())
    return MonthCheck(symbol, year_month, count, expected, max(0, expected - count))


def recent_gap() -> tuple[date, date]:
    """The window the monthly archive has not published yet.

    Named rather than hidden. The archive lags by up to a month, so a run today
    lands nothing for the current month — and a strategy reading "everything up
    to today" would silently be reading up to the last month-end. Filling this
    is what ccxt is genuinely for.
    """
    today = datetime.now(UTC).date()
    first_of_month = today.replace(day=1)
    return first_of_month, today


DAILY_ARCHIVE = "https://data.binance.vision/data/spot/daily/klines"
"""Binance's *daily* archive, on the same host and in the same format.

The monthly archive only appears after a month ends, so anything reading "up
to today" was really reading up to the last month-end — on 2026-08-24 the
newest crypto file was `2026-07`, a twenty-four day hole that looked like
staleness and was actually the shape of the source.

The daily files fill exactly that window. Same CSV inside the zip, same parser,
same host — verified 2026-08-24: `BTCUSDT-1m-2026-08-23.zip` is 70,164 bytes
and carries a `.CHECKSUM` alongside it.
"""


def day_path(symbol: str, day: str, *, directory: Path = LANDING) -> Path:
    """Where one symbol-day lands.

    Beside the months, in the same folder, distinguishable by the length of the
    stamp: `BTCUSDT-1m-2026-08.jsonl.gz` against `BTCUSDT-1m-2026-08-23.jsonl.gz`.
    Readers glob the folder, so a day file is picked up without changing them.
    """
    return directory / symbol / f"{symbol}-1m-{day}.jsonl.gz"


def land_day(symbol: str, day: str, *, directory: Path = LANDING) -> tuple[int, bool]:
    """Fetch and land one symbol-day. Returns (candles, was_downloaded).

    Idempotent in the same way `land_month` is: an existing file is never
    refetched. A day Binance has not published yet returns (0, False) rather
    than raising — asking for today before the day is over is an ordinary
    thing to do, not an error.
    """
    path = day_path(symbol, day, directory=directory)
    if path.exists():
        return 0, False

    try:
        payload = _fetch(f"{DAILY_ARCHIVE}/{symbol}/1m/{symbol}-1m-{day}.zip")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return 0, False
        raise

    candles = parse_month(payload)
    if not candles:
        return 0, False

    path.parent.mkdir(parents=True, exist_ok=True)
    receipt = datetime.now(UTC).isoformat()
    temporary = path.with_suffix(path.suffix + ".partial")
    with gzip.open(temporary, "wt", encoding="utf-8") as handle:
        for candle in candles:
            handle.write(
                json.dumps(
                    {
                        "symbol": symbol,
                        "open": candle.open,
                        "high": candle.high,
                        "low": candle.low,
                        "close": candle.close,
                        "volume": candle.volume,
                        "trades": candle.trades,
                        "event_time": candle.open_time.isoformat(),
                        "knowledge_time": candle.knowledge_time.isoformat(),
                        "receipt_time": receipt,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
    temporary.replace(path)
    return len(candles), True


_MONTH_FILE = re.compile(r"-1m-(\d{4}-\d{2})\.jsonl\.gz$")
_DAY_FILE = re.compile(r"-1m-(\d{4}-\d{2})-(\d{2})\.jsonl\.gz$")


def _folder(name: str) -> str:
    return name.rsplit("/", 1)[0] if "/" in name else ""


def without_superseded(names: Iterable[str]) -> list[str]:
    """The files to read: day files whose month file is also landed are dropped.

    Both are Binance's own minute bars for the same days. The daily filler
    lands a month's days while the month is open; the month file lands once
    Binance publishes it, and the day files stay, because landing is immutable.
    Reading both counted every minute of those days twice: daily volume and
    turnover doubled, and the minute reader returned two candles per minute
    (T-4369). The month file wins because it is the one the archive keeps.
    Paths are compared within their folder, so one symbol's month never hides
    another symbol's day.
    """
    names = list(names)
    months = {(_folder(n), m.group(1)) for n in names if (m := _MONTH_FILE.search(n)) is not None}
    kept = []
    for name in names:
        day = _DAY_FILE.search(name)
        if day is not None and (_folder(name), day.group(1)) in months:
            continue
        kept.append(name)
    return kept


def _landed_names(directory: Path) -> set[str]:
    """Basenames already landed for every symbol, on disk and, for the real
    landing zone, in the bucket as well."""
    names = {p.name for p in directory.glob("*/*.jsonl.gz")} if directory.exists() else set()
    if directory == LANDING:
        from eulerlab.ingest import landing_reader

        names |= {r.rsplit("/", 1)[-1] for r in landing_reader.available("crypto", "*/*.jsonl.gz")}
    return names


def fill_window(today: date) -> date:
    """The first day the daily filler asks for when no `--since` is given.

    The first of the previous month, not of this one. Binance publishes a
    month file a few days after the month ends, so on the 1st to about the 3rd
    the previous month is in neither archive unless its days were filled.
    Starting at the first of the current month asked for nothing at all on the
    1st (from 1 Nov to 31 Oct is no days) and left the previous month's last
    days unfilled until its month file appeared: on 2026-11-01 the newest
    crypto bar was two days old (T-4369). Days already landed, or inside a
    landed month file, are not asked for again, so the wider window costs
    nothing once filled.
    """
    first = today.replace(day=1)
    return (first - timedelta(days=1)).replace(day=1)


def fill_days(
    symbols: list[str],
    *,
    since: date | None = None,
    directory: Path = LANDING,
    workers: int = 6,
    landed: Iterable[str] | None = None,
) -> tuple[int, int, list[str]]:
    """Land every published day from `since` to yesterday. Returns
    (days, candles, missing).

    Defaults to `fill_window`: the first of the previous month. Today is
    excluded: Binance publishes a day after it closes, so asking for it is a
    guaranteed 404 and a misleading one — it would land in `missing` as
    though something were wrong.

    A day is skipped when its file is already landed, on disk or in the
    bucket, or when its month file is. `prune-local` deletes local files once
    the bucket holds them, so checking the disk alone downloaded the month's
    days again on every run. `landed` is the set of landed basenames; it is
    read from `directory` (and the bucket, for the real landing zone) when
    not given.
    """
    from concurrent.futures import ThreadPoolExecutor

    now = datetime.now(UTC).date()
    start = since or fill_window(now)
    days = []
    cursor = start
    while cursor < now:
        days.append(cursor.isoformat())
        cursor += timedelta(days=1)

    have = set(landed) if landed is not None else _landed_names(directory)

    def already(symbol: str, day: str) -> bool:
        return f"{symbol}-1m-{day}.jsonl.gz" in have or f"{symbol}-1m-{day[:7]}.jsonl.gz" in have

    jobs = [(symbol, day) for symbol in symbols for day in days if not already(symbol, day)]
    landed_count = candles = 0
    missing: list[str] = []

    def one(job: tuple[str, str]) -> tuple[str, str, int, bool]:
        symbol, day = job
        try:
            count, downloaded = land_day(symbol, day, directory=directory)
        except Exception:
            return symbol, day, 0, False
        return symbol, day, count, downloaded

    with ThreadPoolExecutor(workers) as pool:
        for symbol, day, count, downloaded in pool.map(one, jobs):
            if downloaded:
                landed_count += 1
                candles += count
            elif not day_path(symbol, day, directory=directory).exists():
                missing.append(f"{symbol} {day}")
    return landed_count, candles, missing
