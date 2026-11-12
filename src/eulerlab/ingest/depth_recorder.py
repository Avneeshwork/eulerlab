"""`make depth-record` — record Kite's market depth for the Nifty 50 during market hours.

No free source sells NSE's past order book (research 130): NSE Data &
Analytics and paid vendors do. So the order book is recorded from the day this
first ran, forward only.

What is recorded is what a Kite Connect subscription streams in ``full`` mode
over the WebSocket: per tick, the last trade (price, quantity, time), day
volume, total buy and sell quantity, open interest for the future, and the
**best five bid and ask levels** (price, quantity, number of orders). It is
not NSE's tick-by-tick order feed: Kite sends a snapshot when something
changes, at most about once a second per instrument, and never individual
orders. docs/STUBS.md S-052.

Instruments: the 50 Nifty stocks (from NSE's own constituent file, read at
start), the NIFTY 50 index (last price only; an index has no book) and the
nearest-expiry NIFTY future.

Every tick row carries ``event_time`` (the exchange timestamp Kite reports)
and ``knowledge_time`` (when this machine received it). Rows are buffered and
written every minute as an immutable Parquet part under
``data/landing/kite_depth/YYYY-MM-DD/``, each recorded with its SHA-256 in
``manifest.jsonl``; a crash loses at most a minute. The
recorder stops itself at 15:31 IST.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from eulerlab.env import load_env, require
from eulerlab.ingest.fetch import Fetcher, FetchPolicy, UrllibTransport
from eulerlab.ingest.kite_mcx_indices import _access_token
from eulerlab.ingest.nse_eod import IST
from eulerlab.paths import data_path

LANDING_ROOT = data_path("landing/kite_depth")
NIFTY50_LIST = "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv"
LEVELS = 5
FLUSH_EVERY_S = 60.0
STOP_AT = (15, 31)

_FIELDS: list[tuple[str, pa.DataType]] = [
    ("event_time", pa.string()),
    ("knowledge_time", pa.string()),
    ("instrument_token", pa.int64()),
    ("symbol", pa.string()),
    ("last_price", pa.float64()),
    ("last_quantity", pa.int64()),
    ("last_trade_time", pa.string()),
    ("average_price", pa.float64()),
    ("volume", pa.int64()),
    ("buy_quantity", pa.int64()),
    ("sell_quantity", pa.int64()),
    ("oi", pa.int64()),
    *[
        (f"{side}{n}_{field}", pa.float64() if field == "price" else pa.int64())
        for side in ("bid", "ask")
        for n in range(1, LEVELS + 1)
        for field in ("price", "qty", "orders")
    ],
]
SCHEMA = pa.schema(_FIELDS)


def parse_constituents(payload: bytes) -> list[str]:
    """Symbols from NSE's `ind_nifty50list.csv`. Refuses anything not 40-60 rows."""
    rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig", errors="replace"))))
    symbols = [(r.get("Symbol") or "").strip() for r in rows]
    symbols = [s for s in symbols if s]
    if not 40 <= len(symbols) <= 60:
        raise ValueError(f"Nifty 50 list has {len(symbols)} symbols; refusing it")
    return symbols


# ASSUMPTION: A-076 - NFO rows carry instrument_type FUT and a date expiry.
def nearest_future(
    nfo: Iterable[Mapping[str, Any]], today: date, name: str = "NIFTY"
) -> Mapping[str, Any]:
    """The NFO future on `name` with the earliest expiry on or after today."""
    futures = [
        row
        for row in nfo
        if row.get("name") == name
        and row.get("instrument_type") == "FUT"
        and isinstance(row.get("expiry"), date)
        and row["expiry"] >= today
    ]
    if not futures:
        raise ValueError(f"no live {name} future in the NFO instrument list")
    return min(futures, key=lambda row: row["expiry"])


def _iso(value: object) -> str | None:
    if isinstance(value, datetime):
        stamp = value if value.tzinfo else value.replace(tzinfo=IST)
        return stamp.isoformat()
    return None


def tick_row(
    tick: Mapping[str, Any], symbols: Mapping[int, str], received: datetime
) -> dict[str, Any]:
    """One flat row from one KiteTicker full-mode tick. Missing levels are null."""
    token = int(tick["instrument_token"])
    row: dict[str, Any] = {
        "event_time": _iso(tick.get("exchange_timestamp")),
        "knowledge_time": received.astimezone(UTC).isoformat(),
        "instrument_token": token,
        "symbol": symbols.get(token, str(token)),
        "last_price": tick.get("last_price"),
        "last_quantity": tick.get("last_traded_quantity"),
        "last_trade_time": _iso(tick.get("last_trade_time")),
        "average_price": tick.get("average_traded_price"),
        "volume": tick.get("volume_traded"),
        "buy_quantity": tick.get("total_buy_quantity"),
        "sell_quantity": tick.get("total_sell_quantity"),
        "oi": tick.get("oi"),
    }
    depth = tick.get("depth") or {}
    for side, key in (("bid", "buy"), ("ask", "sell")):
        levels = list(depth.get(key) or [])
        for n in range(1, LEVELS + 1):
            level = levels[n - 1] if n <= len(levels) else {}
            row[f"{side}{n}_price"] = level.get("price")
            row[f"{side}{n}_qty"] = level.get("quantity")
            row[f"{side}{n}_orders"] = level.get("orders")
    return row


class PartWriter:
    """Buffers rows and writes each flush as its own read-only Parquet part."""

    def __init__(
        self, root: Path, clock: Callable[[], datetime] = lambda: datetime.now(IST)
    ) -> None:
        self.root = root
        self._clock = clock
        self._rows: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self.written = 0

    def add(self, rows: Iterable[dict[str, Any]]) -> None:
        with self._lock:
            self._rows.extend(rows)

    def flush(self) -> Path | None:
        with self._lock:
            rows, self._rows = self._rows, []
        if not rows:
            return None
        now = self._clock()
        folder = self.root / now.date().isoformat()
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"part-{now:%H%M%S}-{len(rows)}.parquet"
        tmp = target.with_suffix(".part")
        pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), tmp, compression="zstd")
        tmp.chmod(0o444)
        tmp.replace(target)
        entry = {
            "trade_date": now.date().isoformat(),
            "key": target.relative_to(self.root).as_posix(),
            "rows": len(rows),
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "knowledge_time": datetime.now(UTC).isoformat(),
        }
        with (self.root / "manifest.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
        self.written += len(rows)
        return target


def resolve_instruments(kite: Any, constituents: Sequence[str], today: date) -> dict[int, str]:
    """Token -> label for the stocks, the index and the nearest future."""
    nse = {row["tradingsymbol"]: int(row["instrument_token"]) for row in kite.instruments("NSE")}
    tokens: dict[int, str] = {}
    missing = [s for s in constituents if s not in nse]
    if missing:
        print(f"not in Kite's NSE list, skipped: {', '.join(missing)}")
    for symbol in constituents:
        if symbol in nse:
            tokens[nse[symbol]] = symbol
    if "NIFTY 50" in nse:
        tokens[nse["NIFTY 50"]] = "NIFTY50"
    future = nearest_future(kite.instruments("NFO"), today)
    tokens[int(future["instrument_token"])] = str(future["tradingsymbol"])
    return tokens


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="depth-record")
    parser.add_argument("--root", type=Path, default=LANDING_ROOT)
    parser.add_argument("--seconds", type=float, default=0, help="stop after N seconds (testing)")
    args = parser.parse_args(argv)

    from kiteconnect import KiteConnect, KiteTicker

    load_env()
    api_key = require("ZERODHA_API_KEY")
    try:
        token = _access_token()
    except RuntimeError as exc:
        print(f"depth-record: {exc}")
        return 1
    kite = KiteConnect(api_key=api_key, access_token=token)
    today = datetime.now(IST).date()
    transport = UrllibTransport()
    transport.establish_session()
    listing = Fetcher(transport, FetchPolicy(min_interval_s=1.0)).get(NIFTY50_LIST)
    if listing.payload is None:
        print(f"depth-record: could not read the Nifty 50 list ({listing.detail})")
        return 1
    symbols = resolve_instruments(kite, parse_constituents(listing.payload), today)
    print(f"recording {len(symbols)} instruments into {args.root}", flush=True)

    writer = PartWriter(args.root)
    ticker = KiteTicker(api_key, token)

    def on_ticks(_ws: Any, ticks: list[dict[str, Any]]) -> None:
        received = datetime.now(UTC)
        writer.add(tick_row(t, symbols, received) for t in ticks)

    def on_connect(ws: Any, _response: Any) -> None:
        ws.subscribe(list(symbols))
        ws.set_mode(ws.MODE_FULL, list(symbols))
        print("connected; subscribed in full mode", flush=True)

    def on_close(_ws: Any, code: Any, reason: Any) -> None:
        print(f"socket closed: {code} {reason}", flush=True)

    ticker.on_ticks = on_ticks
    ticker.on_connect = on_connect
    ticker.on_close = on_close
    ticker.connect(threaded=True)

    started = time.monotonic()
    try:
        while True:
            time.sleep(FLUSH_EVERY_S)
            part = writer.flush()
            if part:
                print(f"{part.name}  total {writer.written:,} rows", flush=True)
            now = datetime.now(IST)
            if (now.hour, now.minute) >= STOP_AT:
                break
            if args.seconds and time.monotonic() - started >= args.seconds:
                break
    finally:
        ticker.close()
        writer.flush()
    print(f"depth-record: {writer.written:,} rows for {today}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
