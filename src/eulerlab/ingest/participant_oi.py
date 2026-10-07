"""Backfill NSE's participant-wise F&O open interest.

One CSV per trading day, splitting open interest by *who holds it* — Client,
DII, FII, Pro — across index futures, stock futures, and index and stock
options, long and short separately.

Of everything surveyed in research note 004 this is the most valuable free
dataset available: positioning is a cause of price movement rather than a
lagging summary of it, and unlike FII/DII cash flow it is genuinely historical.

Reuses the bhavcopy downloader's machinery unchanged — the same `Fetcher`
(rate-limited, bounded retries, never HEAD) and the same append-only manifest
for idempotency and resumability.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date

from eulerlab.ingest.fetch import Fetcher, Outcome
from eulerlab.ingest.landing import Landing

SEGMENT = "participant_oi"
URL = "https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{stamp}.csv"


def url_for(trade_date: date) -> str:
    return URL.format(stamp=f"{trade_date.day:02d}{trade_date.month:02d}{trade_date.year:04d}")


@dataclass(frozen=True)
class OiDay:
    trade_date: date
    rows: int
    client_types: frozenset[str]

    @property
    def looks_sane(self) -> bool:
        """The file should name at least Client, FII and DII.

        A truncated or error page would parse as CSV but carry none of these,
        which is exactly the kind of plausible-looking garbage that a row count
        alone would not catch.
        """
        return {"Client", "FII", "DII"} <= self.client_types


def parse(payload: bytes) -> OiDay | None:
    """Read the report. Returns None when it is not a participant-OI file.

    The real file has a title line above the header, so the header is found
    rather than assumed to be row one.
    """
    text = payload.decode("utf-8", errors="replace")
    lines = text.splitlines()
    header_index = next(
        (i for i, line in enumerate(lines) if line.lstrip().startswith("Client Type")), None
    )
    if header_index is None:
        return None

    reader = csv.DictReader(io.StringIO("\n".join(lines[header_index:])))
    found: set[str] = set()
    count = 0
    for row in reader:
        name = (row.get("Client Type") or "").strip()
        if name:
            found.add(name)
            count += 1
    return OiDay(trade_date=date.today(), rows=count, client_types=frozenset(found))  # noqa: DTZ011


def fetch_day(fetcher: Fetcher, landing: Landing, trade_date: date) -> str:
    """Returns one of: downloaded, skipped, absent, failed, malformed."""
    if landing.has(trade_date, SEGMENT):
        return "skipped"

    result = fetcher.get(url_for(trade_date))
    if result.outcome is Outcome.ABSENT:
        return "absent"
    if result.outcome is Outcome.FAILED or result.payload is None:
        return "failed"

    parsed = parse(result.payload)
    if parsed is None or not parsed.looks_sane:
        # Do not land something that parses but is not the report we asked for.
        return "malformed"

    landing.write(
        trade_date=trade_date,
        segment=SEGMENT,
        file_format="csv",
        url=url_for(trade_date),
        payload=result.payload,
        rows=parsed.rows,
        inner_name=f"fao_participant_oi_{trade_date.isoformat()}.csv",
        suffix="csv",
    )
    return "downloaded"
