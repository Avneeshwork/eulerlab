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
import io
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
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


def parse_instruments(payload: bytes, exchange: str = "NSE") -> dict[str, int]:
    """Symbol → instrument_token for one exchange's tradable equities."""
    text = io.StringIO(payload.decode("utf-8", errors="replace"))
    mapping: dict[str, int] = {}
    for row in csv.DictReader(text):
        if row.get("exchange") != exchange or row.get("instrument_type") != "EQ":
            continue
        symbol, token = row.get("tradingsymbol"), row.get("instrument_token")
        if symbol and token and token.isdigit():
            mapping[symbol] = int(token)
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


class KiteHistorical:
    """Thin authenticated client. One request per call, no retries here."""

    def __init__(self, api_key: str, access_token: str) -> None:
        self._auth = f"token {api_key}:{access_token}"

    def _get(self, url: str, timeout: float = 60.0) -> bytes:
        request = urllib.request.Request(
            url, headers={"X-Kite-Version": "3", "Authorization": self._auth}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data: bytes = response.read()
                return data
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:200]
            msg = f"http {exc.code}: {body}"
            raise KiteError(msg) from exc

    def instruments(self) -> dict[str, int]:
        return parse_instruments(self._get(INSTRUMENTS_URL, timeout=120.0))

    def candles(self, chunk: Chunk, interval: str = "minute") -> list[list[object]]:
        query = urllib.parse.urlencode(
            {"from": f"{chunk.start} 09:00:00", "to": f"{chunk.end} 16:00:00"}
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

    def write(self, chunk: Chunk, table: pa.Table) -> None:
        target = self.root / chunk.relative_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".parquet.part")
        pq.write_table(table, tmp, compression="zstd")
        tmp.replace(target)

        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with self.manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "key": chunk.key,
                        "symbol": chunk.symbol,
                        "token": chunk.token,
                        "start": chunk.start.isoformat(),
                        "end": chunk.end.isoformat(),
                        "rows": table.num_rows,
                        "path": str(chunk.relative_path()),
                        "knowledge_time": datetime.now(UTC).isoformat(),
                    },
                    sort_keys=True,
                )
                + "\n"
            )
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
