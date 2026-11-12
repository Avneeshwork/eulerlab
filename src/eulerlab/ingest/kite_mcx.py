"""Fetch and preserve Zerodha Kite's current MCX instrument master.

The broker generates this CSV once a day. It is a current tradable-contract
snapshot, not historical contract reference data. Raw bytes land unchanged and
are mirrored with the rest of the landing trees to the ``nse/mcx/`` B2 prefix.
"""

from __future__ import annotations

import csv
import gzip
import http.client
import io
import json
import os
import urllib.error
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

from eulerlab.env import load_env, require
from eulerlab.ingest.fetch import Fetcher, FetchPolicy, FetchResult, TransportError
from eulerlab.ingest.landing import Landing
from eulerlab.paths import data_path

MCX_URL = "https://api.kite.trade/instruments/MCX"
LANDING_ROOT = data_path("landing/mcx")
SESSION_FILE = Path(".kite_session.json")
REQUIRED_COLUMNS = frozenset(
    {
        "instrument_token",
        "tradingsymbol",
        "expiry",
        "tick_size",
        "lot_size",
        "instrument_type",
        "segment",
        "exchange",
    }
)


class KiteMCXError(RuntimeError):
    """Kite did not return a usable MCX instrument master."""


class PayloadFetcher(Protocol):
    def get(self, url: str) -> FetchResult: ...


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
    raise KiteMCXError("No current Kite access token. Run `make kite-login` and retry.")


class KiteTransport:
    """Small authenticated transport that keeps HTTP failures visible to Fetcher."""

    def __init__(self, api_key: str, access_token: str) -> None:
        self.authorization = f"token {api_key}:{access_token}"

    def get(self, url: str, *, timeout: float) -> tuple[int, bytes]:
        request = urllib.request.Request(
            url,
            headers={
                "X-Kite-Version": "3",
                "Authorization": self.authorization,
                "User-Agent": "EulerLab/0.1",
                "Accept-Encoding": "identity",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except (http.client.HTTPException, urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TransportError(f"Kite request failed: {type(exc).__name__}: {exc}") from exc


def _csv_bytes(payload: bytes) -> bytes:
    return gzip.decompress(payload) if payload.startswith(b"\x1f\x8b") else payload


def parse_mcx_instruments(payload: bytes) -> list[dict[str, str]]:
    """Validate the Kite CSV and return the MCX rows without normalizing values."""
    try:
        text = _csv_bytes(payload).decode("utf-8-sig")
    except (UnicodeDecodeError, OSError) as exc:
        raise KiteMCXError(f"Kite's MCX instrument response is not readable CSV: {exc}") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    columns = set(reader.fieldnames or ())
    missing = sorted(REQUIRED_COLUMNS - columns)
    if missing:
        raise KiteMCXError(f"Kite's MCX CSV is missing columns: {', '.join(missing)}")

    rows: list[dict[str, str]] = []
    for line, raw in enumerate(reader, start=2):
        if not raw or not any(value for value in raw.values() if value is not None):
            continue
        if (raw.get("exchange") or "").strip() != "MCX":
            continue
        row = {key: (value or "").strip() for key, value in raw.items() if key is not None}
        if not row.get("instrument_token", "").isdigit() or not row.get("tradingsymbol"):
            raise KiteMCXError(f"Kite's MCX CSV has an invalid token or symbol on line {line}.")
        if not row.get("lot_size") or not row.get("tick_size"):
            raise KiteMCXError(f"Kite's MCX CSV is missing lot or tick size on line {line}.")
        rows.append(row)
    if not rows:
        raise KiteMCXError("Kite returned no MCX instruments; nothing was saved.")
    return rows


def fetch_snapshot(
    fetcher: PayloadFetcher,
    landing: Landing,
    trade_date: date,
) -> str:
    """Land one immutable daily snapshot, or skip if today's bytes already landed."""
    segment = "instruments"
    if landing.has(trade_date, segment):
        print(f"MCX instruments {trade_date}: already landed")
        return "skipped"

    result = fetcher.get(MCX_URL)
    if not result.ok or result.payload is None:
        raise KiteMCXError(f"Could not fetch MCX instruments: {result.detail or result.status}")
    rows = parse_mcx_instruments(result.payload)
    suffix = "csv.gz" if result.payload.startswith(b"\x1f\x8b") else "csv"
    entry = landing.write(
        trade_date=trade_date,
        segment=segment,
        file_format="instruments",
        url=MCX_URL,
        payload=result.payload,
        rows=len(rows),
        inner_name="Kite MCX instrument master",
        suffix=suffix,
    )
    print(
        f"MCX instruments {trade_date}: landed {len(rows):,} rows "
        f"({entry.size_bytes:,} bytes, sha256 {entry.sha256[:12]})"
    )
    return "downloaded"


def main() -> int:
    try:
        api_key = require("ZERODHA_API_KEY")
        token = _access_token()
        transport = KiteTransport(api_key, token)
        fetcher = Fetcher(transport, FetchPolicy(max_attempts=3, timeout_s=60.0))
        today_ist = datetime.now(UTC).astimezone(ZoneInfo("Asia/Kolkata")).date()
        fetch_snapshot(fetcher, Landing(LANDING_ROOT), today_ist)
    except (KiteMCXError, SystemExit) as exc:
        print(f"kite-mcx: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
