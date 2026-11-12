"""Fetch available minute candles for the current standard MCX Gold future.

Kite exposes minute history for live contracts, but its continuous endpoint for
expired MCX futures is daily only. This fetcher therefore walks backward by
calendar month for the current GOLD contract and stops at the first month with
no candles. MCX's evening session is included in each request.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

from eulerlab.env import load_env, require
from eulerlab.ingest.backfill_minute import last_complete_session
from eulerlab.ingest.kite_mcx import SESSION_FILE, parse_mcx_instruments
from eulerlab.ingest.kite_minute import (
    Chunk,
    KiteError,
    KiteHistorical,
    MinuteStore,
    candles_to_table,
)
from eulerlab.paths import data_path

LANDING_ROOT = data_path("landing/mcx_gold")
MASTER_ROOT = data_path("landing/mcx/instruments")
CONTRACT = re.compile(r"^GOLD\d{2}[A-Z]{3}FUT$")
MIN_INTERVAL_S = 0.34


class HistoricalClient(Protocol):
    def candles(self, chunk: Chunk, interval: str = "minute") -> list[list[object]]: ...


def _master_path() -> Path:
    candidates = sorted(MASTER_ROOT.glob("**/*_instruments.csv"))
    if not candidates:
        raise RuntimeError("No saved MCX instrument snapshot. Run `make mcx-instruments` first.")
    return candidates[-1]


def _front_gold_contract(master_path: Path, on_date: date) -> dict[str, str]:
    with master_path.open("rb") as handle:
        rows = parse_mcx_instruments(handle.read())
    futures = [
        row
        for row in rows
        if row.get("instrument_type") == "FUT"
        and CONTRACT.fullmatch(row.get("tradingsymbol", ""))
        and row.get("expiry")
        and date.fromisoformat(row["expiry"]) >= on_date
    ]
    if not futures:
        raise RuntimeError(f"No unexpired standard GOLD futures contract in {master_path}.")
    return min(futures, key=lambda row: row["expiry"])


def _month_bounds(day: date) -> tuple[date, date]:
    first = day.replace(day=1)
    if first.month == 12:
        next_month = date(first.year + 1, 1, 1)
    else:
        next_month = date(first.year, first.month + 1, 1)
    return first, min(day, next_month - timedelta(days=1))


def fetch_available_history(
    client: HistoricalClient,
    store: MinuteStore,
    contract: dict[str, str],
    *,
    end: date,
    years: int = 5,
    sleep_s: float = MIN_INTERVAL_S,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, int | str]:
    """Fetch stable month chunks until Kite has no earlier live-token candles."""
    symbol = contract["tradingsymbol"]
    token = int(contract["instrument_token"])
    earliest = end - timedelta(days=365 * years)
    totals: dict[str, int | str] = {"downloaded": 0, "skipped": 0, "rows": 0, "first_date": ""}
    # Download the current month one session at a time so every daily refresh
    # has an immutable, stable key. Older months are compact month chunks.
    month_start, _ = _month_bounds(end)
    for session_day in (
        month_start + timedelta(days=i) for i in range((end - month_start).days + 1)
    ):
        if session_day < earliest or session_day.weekday() >= 5:
            continue
        chunk = Chunk(
            symbol, token, session_day, session_day, from_time="09:00:00", to_time="23:55:00"
        )
        if store.has(chunk):
            entry = _manifest_entry(store, chunk.key)
            totals["skipped"] = int(totals["skipped"]) + 1
            if entry:
                totals["rows"] = int(totals["rows"]) + _entry_int(entry, "rows")
                totals["first_date"] = min(
                    str(totals["first_date"]) or _entry_text(entry, "start"),
                    _entry_text(entry, "start"),
                )
            continue
        candles = client.candles(chunk)
        if not candles:
            if sleep_s:
                time.sleep(sleep_s)
            continue  # holidays are normal; keep checking earlier weekdays
        table = candles_to_table(candles)
        store.write(chunk, table)
        totals["downloaded"] = int(totals["downloaded"]) + 1
        totals["rows"] = int(totals["rows"]) + table.num_rows
        candle_start = str(candles[0][0])[:10]
        totals["first_date"] = min(str(totals["first_date"]) or candle_start, candle_start)
        print(f"{symbol} {session_day}: {table.num_rows:,} candles")
        if on_progress:
            on_progress(f"{symbol} · {session_day} · {int(totals['rows']):,} candles")
        if sleep_s:
            time.sleep(sleep_s)

    cursor = month_start - timedelta(days=1)
    while cursor >= earliest:
        start, stop = _month_bounds(cursor)
        chunk = Chunk(symbol, token, start, stop, from_time="09:00:00", to_time="23:55:00")
        if store.has(chunk):
            entry = _manifest_entry(store, chunk.key)
            rows = _entry_int(entry, "rows") if entry else 0
            totals["skipped"] = int(totals["skipped"]) + 1
            if rows == 0 or entry is None:
                break
            totals["rows"] = int(totals["rows"]) + rows
            totals["first_date"] = min(
                str(totals["first_date"]) or _entry_text(entry, "start"),
                _entry_text(entry, "start"),
            )
        else:
            candles = client.candles(chunk)
            if not candles:
                if on_progress:
                    on_progress(f"{symbol} · no earlier minute candles before {start}")
                if sleep_s:
                    time.sleep(sleep_s)
                break
            table = candles_to_table(candles)
            store.write(chunk, table)
            totals["downloaded"] = int(totals["downloaded"]) + 1
            totals["rows"] = int(totals["rows"]) + table.num_rows
            candle_start = str(candles[0][0])[:10]
            totals["first_date"] = min(str(totals["first_date"]) or candle_start, candle_start)
            print(f"{symbol} {start}..{stop}: {table.num_rows:,} candles")
            if on_progress:
                on_progress(f"{symbol} · {stop} · {int(totals['rows']):,} candles")
            if sleep_s:
                time.sleep(sleep_s)
        cursor = start - timedelta(days=1)
    return totals


def _manifest_entry(store: MinuteStore, key: str) -> dict[str, object] | None:
    if not store.manifest_path.exists():
        return None
    for line in reversed(store.manifest_path.read_text(encoding="utf-8").splitlines()):
        try:
            parsed: object = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        row = {str(name): value for name, value in parsed.items()}
        if row.get("key") == key:
            return row
    return None


def _entry_int(entry: dict[str, object], field: str) -> int:
    value = entry.get(field, 0)
    if isinstance(value, (int, float, str)):
        return int(value)
    return 0


def _entry_text(entry: dict[str, object], field: str) -> str:
    value = entry.get(field, "")
    return value if isinstance(value, str) else str(value)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kite-mcx-gold")
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--to", dest="end", type=date.fromisoformat, default=None)
    parser.add_argument("--root", type=Path, default=LANDING_ROOT)
    args = parser.parse_args(argv)
    if args.years < 1:
        parser.error("--years must be at least 1")
    load_env()
    try:
        today = datetime.now(UTC).astimezone(ZoneInfo("Asia/Kolkata")).date()
        contract = _front_gold_contract(_master_path(), today)
        session = (
            json.loads(SESSION_FILE.read_text(encoding="utf-8")) if SESSION_FILE.exists() else {}
        )
        access_token = (
            session.get("access_token") or os.environ.get("ZERODHA_ACCESS_TOKEN", "").strip()
        )
        if not access_token:
            raise RuntimeError("No current Kite access token. Run `make kite-login` and retry.")
        client = KiteHistorical(require("ZERODHA_API_KEY"), access_token)
        end = args.end or last_complete_session()
        totals = fetch_available_history(
            client, MinuteStore(args.root), contract, end=end, years=args.years
        )
    except (KiteError, OSError, RuntimeError, ValueError, SystemExit) as exc:
        print(f"kite-mcx-gold: {exc}")
        return 1
    print(
        f"MCX Gold {contract['tradingsymbol']} (expiry {contract['expiry']}): "
        f"{totals['rows']:,} minute candles from {totals['first_date'] or 'no data'}; "
        "Kite continuous history for expired contracts is daily, not minute."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
