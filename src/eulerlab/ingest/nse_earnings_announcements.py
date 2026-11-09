"""NSE financial-result announcement timestamps, landed raw and then derived.

Each calendar quarter's answer from NSE's corporate-announcements API lands
once, as received, in ``data/landing/nse_announcements/`` and is never fetched
again: re-running reads the landed file (idempotent, resumable). The derived
file keeps only "Financial Result Updates" rows, each with ``event_time`` (when
the company filed) and ``knowledge_time`` (when NSE disseminated it, the first
moment anyone outside could act). Research 114 uses it.
"""

from __future__ import annotations

import argparse
import json
from calendar import monthrange
from collections.abc import Iterator
from datetime import date, datetime
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, OpenerDirector, Request, build_opener
from zoneinfo import ZoneInfo

LANDING = Path("data/landing/nse_announcements")
OUT = Path("data/derived/nse_earnings_announcements.jsonl")
PAGE = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
API = "https://www.nseindia.com/api/corporate-announcements"
IST = ZoneInfo("Asia/Kolkata")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
)
SUBJECT = "Financial Result Updates"
BOARD_OUTCOME = "Outcome of Board Meeting"
RESULTS_TEXT = "the financial results for the"
"""Since 2026 (every daily answer landed from 2026-08-10) NSE files no "Financial Result
Updates" rows: results arrive only as board-meeting outcomes whose text says the company
"has submitted to the Exchange, the financial results for the period ended ...". Such a
row counts as a result for a (symbol, day) with no results row (HISTORY, research 182)."""
INCOMPLETE = ((date(2022, 7, 1), date(2022, 12, 31)),)
"""Windows where NSE filed results under other labels: 21 and 9 results rows
against about 1,800 a quarter elsewhere (checked 2026-10-16). Excluded from
any study rather than read as quarters with no results."""
ROUND_COUNTS = (1000, 2000, 5000, 10000, 20000, 50000)
"""Row counts that suggest the API stopped at a page limit, not at the data's end."""


def _exchange_time(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)
    except ValueError:
        return None
    return parsed.isoformat()


def windows(start: date, end: date) -> Iterator[tuple[date, date]]:
    """Calendar quarters covering [start, end], clipped at both ends."""
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        month = ((cursor.month - 1) // 3 + 1) * 3
        last_month = date(cursor.year, month, monthrange(cursor.year, month)[1])
        yield max(cursor, start), min(last_month, end)
        cursor = date(cursor.year + 1, 1, 1) if month == 12 else date(cursor.year, month + 1, 1)


def landing_path(window_start: date, window_end: date, root: Path = LANDING) -> Path:
    return root / f"{window_start.isoformat()}_{window_end.isoformat()}.json"


def _opener() -> OpenerDirector:
    """A session holding NSE's cookies: the API refuses a request without them."""
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    with opener.open(Request(PAGE, headers={"User-Agent": USER_AGENT}), timeout=30) as response:
        response.read(1024)
    return opener


def _download(opener: OpenerDirector, window_start: date, window_end: date) -> bytes:
    params = urlencode(
        {
            "index": "equities",
            "from_date": window_start.strftime("%d-%m-%Y"),
            "to_date": window_end.strftime("%d-%m-%Y"),
        }
    )
    request = Request(
        f"{API}?{params}",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Referer": PAGE,
        },
    )
    with opener.open(request, timeout=60) as response:
        payload: bytes = response.read()
    return payload


def land(start: date, end: date, *, root: Path = LANDING) -> list[Path]:
    """Land every quarter in [start, end] not already landed. Returns all their paths.

    A landed file is never rewritten. A quarter that ends after today is not
    landed: its answer would still grow, and an immutable file must be final.
    """
    if end < start:
        raise ValueError("end date must be on or after start date")
    root.mkdir(parents=True, exist_ok=True)
    opener: OpenerDirector | None = None
    paths = []
    for window_start, window_end in windows(start, end):
        path = landing_path(window_start, window_end, root)
        paths.append(path)
        if path.exists():
            continue
        if window_end >= datetime.now(IST).date():
            raise ValueError(f"{window_end} has not finished; land only completed windows")
        opener = opener or _opener()
        payload = _download(opener, window_start, window_end)
        json.loads(payload)  # refuse to land something that is not JSON
        partial = path.with_suffix(".partial")
        partial.write_bytes(payload)
        partial.replace(path)
    return paths


def derive(paths: list[Path]) -> tuple[list[dict[str, Any]], list[str]]:
    """Result filings from landed answers, oldest first; and warnings about the answers."""
    warnings = []
    collected: dict[tuple[str, str], dict[str, Any]] = {}
    board: dict[tuple[str, str], str] = {}
    outcome: dict[tuple[str, str], dict[str, Any]] = {}
    """Earliest same-day board-meeting outcome per (symbol, day). It often carries
    the results minutes before the results row (median 3 min in Q3 2024, 738 of
    2,056), so a result is known from whichever came first."""
    for path in paths:
        rows = json.loads(path.read_bytes())
        if len(rows) in ROUND_COUNTS:
            warnings.append(f"{path.name}: exactly {len(rows)} rows; the API may have truncated")
        window_start, window_end = (date.fromisoformat(p) for p in path.stem.split("_"))
        for row in rows:
            if row.get("desc") == BOARD_OUTCOME:
                symbol = str(row.get("symbol") or "").strip().upper()
                at = _exchange_time(row.get("exchdisstime"))
                if symbol and at:
                    key = (symbol, at[:10])
                    board[key] = min(board.get(key, at), at)
                    text = str(row.get("attchmntText") or "")
                    if (
                        RESULTS_TEXT in text.lower()
                        and window_start <= date.fromisoformat(at[:10]) <= window_end
                    ):
                        have = outcome.get(key)
                        if have is None or at < have["knowledge_time"]:
                            outcome[key] = {
                                "symbol": symbol,
                                "event_time": _exchange_time(row.get("an_dt")) or at,
                                "knowledge_time": at,
                                "results_row_time": at,
                                "details": text,
                                "attachment": str(row.get("attchmntFile") or ""),
                                "source": "NSE corporate-announcements API (board outcome)",
                                "landing": path.name,
                            }
                continue
            if row.get("desc") != SUBJECT:
                continue
            symbol = str(row.get("symbol") or "").strip().upper()
            disseminated = _exchange_time(row.get("exchdisstime"))
            if not symbol or not disseminated:
                continue
            if not window_start <= datetime.fromisoformat(disseminated).date() <= window_end:
                continue
            received = _exchange_time(row.get("an_dt")) or disseminated
            collected[(symbol, disseminated)] = {
                "symbol": symbol,
                "event_time": received,
                "knowledge_time": disseminated,
                "results_row_time": disseminated,
                "details": str(row.get("attchmntText") or ""),
                "attachment": str(row.get("attchmntFile") or ""),
                "source": "NSE corporate-announcements API",
                "landing": path.name,
            }
    have_days = {(r["symbol"], r["results_row_time"][:10]) for r in collected.values()}
    for key, row in outcome.items():
        if key not in have_days:
            collected[(row["symbol"], row["knowledge_time"])] = row
    for row in collected.values():
        earlier = board.get((row["symbol"], row["results_row_time"][:10]))
        if earlier is not None and earlier < row["knowledge_time"]:
            row["knowledge_time"] = earlier
            row["event_time"] = min(row["event_time"], earlier)
    out = sorted(collected.values(), key=lambda row: (row["knowledge_time"], row["symbol"]))
    return out, warnings


def load(path: Path = OUT) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-date", type=date.fromisoformat, default=date(2021, 7, 1))
    parser.add_argument("--to-date", type=date.fromisoformat, default=date(2024, 12, 31))
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    rows, warnings = derive(land(args.from_date, args.to_date))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    for warning in warnings:
        print(f"WARNING {warning}")
    print(f"wrote {len(rows)} NSE financial-result timestamps to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
