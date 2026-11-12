"""One-minute NSE bars from Angel One SmartAPI, for sessions Kite could not fetch.

Kite's token lapses at 06:00 IST each day and needs a browser login; Angel's
SmartAPI logs in headless with TOTP. So a session the nightly minute step
missed (no Kite login, or Muhurat on Sunday 2026-11-08, ADR-157) is filled
from Angel.

Stored uniformly with Kite's bars (operator, 2026-11-09): equities in
`data/landing/kite_minute`, the indices in `data/landing/kite_index_minute`
under Kite's folder names, the same `MinuteStore` files, columns and
timestamp format (`+0530`). Backtests, the B2 upload and Kite's own planning
read them unchanged; Kite does not fetch a day Angel already landed. Each
manifest line says `"source": "angel_one"`, so the source of every bar stays
visible. Equities from the same universe file as `backfill_minute`, plus
NIFTY 50, NIFTY BANK and INDIA VIX.

The first fills (2026-11-09) landed in `data/landing/angel_minute`; that tree
is raw and kept, and `--migrate` copies it into the uniform stores once.

`make angel-minute FROM=2026-11-08 TO=2026-11-08`.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from eulerlab.broker.angel_check import download_master, master_tokens
from eulerlab.env import load_env
from eulerlab.ingest.angel_mcx_gold import _make_client
from eulerlab.ingest.backfill_minute import DEFAULT_UNIVERSE, complete_days
from eulerlab.ingest.kite_minute import Chunk, MinuteStore, candles_to_table, read_universe
from eulerlab.ingest.nse_eod import session_days
from eulerlab.paths import data_path

OLD_ROOT = data_path("landing/angel_minute")
"""Where the first fills landed, before storage was made uniform. Raw; kept."""
STOCK_ROOT = data_path("landing/kite_minute")
INDEX_ROOT = data_path("landing/kite_index_minute")
SOURCE = "angel_one"
SCRIP_MASTER = (
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
)
REQUEST_DELAY_S = 1.0
"""SmartAPI documents 3 requests a second but refused at 0.4 s on 2026-11-09; 1 s holds."""

INDICES = {"NIFTY 50": "Nifty 50", "NIFTY BANK": "Nifty Bank", "INDIA VIX": "India VIX"}
"""Our folder name -> the scrip master's `symbol` for the index (exch_seg NSE,
instrumenttype AMXIDX). Read from the master on 2026-11-09: tokens 99926000,
99926009 and 99926017. A renamed index is reported as not in the master."""

KITE_FOLDERS = {"NIFTY 50": "NIFTY50", "NIFTY BANK": "NIFTYBANK", "INDIA VIX": "INDIAVIX"}
"""Our index name -> the folder `kite_index_minute` stores it under."""


def kite_ts(stamp: object) -> str:
    """Angel's `2026-11-08T14:20:00+05:30` written as Kite writes it, `...+0530`."""
    text = str(stamp)
    if len(text) >= 6 and text[-3] == ":" and text[-6] in "+-":
        return text[:-3] + text[-2:]
    return text


_SPANS: dict[Path, dict[str, list[tuple[date, date]]]] = {}


def held(store: MinuteStore, symbol: str, day: date) -> bool:
    """Whether `store` holds `day` for `symbol` in any chunk, Kite's or Angel's.

    The manifest is read once per store per process: it has tens of thousands
    of lines and is asked once per symbol per day."""
    spans = _SPANS.get(store.manifest_path)
    if spans is None:
        spans = _SPANS[store.manifest_path] = store.covered()
    return any(a <= day <= b for a, b in spans.get(symbol, ()))


def _note(store: MinuteStore, symbol: str, day: date) -> None:
    if store.manifest_path in _SPANS:
        _SPANS[store.manifest_path].setdefault(symbol, []).append((day, day))


def store_for(symbol: str, stocks: MinuteStore, indices: MinuteStore) -> tuple[MinuteStore, str]:
    """The uniform store and folder a symbol lands in."""
    if symbol in KITE_FOLDERS:
        return indices, KITE_FOLDERS[symbol]
    return stocks, symbol


def nse_tokens(rows: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """Our symbol -> Angel token: cash lines (`angel_check.master_tokens`) plus
    the three indices."""
    out = master_tokens(rows)
    for row in rows:
        if row.get("exch_seg") != "NSE" or str(row.get("instrumenttype") or "") != "AMXIDX":
            continue
        symbol, token = str(row.get("symbol") or ""), str(row.get("token") or "")
        for folder, name in INDICES.items():
            if symbol == name and token:
                out[folder] = token  # e.g. "Nifty 50" -> 99926000
    return out


def fetch_day(
    client: Any,
    store: MinuteStore,
    symbol: str,
    token: str,
    day: date,
    *,
    today: date | None = None,
) -> int:
    """One symbol, one session, into `store` under `symbol`.

    Returns the bars landed; -1 if already held (by Kite or Angel), -2 when
    the session is today's and not complete yet: a part-day landed would be
    held as the whole day and never fetched again.
    """
    chunk = Chunk(symbol, int(token), day, day, from_time="09:00:00", to_time="23:59:00")
    if store.has(chunk) or held(store, symbol, day):
        return -1
    params = {
        "exchange": "NSE",
        "symboltoken": token,
        "interval": "ONE_MINUTE",
        "fromdate": f"{day.isoformat()} 09:00",
        "todate": f"{day.isoformat()} 23:59",
    }
    reply: Any = None
    for cooldown in (0, 2, 5, 15, 30):
        if cooldown:
            time.sleep(cooldown)
        try:
            reply = client.getCandleData(params)
        except Exception as exc:  # SmartAPI raises on its plain-text rate-limit reply
            if "rate" in str(exc).lower():
                continue
            raise RuntimeError(f"Angel candles {symbol} {day}: {exc}") from exc
        if isinstance(reply, dict) and reply.get("status") is True:
            break
        detail = str((reply or {}).get("message", "")) if isinstance(reply, dict) else ""
        if "rate" not in detail.lower() and "something went wrong" not in detail.lower():
            break
    if not isinstance(reply, dict) or reply.get("status") is not True:
        detail = str(reply.get("message")) if isinstance(reply, dict) else "no reply"
        raise RuntimeError(f"Angel candles {symbol} {day}: {detail}")
    candles = [[kite_ts(c[0]), *c[1:]] for c in list(reply.get("data") or []) if c]
    kept, candles = complete_days(
        chunk, candles, today or datetime.now(ZoneInfo("Asia/Kolkata")).date()
    )
    if kept is None:
        return -2
    table = candles_to_table(candles)
    store.write(chunk, table, source=SOURCE)
    _note(store, symbol, day)
    return int(table.num_rows)


def migrate(old: Path = OLD_ROOT, stocks: Path = STOCK_ROOT, indices: Path = INDEX_ROOT) -> int:
    """Copy the first fills from `old` into the uniform stores. Returns files copied.

    The old tree is left as it is (raw data is immutable); a day either store
    already holds is skipped, so running it twice copies nothing.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    manifest = old / "manifest.jsonl"
    if not manifest.exists():
        return 0
    stock_store, index_store = MinuteStore(stocks), MinuteStore(indices)
    copied = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if "path" not in row or "symbol" not in row:
            continue  # an unresolvable-symbol note, not a file
        store, folder = store_for(str(row["symbol"]), stock_store, index_store)
        day = date.fromisoformat(str(row["start"]))
        chunk = Chunk(folder, int(row.get("token") or 0), day, date.fromisoformat(str(row["end"])))
        if store.has(chunk) or held(store, folder, day):
            continue
        table = pq.read_table(old / str(row["path"]))
        stamps = pa.array([kite_ts(t) for t in table.column("ts").to_pylist()], pa.string())
        table = table.set_column(table.schema.get_field_index("ts"), "ts", stamps)
        store.write(chunk, table, source=SOURCE, knowledge_time=str(row.get("knowledge_time")))
        _note(store, folder, day)
        copied += 1
    return copied


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="angel-minute", description=__doc__)
    parser.add_argument("--from", dest="start", type=date.fromisoformat)
    parser.add_argument("--to", dest="end", type=date.fromisoformat)
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--root", type=Path, default=STOCK_ROOT)
    parser.add_argument("--index-root", type=Path, default=INDEX_ROOT)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--migrate", action="store_true", help=f"copy {OLD_ROOT} into the uniform stores, once"
    )
    args = parser.parse_args(argv)

    if args.migrate:
        print(f"angel-minute: copied {migrate(OLD_ROOT, args.root, args.index_root)} file(s)")
        return 0
    if args.start is None:
        parser.error("--from is required")
    load_env()
    days = session_days(args.start, args.end or args.start)
    symbols = [*INDICES, *read_universe(args.universe)]
    if args.limit:
        symbols = symbols[: args.limit]
    tokens = nse_tokens(download_master())
    missing = [s for s in symbols if s not in tokens]
    client = _make_client()
    stocks, indices = MinuteStore(args.root), MinuteStore(args.index_root)
    print(
        f"angel-minute: {len(days)} session(s) {args.start}..{args.end or args.start}, "
        f"{len(symbols) - len(missing)} symbols ({len(missing)} not in Angel's master)"
    )
    counts = {"landed": 0, "held": 0, "empty": 0, "incomplete": 0, "failed": 0, "bars": 0}
    for day in days:
        for symbol in symbols:
            if symbol not in tokens:
                continue
            store, folder = store_for(symbol, stocks, indices)
            try:
                got = fetch_day(client, store, folder, tokens[symbol], day)
            except RuntimeError as exc:
                counts["failed"] += 1
                print(f"  failed: {exc}")
                continue
            if got == -1:
                counts["held"] += 1
                continue
            if got == -2:
                counts["incomplete"] += 1
            else:
                counts["landed" if got else "empty"] += 1
                counts["bars"] += got
            time.sleep(REQUEST_DELAY_S)
    print(f"  done: {counts}")
    if missing:
        print(f"  not in Angel's master: {', '.join(missing[:20])}")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
