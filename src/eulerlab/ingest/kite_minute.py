"""Backfill 1-minute candles from Kite into the landing zone.

Shaped like the bhavcopy downloader on purpose: an append-only manifest gives
idempotency and resumability, files are written once and never edited, and a
re-run fetches only what is missing. Nothing here is clever; it is the same
discipline applied to a different source.

Two limits, both measured against the live API on 2026-08-18 rather than taken
from the docs, which do not state them:

* **60 days maximum per request.** Asking for more returns
  ``400 interval exceeds max limit: 60 days``.
* **3 requests/second**, per Kite's published rate limits.

Data is stored as Parquet per symbol per chunk. One file per fetch keeps writes
atomic and append-only — appending into an existing Parquet file would mean
rewriting it, which is exactly the mutation the landing zone forbids.

**Survivorship warning.** Kite only knows instruments that exist today, so this
can never reach a company that has since delisted. The universe therefore comes
from our own bhavcopy history (which records what actually traded), and every
symbol Kite cannot resolve is *recorded as a miss* rather than skipped quietly.
Knowing the size of the hole is the whole point.
"""

from __future__ import annotations

import csv
import http.client
import io
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

INSTRUMENTS_URL = "https://api.kite.trade/instruments"
HISTORICAL_URL = "https://api.kite.trade/instruments/historical/{token}/{interval}"

MAX_DAYS_PER_REQUEST = 60
"""Measured, not documented. Kite rejects 61+ with an explicit error."""

CANDLE_FIELDS = ("ts", "open", "high", "low", "close", "volume")


class KiteError(RuntimeError):
    """Kite refused a request."""


@dataclass(frozen=True)
class Chunk:
    symbol: str
    token: int
    start: date
    end: date
    from_time: str = "09:00:00"
    to_time: str = "16:00:00"

    @property
    def key(self) -> str:
        return f"{self.symbol}/{self.start.isoformat()}"

    def relative_path(self) -> Path:
        return Path(self.symbol, f"{self.start.isoformat()}_{self.end.isoformat()}.parquet")


def chunks_for(symbol: str, token: int, start: date, end: date) -> Iterator[Chunk]:
    """Split a date range into request-sized pieces."""
    cursor = start
    while cursor <= end:
        stop = min(cursor + timedelta(days=MAX_DAYS_PER_REQUEST - 1), end)
        yield Chunk(symbol=symbol, token=token, start=cursor, end=stop)
        cursor = stop + timedelta(days=1)


def uncovered_chunks(
    symbol: str,
    token: int,
    start: date,
    end: date,
    held: Sequence[tuple[date, date]],
    *,
    weekend_sessions: frozenset[date] = frozenset(),
) -> Iterator[Chunk]:
    """Chunks for only the sessions in [start, end] no landed range covers.

    A session is a weekday, or a weekend day in `weekend_sessions` (Muhurat and
    other special sessions the bhavcopy proved, ADR-157).

    `chunks_for(start, end)` cut its windows from `end - 1 year`, a start that
    moves every day, so no window ever matched a key already landed: every run
    re-fetched the whole year — `2898 total, 2898 to fetch`, 37.6M bars, on
    2026-10-08 (T-4036). Planning from what is held fetches only the gap,
    normally the one new session per symbol. Other weekends are never fetched,
    and a weekend between two missing days does not split the chunk.
    """
    have: set[date] = set()
    for first, last in held:
        day = max(first, start)
        while day <= min(last, end):
            have.add(day)
            day += timedelta(days=1)

    run_start: date | None = None
    run_end: date | None = None
    day = start
    while day <= end:
        if day.weekday() < 5 or day in weekend_sessions:
            if day in have:
                if run_start is not None and run_end is not None:
                    yield from chunks_for(symbol, token, run_start, run_end)
                run_start = run_end = None
            else:
                run_start = run_start or day
                run_end = day
        day += timedelta(days=1)
    if run_start is not None and run_end is not None:
        yield from chunks_for(symbol, token, run_start, run_end)


SERIES_SUFFIXES = ("-BE", "-BZ", "-SM", "-ST", "-IT")
"""NSE appends the series to the tradingsymbol for anything outside plain EQ.

A stock moved to trade-for-trade surveillance becomes `RELINFRA-BE` in Kite
while the bhavcopy still calls it `RELINFRA`. Matching the bare ticker missed
four symbols and reported them as delisted, which was a false negative that
looked exactly like a real one.
"""


def parse_instruments(payload: bytes, exchange: str = "NSE") -> dict[str, int]:
    """Symbol → instrument_token for one exchange's tradable equities.

    Keys on the *bare* ticker, so a symbol carrying a series suffix in Kite
    still resolves from the plain name the bhavcopy uses. The unsuffixed
    listing wins when both exist, since that is the ordinary-segment line.
    """
    text = io.StringIO(payload.decode("utf-8", errors="replace"))
    mapping: dict[str, int] = {}
    suffixed: dict[str, int] = {}
    for row in csv.DictReader(text):
        if row.get("exchange") != exchange or row.get("instrument_type") != "EQ":
            continue
        symbol, token = row.get("tradingsymbol"), row.get("instrument_token")
        if not symbol or not token or not token.isdigit():
            continue
        for suffix in SERIES_SUFFIXES:
            if symbol.endswith(suffix):
                suffixed.setdefault(symbol[: -len(suffix)], int(token))
                break
        else:
            mapping[symbol] = int(token)
    for bare, token in suffixed.items():
        mapping.setdefault(bare, token)
    return mapping


def read_universe(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def candles_to_table(candles: list[list[object]]) -> pa.Table:
    """Kite returns positional arrays; name them and keep timestamps as strings.

    The exchange timestamp is stored verbatim rather than parsed into a naive
    datetime. Timezone handling belongs in one place later, not scattered
    through an ingest path where a silent UTC assumption would be invisible.
    """
    columns: dict[str, list[object]] = {name: [] for name in CANDLE_FIELDS}
    for row in candles:
        if len(row) < 6:
            continue
        columns["ts"].append(str(row[0]))
        for index, name in enumerate(CANDLE_FIELDS[1:], start=1):
            columns[name].append(row[index])
    return pa.table(
        {
            "ts": pa.array(columns["ts"], pa.string()),
            "open": pa.array(columns["open"], pa.float64()),
            "high": pa.array(columns["high"], pa.float64()),
            "low": pa.array(columns["low"], pa.float64()),
            "close": pa.array(columns["close"], pa.float64()),
            "volume": pa.array(columns["volume"], pa.int64()),
        }
    )


RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

MAX_ATTEMPTS = 3
BACKOFF_BASE_S = 1.0
BACKOFF_CAP_S = 5.0
"""Deliberately impatient.

A failed chunk is not lost: it is absent from the manifest, so the next run
fetches it. That makes waiting expensive and pointless. Measured on 2026-08-18:
307 transient DNS failures at ~14s of backoff each cost roughly 70 minutes and
dropped throughput from 3/sec to 0.1/sec. Fail fast, record it, sweep it up on
the next pass."""


class KiteHistorical:
    """Thin authenticated client with bounded retries.

    Every transport failure is converted to ``KiteError``. That matters more
    than it sounds: a 5-hour backfill died after 41 of 240 symbols because a
    truncated response raised ``http.client.IncompleteRead``, which is neither
    an ``HTTPError`` nor a ``URLError`` and so escaped the caller's handler and
    aborted the whole run. One bad packet must cost one chunk, never the job.
    """

    def __init__(self, api_key: str, access_token: str, *, seed: int = 0) -> None:
        self._auth = f"token {api_key}:{access_token}"
        self._random = random.Random(seed)

    def _once(self, url: str, timeout: float) -> bytes:
        request = urllib.request.Request(
            url, headers={"X-Kite-Version": "3", "Authorization": self._auth}
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data: bytes = response.read()
            return data

    def _get(self, url: str, timeout: float = 60.0) -> bytes:
        last = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return self._once(url, timeout)
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")[:200]
                last = f"http {exc.code}: {body}"
                if exc.code not in RETRYABLE_STATUS:
                    raise KiteError(last) from exc
            except (
                http.client.HTTPException,  # IncompleteRead, BadStatusLine, ...
                urllib.error.URLError,
                TimeoutError,
                OSError,
            ) as exc:
                last = f"{type(exc).__name__}: {exc}"

            if attempt < MAX_ATTEMPTS:
                delay = min(BACKOFF_BASE_S * (2.0 ** (attempt - 1)), BACKOFF_CAP_S)
                time.sleep(delay * (0.5 + self._random.random()))

        msg = f"{last} after {MAX_ATTEMPTS} attempts"
        raise KiteError(msg)

    def instruments(self, exchange: str = "NSE") -> dict[str, int]:
        return parse_instruments(self._get(INSTRUMENTS_URL, timeout=120.0), exchange=exchange)

    def candles(self, chunk: Chunk, interval: str = "minute") -> list[list[object]]:
        query = urllib.parse.urlencode(
            {"from": f"{chunk.start} {chunk.from_time}", "to": f"{chunk.end} {chunk.to_time}"}
        )
        url = f"{HISTORICAL_URL.format(token=chunk.token, interval=interval)}?{query}"
        payload = json.loads(self._get(url))
        data = payload.get("data") or {}
        candles = data.get("candles")
        return candles if isinstance(candles, list) else []


class MinuteStore:
    """Landing zone for minute bars, with its own append-only manifest."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.manifest_path = root / "manifest.jsonl"
        self._done: set[str] | None = None

    def done(self) -> set[str]:
        if self._done is None:
            self._done = set()
            if self.manifest_path.exists():
                for line in self.manifest_path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        key = json.loads(line).get("key")
                        if isinstance(key, str):
                            self._done.add(key)
        return self._done

    def has(self, chunk: Chunk) -> bool:
        return chunk.key in self.done()

    def covered(self) -> dict[str, list[tuple[date, date]]]:
        """Each symbol's landed date ranges, from the manifest."""
        out: dict[str, list[tuple[date, date]]] = {}
        if not self.manifest_path.exists():
            return out
        for line in self.manifest_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            try:
                span = (date.fromisoformat(row["start"]), date.fromisoformat(row["end"]))
            except (KeyError, TypeError, ValueError):
                continue
            out.setdefault(str(row.get("symbol", "")), []).append(span)
        return out

    def write(
        self,
        chunk: Chunk,
        table: pa.Table,
        *,
        source: str | None = None,
        knowledge_time: str | None = None,
    ) -> None:
        """Land one chunk. `source` is set for bars not from Kite (`angel_one`);
        `knowledge_time` only when copying a file landed earlier elsewhere."""
        target = self.root / chunk.relative_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".parquet.part")
        pq.write_table(table, tmp, compression="zstd")
        tmp.replace(target)

        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        row: dict[str, object] = {
            "key": chunk.key,
            "symbol": chunk.symbol,
            "token": chunk.token,
            "start": chunk.start.isoformat(),
            "end": chunk.end.isoformat(),
            "rows": table.num_rows,
            "path": str(chunk.relative_path()),
            "knowledge_time": knowledge_time or datetime.now(UTC).isoformat(),
        }
        if source:
            row["source"] = source
        with self.manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        self.done().add(chunk.key)

    def mark_unresolvable(self, symbol: str, reason: str) -> None:
        """Record a symbol Kite cannot serve, rather than dropping it silently.

        These are the survivorship holes. An unrecorded miss is indistinguishable
        from a symbol we never asked for.
        """
        path = self.root / "unresolved.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"symbol": symbol, "reason": reason}) + "\n")
