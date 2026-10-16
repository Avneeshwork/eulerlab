"""Backfill Kite minute candles for the MCX iCOMDEX indices.

Kite lists a small subset of the iCOMDEX family as MCX index instruments.
The source's history is uneven: this job only fetches mapped symbols with a
current MCX index token, queries the full requested window, and records the
requested indices Kite cannot serve in ``unresolved.jsonl``. Data is append-only
Parquet in the landing zone.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Protocol

from eulerlab.env import load_env, require
from eulerlab.ingest.backfill_minute import last_complete_session
from eulerlab.ingest.kite_minute import (
    Chunk,
    KiteError,
    KiteHistorical,
    MinuteStore,
    candles_to_table,
    uncovered_chunks,
)

LANDING_ROOT = Path("data/landing/mcx_indices")
SESSION_FILE = Path(".kite_session.json")
MIN_INTERVAL_S = 0.34


class HistoricalClient(Protocol):
    def instruments(self, exchange: str = "NSE") -> dict[str, int]: ...

    def candles(self, chunk: Chunk, interval: str = "minute") -> list[list[object]]: ...


@dataclass(frozen=True)
class IndexSpec:
    name: str
    symbol: str | None
    reason: str = ""


# These map the names in MCX's iCOMDEX list to Kite's instrument symbols.
INDEX_SPECS = (
    IndexSpec("MCX iCOMDEX Composite", "MCXCOMPDEX"),
    IndexSpec("MCX iCOMDEX Bullion", "MCXBULLDEX"),
    IndexSpec("MCX iCOMDEX Base Metal", "MCXMETLDEX"),
    IndexSpec(
        "MCX iCOMDEX Energy",
        "MCXENERGY",
        "Kite lists the index token, but five-year minute-history requests returned no candles.",
    ),
    IndexSpec("MCX iCOMDEX Gold", "MCXGOLDEX"),
    IndexSpec("MCX iCOMDEX Silver", "MCXSILVDEX"),
    IndexSpec(
        "MCX iCOMDEX Aluminium",
        None,
        "No standalone MCX index token in Kite's instrument list.",
    ),
    IndexSpec("MCX iCOMDEX Copper", "MCXCOPRDEX"),
    IndexSpec("MCX iCOMDEX Lead", None, "No standalone MCX index token in Kite's instrument list."),
    IndexSpec("MCX iCOMDEX Zinc", None, "No standalone MCX index token in Kite's instrument list."),
    IndexSpec("MCX iCOMDEX Crude Oil", "MCXCRUDEX"),
    IndexSpec(
        "MCX iCOMDEX Natural Gas",
        None,
        "No standalone MCX index token in Kite's instrument list.",
    ),
)


def _access_token() -> str:
    if SESSION_FILE.exists():
        try:
            raw = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        token = raw.get("access_token") if isinstance(raw, dict) else None
        if isinstance(token, str) and token.strip():
            return token.strip()
    load_env()
    token = os.environ.get("ZERODHA_ACCESS_TOKEN", "").strip()
    if token:
        return token
    raise RuntimeError(
        "No current Kite access token. Log in to Kite on the Instruments page and retry."
    )


def _record_unresolved(store: MinuteStore, spec: IndexSpec, reason: str) -> None:
    path = store.root / "unresolved.jsonl"
    latest: dict[str, dict[str, object]] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
                latest[str(entry.get("symbol", ""))] = entry
            except json.JSONDecodeError:
                continue
    current = latest.get(spec.name)
    if (
        current is not None
        and not current.get("resolved", False)
        and current.get("reason") == reason
    ):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps({"symbol": spec.name, "reason": reason, "resolved": False}, sort_keys=True)
            + "\n"
        )


def _record_resolved(store: MinuteStore, spec: IndexSpec) -> None:
    path = store.root / "unresolved.jsonl"
    if not path.exists():
        return
    latest: dict[str, dict[str, object]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
            latest[str(entry.get("symbol", ""))] = entry
        except json.JSONDecodeError:
            continue
    current = latest.get(spec.name)
    if current is None or current.get("resolved", False):
        return
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {"symbol": spec.name, "reason": "minute candles are now present", "resolved": True},
                sort_keys=True,
            )
            + "\n"
        )


def backfill(
    client: HistoricalClient,
    store: MinuteStore,
    *,
    end: date,
    years: int = 5,
    sleep_s: float = MIN_INTERVAL_S,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Fetch all available requested history, resuming from the manifest."""
    requested_start = end - timedelta(days=365 * years)
    tokens = client.instruments(exchange="MCX")
    totals = {"downloaded": 0, "skipped": 0, "rows": 0, "failed": 0}
    held = store.covered()

    for spec in INDEX_SPECS:
        if spec.symbol is None:
            _record_unresolved(store, spec, spec.reason)
            print(f"{spec.name}: unavailable — {spec.reason}")
            continue
        token = tokens.get(spec.symbol)
        if token is None:
            _record_unresolved(
                store, spec, f"{spec.symbol} is absent from Kite's current instrument list."
            )
            print(f"{spec.name}: unavailable — Kite instrument {spec.symbol} is missing")
            continue
        start = requested_start
        planned = list(uncovered_chunks(spec.symbol, token, start, end, held.get(spec.symbol, ())))
        print(f"{spec.name}: {spec.symbol}, {start} .. {end}, {len(planned)} chunks")
        if on_progress:
            on_progress(f"{spec.name} · {len(planned)} chunks")
        symbol_failed = 0
        for chunk in planned:
            if store.has(chunk):
                totals["skipped"] += 1
                continue
            try:
                candles = client.candles(chunk)
                table = candles_to_table(candles)
                store.write(chunk, table)
                totals["downloaded"] += 1
                totals["rows"] += table.num_rows
                print(f"  {chunk.start}..{chunk.end}: {table.num_rows:,} candles")
            except KiteError as exc:
                totals["failed"] += 1
                symbol_failed += 1
                print(f"  {chunk.start}..{chunk.end}: FAILED: {exc}")
            if on_progress:
                on_progress(f"{spec.name} · {chunk.end} · {totals['rows']:,} candles")
            if sleep_s:
                time.sleep(sleep_s)
        held = store.covered()
        rows_landed = _rows_for_symbol(store, spec.symbol)
        if rows_landed == 0 and symbol_failed == 0:
            reason = (
                spec.reason or f"Kite returned no minute candles for {years} years of requests."
            )
            _record_unresolved(store, spec, reason)
            print(f"{spec.name}: no candles returned across the requested range")
        elif rows_landed:
            _record_resolved(store, spec)

    return totals


def _rows_for_symbol(store: MinuteStore, symbol: str) -> int:
    path = store.manifest_path
    if not path.exists():
        return 0
    rows = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("symbol") == symbol:
            rows += int(entry.get("rows", 0))
    return rows


def main(
    argv: Sequence[str] | None = None,
    *,
    on_progress: Callable[[str], None] | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog="kite-mcx-indices")
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--to", dest="end", type=date.fromisoformat, default=None)
    parser.add_argument("--root", type=Path, default=LANDING_ROOT)
    args = parser.parse_args(argv)
    if args.years < 1:
        parser.error("--years must be at least 1")

    load_env()
    try:
        client = KiteHistorical(require("ZERODHA_API_KEY"), _access_token())
        end = args.end or last_complete_session()
        totals = backfill(
            client, MinuteStore(args.root), end=end, years=args.years, on_progress=on_progress
        )
    except (KiteError, RuntimeError, SystemExit) as exc:
        print(f"kite-mcx-indices: {exc}")
        return 1
    print(
        f"MCX iCOMDEX minute history: downloaded {totals['downloaded']} chunks, "
        f"{totals['rows']:,} candles, {totals['failed']} failed"
    )
    return 1 if totals["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
