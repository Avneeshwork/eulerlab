"""Land Angel One's rolled, one-minute MCX Gold futures series.

SmartAPI's current-month Gold futures token serves its historical rolled futures
series, including prior expiries (per Angel One SmartAPI support). The token is
resolved from the live MCX scrip search on every run; downloaded chunks are
stored separately from Kite so source and timestamp provenance remain clear.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, cast
from zoneinfo import ZoneInfo

from eulerlab.env import load_env, require
from eulerlab.ingest.backfill_minute import last_complete_session
from eulerlab.ingest.kite_minute import Chunk, MinuteStore, candles_to_table

LANDING_ROOT = Path("data/landing/angel_mcx_gold")
CONTRACT_PATTERN = re.compile(r"^GOLD(\d{2}[A-Z]{3}\d{2})FUT$")
WINDOW_DAYS = 1
REQUEST_DELAY_S = 1.1
INDIA = ZoneInfo("Asia/Kolkata")


class HistoricalClient(Protocol):
    def getCandleData(self, historicDataParams: dict[str, str]) -> Any: ...
    def searchScrip(self, exchange: str, searchscrip: str) -> Any: ...


def _expiry(symbol: str) -> date | None:
    match = CONTRACT_PATTERN.fullmatch(symbol)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%d%b%y").replace(tzinfo=UTC).date()
    except ValueError:
        return None


def resolve_front_contract(client: HistoricalClient, on_date: date) -> dict[str, str]:
    """Resolve the nearest unexpired standard Gold futures token."""
    response = client.searchScrip("MCX", "GOLD")
    if not isinstance(response, dict) or response.get("status") is not True:
        detail = (
            response.get("message", "invalid search response")
            if isinstance(response, dict)
            else "invalid search response"
        )
        raise RuntimeError(f"Angel One could not resolve MCX Gold futures: {detail}")
    rows = response.get("data") or []
    candidates: list[tuple[date, dict[str, str]]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("tradingsymbol") or "")
        expiry = _expiry(symbol)
        token = str(row.get("symboltoken") or "")
        if row.get("exchange") == "MCX" and expiry and expiry >= on_date and token.isdigit():
            candidates.append(
                (expiry, {"symbol": symbol, "token": token, "expiry": expiry.isoformat()})
            )
    if not candidates:
        raise RuntimeError("Angel One returned no unexpired standard MCX Gold futures contract.")
    return min(candidates, key=lambda item: item[0])[1]


def _windows(start: date, end: date) -> list[tuple[date, date]]:
    """Use one-session windows; larger MCX requests timed out in live probes."""
    if start > end:
        raise ValueError("start must be on or before end")
    result: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            result.append((cursor, cursor))
        cursor += timedelta(days=WINDOW_DAYS)
    return result


def fetch_history(
    client: HistoricalClient,
    store: MinuteStore,
    contract: dict[str, str],
    *,
    start: date,
    end: date,
    delay_s: float = REQUEST_DELAY_S,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, int | str]:
    """Fetch/resume minute chunks; stop on API errors without marking them landed."""
    totals: dict[str, int | str] = {"downloaded": 0, "skipped": 0, "rows": 0}
    symbol, token = contract["symbol"], int(contract["token"])
    if delay_s:
        # SmartAPI applies a stricter practical gate immediately after its
        # instrument-search route, despite publishing a shared 3 req/s limit.
        time.sleep(delay_s)
    for window_start, window_end in _windows(start, end):
        chunk = Chunk(
            symbol,
            token,
            window_start,
            window_end,
            from_time="09:00:00",
            to_time="23:59:00",
        )
        if store.has(chunk):
            totals["skipped"] = int(totals["skipped"]) + 1
            continue
        params = {
            "exchange": "MCX",
            "symboltoken": str(token),
            "interval": "ONE_MINUTE",
            "fromdate": f"{window_start.isoformat()} 09:00",
            "todate": f"{window_end.isoformat()} 23:59",
        }
        response: Any = None
        last_error: Exception | None = None
        for attempt, cooldown in enumerate((0, 5, 15, 30), start=1):
            if cooldown:
                print(f"Angel One rate/API retry {attempt - 1}/3 after {cooldown}s")
                time.sleep(cooldown)
            try:
                response = client.getCandleData(params)
                last_error = None
                if isinstance(response, dict) and response.get("status") is not True:
                    detail = str(response.get("message") or response.get("errorcode") or "")
                    lowered = detail.lower()
                    if any(
                        part in lowered
                        for part in ("access rate", "rate limit", "something went wrong")
                    ):
                        last_error = RuntimeError(detail)
                        continue
                break
            except Exception as exc:
                last_error = exc
                text = str(exc).lower()
                transient = ("access rate", "rate limit", "timed out", "connection", "temporar")
                if not any(part in text for part in transient):
                    break
        if last_error is not None:
            raise RuntimeError(
                f"Angel One candles {window_start}..{window_end}: "
                f"{type(last_error).__name__}: {last_error}"
            ) from last_error
        if not isinstance(response, dict) or response.get("status") is not True:
            detail = (
                response.get("message", "invalid candle response")
                if isinstance(response, dict)
                else "invalid candle response"
            )
            raise RuntimeError(f"Angel One candles {window_start}..{window_end}: {detail}")
        candles = response.get("data") or []
        table = candles_to_table(candles)
        # Empty holiday windows are recorded too, so reruns remain incremental.
        store.write(chunk, table)
        totals["downloaded"] = int(totals["downloaded"]) + 1
        totals["rows"] = int(totals["rows"]) + table.num_rows
        if table.num_rows:
            print(f"{window_start}..{window_end}: {table.num_rows:,} one-minute candles")
        if on_progress and int(totals["downloaded"]) % 25 == 0:
            on_progress(f"{window_end} · {int(totals['rows']):,} candles landed")
        if delay_s:
            time.sleep(delay_s)
    return totals


def _make_client() -> HistoricalClient:
    """Log in without persisting the JWT or TOTP code to disk."""
    try:
        import logzero  # type: ignore[import-untyped]
        import pyotp
        from SmartApi import SmartConnect  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError("Install the Angel One extras with `uv sync --extra angel`.") from exc

    logzero.logger.disabled = True  # searchScrip otherwise logs thousands of instruments
    client = SmartConnect(require("ANGEL_API_KEY"))
    session = client.generateSession(
        require("ANGEL_CLIENT_CODE"),
        require("ANGEL_PIN"),
        pyotp.TOTP(require("ANGEL_TOTP_SECRET")).now(),
    )
    if not isinstance(session, dict) or session.get("status") is not True:
        detail = (
            session.get("message", "login failed") if isinstance(session, dict) else "login failed"
        )
        raise RuntimeError(f"Angel One SmartAPI login failed: {detail}")
    return cast(HistoricalClient, client)


def _write_metadata(
    root: Path,
    contract: dict[str, str],
    *,
    start: date,
    end: date,
    rows: int,
    status: str,
) -> None:
    metadata = {
        "source": "Angel One SmartAPI",
        "exchange": "MCX",
        "interval": "ONE_MINUTE",
        "series": "standard GOLD front-month rolled futures history",
        "resolved_contract": contract,
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "downloaded_at_utc": datetime.now(UTC).isoformat(),
        "candles_downloaded_this_run": rows,
        "status": status,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "source.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="angel-mcx-gold")
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--from", dest="start", type=date.fromisoformat)
    parser.add_argument("--to", dest="end", type=date.fromisoformat)
    parser.add_argument("--root", type=Path, default=LANDING_ROOT)
    parser.add_argument("--delay", type=float, default=REQUEST_DELAY_S)
    args = parser.parse_args(argv)
    if args.years < 1:
        parser.error("--years must be at least 1")
    if args.delay < 0.34:
        parser.error("--delay must be at least 0.34 seconds (SmartAPI's documented 3 req/s limit)")

    load_env()
    try:
        client = _make_client()
        end = args.end or last_complete_session()
        start = args.start or end - timedelta(days=365 * args.years)
        contract = resolve_front_contract(client, end)
        store = MinuteStore(args.root)
        print(
            f"Angel One MCX Gold rolled futures · {contract['symbol']} · token {contract['token']}"
        )
        print(f"range: {start} .. {end} · {len(_windows(start, end))} resumable request windows")
        _write_metadata(args.root, contract, start=start, end=end, rows=0, status="in_progress")
        try:
            totals = fetch_history(
                client, store, contract, start=start, end=end, delay_s=args.delay
            )
        except RuntimeError:
            rows = (
                sum(
                    int(json.loads(line).get("rows", 0))
                    for line in store.manifest_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                )
                if store.manifest_path.exists()
                else 0
            )
            _write_metadata(args.root, contract, start=start, end=end, rows=rows, status="partial")
            raise
        _write_metadata(
            args.root,
            contract,
            start=start,
            end=end,
            rows=int(totals["rows"]),
            status="complete",
        )
    except (OSError, RuntimeError, ValueError, SystemExit) as exc:
        print(f"angel-mcx-gold: {exc}")
        return 1
    print(
        f"landed {totals['rows']:,} new candles in {totals['downloaded']} windows; "
        f"skipped {totals['skipped']} existing windows at {args.root}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
