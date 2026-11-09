"""One-minute NSE bars from Angel One SmartAPI, for sessions Kite could not fetch.

Kite's token lapses at 06:00 IST each day and needs a browser login; Angel's
SmartAPI logs in headless with TOTP. So a session the nightly minute step
missed (Muhurat on Sunday 2026-11-08, ADR-157) can be filled from Angel.

Lands in its own tree, `data/landing/angel_minute`, in the Kite minute layout
(`MinuteStore`, one parquet per symbol and day, `candles_to_table` columns),
so the source of every bar stays visible. Equities from the same universe file
as `backfill_minute`, plus NIFTY 50, NIFTY BANK and INDIA VIX.

`make angel-minute FROM=2026-11-08 TO=2026-11-08`.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from eulerlab.broker.angel_check import download_master, master_tokens
from eulerlab.env import load_env
from eulerlab.ingest.angel_mcx_gold import _make_client
from eulerlab.ingest.backfill_minute import DEFAULT_UNIVERSE
from eulerlab.ingest.kite_minute import Chunk, MinuteStore, candles_to_table, read_universe
from eulerlab.ingest.nse_eod import session_days

LANDING_ROOT = Path("data/landing/angel_minute")
SCRIP_MASTER = (
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
)
REQUEST_DELAY_S = 1.0
"""SmartAPI documents 3 requests a second but refused at 0.4 s on 2026-11-09; 1 s holds."""

INDICES = {"NIFTY 50": "Nifty 50", "NIFTY BANK": "Nifty Bank", "INDIA VIX": "India VIX"}
"""Our folder name -> the scrip master's `symbol` for the index (exch_seg NSE,
instrumenttype AMXIDX). Read from the master on 2026-11-09: tokens 99926000,
99926009 and 99926017. A renamed index is reported as not in the master."""


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


def fetch_day(client: Any, store: MinuteStore, symbol: str, token: str, day: date) -> int:
    """One symbol, one session. Returns the bars landed; -1 if already held."""
    chunk = Chunk(symbol, int(token), day, day, from_time="09:00:00", to_time="23:59:00")
    if store.has(chunk):
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
    table = candles_to_table(list(reply.get("data") or []))
    store.write(chunk, table)
    return int(table.num_rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="angel-minute", description=__doc__)
    parser.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    parser.add_argument("--to", dest="end", type=date.fromisoformat, required=True)
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--root", type=Path, default=LANDING_ROOT)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)

    load_env()
    days = session_days(args.start, args.end)
    symbols = [*INDICES, *read_universe(args.universe)]
    if args.limit:
        symbols = symbols[: args.limit]
    tokens = nse_tokens(download_master())
    missing = [s for s in symbols if s not in tokens]
    client = _make_client()
    store = MinuteStore(args.root)
    print(
        f"angel-minute: {len(days)} session(s) {args.start}..{args.end}, "
        f"{len(symbols) - len(missing)} symbols ({len(missing)} not in Angel's master)"
    )
    counts = {"landed": 0, "held": 0, "empty": 0, "failed": 0, "bars": 0}
    for day in days:
        for symbol in symbols:
            if symbol not in tokens:
                continue
            try:
                got = fetch_day(client, store, symbol, tokens[symbol], day)
            except RuntimeError as exc:
                counts["failed"] += 1
                print(f"  failed: {exc}")
                continue
            if got < 0:
                counts["held"] += 1
                continue
            counts["landed" if got else "empty"] += 1
            counts["bars"] += max(got, 0)
            time.sleep(REQUEST_DELAY_S)
    print(f"  done: {counts}")
    if missing:
        print(f"  not in Angel's master: {', '.join(missing[:20])}")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
