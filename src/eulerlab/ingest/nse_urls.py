"""NSE archive URLs for both bhavcopy formats.

NSE changed its end-of-day file format mid-2024. An 11-year backfill therefore
spans two schemas at two URL patterns:

* **UDiFF** — 34 columns, one schema for cash and derivatives. Confirmed
  available back to 2024-01-02.
* **Legacy** — 13 columns (cash) and 15 (derivatives). Confirmed available for
  2015; stops somewhere between 2024-06-03 and 2024-09-02.

Both are documented with fetch dates in
``docs/RESEARCH/002-nse-eod-sources-and-schemas.md``.

# ASSUMPTION: the exact cutover date is inferred from probing, not from the NSE
# circular (docs/ASSUMPTIONS.md A-009). Nothing here hardcodes it as a
# boundary: `candidates()` returns the likely format first and the other as a
# fallback, so a wrong guess costs one extra request, never a missing day.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

ARCHIVE_HOST = "https://nsearchives.nseindia.com"

# Locale-independent. strftime("%b") would follow the machine's locale and
# silently produce the wrong URL on a non-English system.
MONTH_ABBR = (
    "JAN",
    "FEB",
    "MAR",
    "APR",
    "MAY",
    "JUN",
    "JUL",
    "AUG",
    "SEP",
    "OCT",
    "NOV",
    "DEC",
)

# First date for which the UDiFF format is confirmed present.
UDIFF_CONFIRMED_FROM = date(2024, 1, 2)


class Segment(StrEnum):
    """Which market's end-of-day file."""

    CM = "cm"
    """Cash market — equities."""

    FO = "fo"
    """Futures and options."""


class FileFormat(StrEnum):
    UDIFF = "udiff"
    LEGACY = "legacy"


def _legacy_directory(segment: Segment) -> str:
    return "EQUITIES" if segment is Segment.CM else "DERIVATIVES"


def url_for(trade_date: date, segment: Segment, file_format: FileFormat) -> str:
    """Build the archive URL for one date, segment and format."""
    if file_format is FileFormat.UDIFF:
        stamp = f"{trade_date.year:04d}{trade_date.month:02d}{trade_date.day:02d}"
        tag = segment.name  # "CM" / "FO"
        return f"{ARCHIVE_HOST}/content/{segment.value}/BhavCopy_NSE_{tag}_0_0_0_{stamp}_F_0000.csv.zip"

    month = MONTH_ABBR[trade_date.month - 1]
    return (
        f"{ARCHIVE_HOST}/content/historical/{_legacy_directory(segment)}"
        f"/{trade_date.year:04d}/{month}"
        f"/{segment.value}{trade_date.day:02d}{month}{trade_date.year:04d}bhav.csv.zip"
    )


def candidates(trade_date: date, segment: Segment) -> tuple[tuple[FileFormat, str], ...]:
    """Formats to try for this date, most likely first.

    Both are always returned. Around the mid-2024 changeover we do not know
    precisely which applies, and one wasted request is far cheaper than
    recording a trading day as missing.
    """
    order = (
        (FileFormat.UDIFF, FileFormat.LEGACY)
        if trade_date >= UDIFF_CONFIRMED_FROM
        else (FileFormat.LEGACY, FileFormat.UDIFF)
    )
    return tuple((fmt, url_for(trade_date, segment, fmt)) for fmt in order)
