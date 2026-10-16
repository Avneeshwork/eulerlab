"""Capture NSE financial-result announcement timestamps for research."""

from __future__ import annotations

import argparse
import json
from calendar import monthrange
from collections.abc import Iterator
from datetime import date, datetime
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener
from zoneinfo import ZoneInfo

OUT = Path("data/derived/nse_earnings_announcements.jsonl")
PAGE = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
API = "https://www.nseindia.com/api/corporate-announcements"
IST = ZoneInfo("Asia/Kolkata")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
)


def _exchange_time(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)
    except ValueError:
        return None
    return parsed.isoformat()


def _windows(start: date, end: date) -> Iterator[tuple[date, date]]:
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        month = ((cursor.month - 1) // 3 + 1) * 3
        last_month = date(cursor.year, month, monthrange(cursor.year, month)[1])
        window_end = min(last_month, end)
        yield max(cursor, start), window_end
        cursor = date(cursor.year + 1, 1, 1) if month == 12 else date(cursor.year, month + 1, 1)


def fetch(start: date, end: date) -> list[dict[str, str]]:
    """Fetch only official financial-results rows, retaining exchange timestamps."""
    if end < start:
        raise ValueError("end date must be on or after start date")
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    page_request = Request(PAGE, headers={"User-Agent": USER_AGENT})
    with opener.open(page_request, timeout=30) as response:
        response.read(1024)

    collected: dict[tuple[str, str], dict[str, str]] = {}
    for window_start, window_end in _windows(start, end):
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
            rows = json.loads(response.read())
        for row in rows:
            if row.get("desc") != "Financial Result Updates":
                continue
            symbol = str(row.get("symbol") or "").strip().upper()
            received = _exchange_time(row.get("an_dt"))
            disseminated = _exchange_time(row.get("exchdisstime"))
            if not symbol or not disseminated:
                continue
            published = datetime.fromisoformat(disseminated)
            if not start <= published.date() <= end:
                continue
            key = (symbol, disseminated)
            collected[key] = {
                "symbol": symbol,
                "subject": str(row.get("desc") or ""),
                "received_at": received or disseminated,
                "disseminated_at": disseminated,
                "details": str(row.get("attchmntText") or ""),
                "attachment": str(row.get("attchmntFile") or ""),
                "source": "NSE corporate-announcements API",
            }
    return sorted(collected.values(), key=lambda row: row["disseminated_at"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-date", type=date.fromisoformat, default=date(2024, 1, 1))
    parser.add_argument("--to-date", type=date.fromisoformat, default=date(2024, 11, 30))
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    rows = fetch(args.from_date, args.to_date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    print(f"wrote {len(rows)} NSE financial-result timestamps to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
