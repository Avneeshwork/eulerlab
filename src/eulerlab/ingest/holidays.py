"""NSE trading holidays — corroboration, not a source of truth.

This exists only to upgrade "both segments absent, so probably a holiday" into
"both segments absent, and NSE says it was a holiday". It is deliberately
best-effort: when the list is unavailable the ingest still runs and simply
reports its closures as *likely* rather than *confirmed*.

**Known limitation:** NSE's endpoint returns the current year only. For an
11-year backfill most historical closures cannot be corroborated this way, and
the report says so rather than implying more certainty than it has.
# ASSUMPTION: see docs/ASSUMPTIONS.md A-012.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path

HOLIDAY_URL = "https://www.nseindia.com/api/holiday-master?type=trading"
CACHE_NAME = "nse_holidays.json"

# NSE returns e.g. "15-Jan-2026". Locale-independent parse.
_MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


def parse_nse_date(text: str) -> date | None:
    """Parse NSE's ``DD-Mon-YYYY``. Returns None rather than raising.

    A single unparseable row must not take down an ingest run whose real job
    is downloading files.
    """
    parts = text.strip().split("-")
    if len(parts) != 3:
        return None
    day, month_name, year = parts
    month = _MONTHS.get(month_name[:3].title())
    if month is None or not day.isdigit() or not year.isdigit():
        return None
    try:
        return date(int(year), month, int(day))
    except ValueError:
        return None


def extract(payload: Mapping[str, object], segment_key: str = "CM") -> frozenset[date]:
    """Pull one segment's holiday dates out of NSE's response shape."""
    rows = payload.get(segment_key)
    if not isinstance(rows, list):
        return frozenset()
    found: set[date] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get("tradingDate")
        if isinstance(raw, str):
            parsed = parse_nse_date(raw)
            if parsed is not None:
                found.add(parsed)
    return frozenset(found)


def load_holidays(cache_dir: Path) -> frozenset[date]:
    """Read the cached holiday list. Empty set when there is none.

    Deliberately does not fetch. Ingest runs are already making thousands of
    requests; refreshing reference data is a separate, explicit action
    (``refresh_holidays``) so a backfill never silently depends on a live API.
    """
    cache = cache_dir / CACHE_NAME
    if not cache.exists():
        return frozenset()
    try:
        payload = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return frozenset()
    if not isinstance(payload, dict):
        return frozenset()
    return extract(payload)


def save_holidays(cache_dir: Path, payload: bytes) -> Path:
    """Cache a raw holiday response, stamped with when we fetched it."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / CACHE_NAME
    cache.write_bytes(payload)
    stamp = cache_dir / "nse_holidays.fetched_at"
    stamp.write_text(datetime.now().astimezone().isoformat(), encoding="utf-8")
    return cache
