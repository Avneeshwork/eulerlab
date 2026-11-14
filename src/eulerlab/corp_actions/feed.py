"""Ingest the NSE corporate-actions feed into the immutable landing zone.

Endpoint verified in research note 008:

    nseindia.com/api/corporates-corporateActions
        ?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY

Two things were unverified there and are measured here instead:

**How far back it reaches.** A 2005-2010 probe returned 8,430 rows, so the
feed is deeper than our own price history (2015-). Nothing before 2015 is
useful to us — there is no bhavcopy to adjust — so the backfill starts there.

**Whether the date parameters are honoured.** They are: a 2020-only request
returned only 2020 rows (min/max exDate both inside the window). This matters
because a sibling endpoint, the FII/DII flow feed surveyed in research note
004, silently ignores its date parameters and always returns the same fixed
window — a mistake worth naming so it is not repeated here without checking.

**No pagination limit was hit.** The full 2015 to today span returned 25,644
rows in one request, 7.9 MB. So the backfill is one request per year, not one
per day — a corporate action has no single "trade date" the way a bhavcopy
row does, so records are landed in yearly buckets keyed by 1 January of the
year, using the same `Landing` used for everything else. This is a label of
convenience for the manifest's `(trade_date, segment)` key, not a claim about
when anything in the file happened; every row inside carries its own `exDate`.
"""

from __future__ import annotations

import json
from datetime import date

from eulerlab.ingest.fetch import Fetcher, Outcome
from eulerlab.ingest.landing import Landing
from eulerlab.paths import data_path

SEGMENT = "corp_actions"
URL = (
    "https://www.nseindia.com/api/corporates-corporateActions"
    "?index=equities&from_date={frm}&to_date={to}"
)

FIRST_YEAR = 2015
"""Nothing earlier is useful: there is no bhavcopy before this to adjust."""


def url_for_year(year: int) -> str:
    frm = date(year, 1, 1).strftime("%d-%m-%Y")
    to = date(year, 12, 31).strftime("%d-%m-%Y")
    return URL.format(frm=frm, to=to)


def fetch_year(fetcher: Fetcher, landing: Landing, year: int) -> str:
    """Returns one of: downloaded, skipped, absent, failed, malformed."""
    marker = date(year, 1, 1)
    if landing.has(marker, SEGMENT):
        return "skipped"

    result = fetcher.get(url_for_year(year))
    if result.outcome is Outcome.ABSENT:
        return "absent"
    if result.outcome is Outcome.FAILED or result.payload is None:
        return "failed"

    text = result.payload.decode("utf-8", errors="replace").strip()
    if not (text.startswith("[") and text.endswith("]")):
        # Not JSON, or an HTML error page NSE serves as if it were a normal
        # response. Landing it would make a future rebuild trust garbage.
        return "malformed"

    try:
        rows = json.loads(text)
    except json.JSONDecodeError:
        return "malformed"
    if not isinstance(rows, list):
        return "malformed"

    landing.write(
        trade_date=marker,
        segment=SEGMENT,
        file_format="json",
        url=url_for_year(year),
        payload=result.payload,
        rows=len(rows),
        inner_name=f"corporate_actions_{year}.json",
        suffix="json",
    )
    return "downloaded"


def refresh(fetcher: Fetcher, landing: Landing, today: date) -> dict[int, str]:
    """Land this year's list again, keyed by `today` (T-4615).

    `fetch_year` lands a year once, under 1 January, and never asks again, so
    the 2026 list fetched on 2026-08-19 never learned of a later action and
    the factors went stale. The weekly job lands the current year under the
    run's date; in January, the year just ended gets one last list under
    31 December. The factor build reads only each year's latest list."""
    out: dict[int, str] = {}
    targets = [(today.year, today)]
    if today.month == 1:
        targets.insert(0, (today.year - 1, date(today.year - 1, 12, 31)))
    for year, marker in targets:
        out[year] = _land_list(fetcher, landing, year, marker)
    return out


def _land_list(fetcher: Fetcher, landing: Landing, year: int, marker: date) -> str:
    if landing.has(marker, SEGMENT):
        return "skipped"
    result = fetcher.get(url_for_year(year))
    if result.outcome is Outcome.ABSENT:
        return "absent"
    if result.outcome is Outcome.FAILED or result.payload is None:
        return "failed"
    text = result.payload.decode("utf-8", errors="replace").strip()
    try:
        rows = json.loads(text) if text.startswith("[") else None
    except json.JSONDecodeError:
        rows = None
    if not isinstance(rows, list) or not rows:
        return "malformed"
    landing.write(
        trade_date=marker,
        segment=SEGMENT,
        file_format="json",
        url=url_for_year(year),
        payload=result.payload,
        rows=len(rows),
        inner_name=f"corporate_actions_{year}.json",
        suffix="json",
    )
    return "downloaded"


def backfill(
    fetcher: Fetcher, landing: Landing, *, from_year: int = FIRST_YEAR, to_year: int | None = None
) -> dict[str, int]:
    """Land one file per year. Idempotent: an already-landed year is skipped."""
    last = to_year or date.today().year  # noqa: DTZ011 - a run date, not a knowledge time
    counts: dict[str, int] = {}
    for year in range(from_year, last + 1):
        outcome = fetch_year(fetcher, landing, year)
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts


def main() -> int:
    import argparse

    from eulerlab.ingest.fetch import UrllibTransport

    parser = argparse.ArgumentParser(description="Backfill NSE corporate actions.")
    parser.add_argument("--from-year", type=int, default=FIRST_YEAR)
    parser.add_argument("--to-year", type=int, default=None)
    parser.add_argument("--landing", default=str(data_path("landing/nse")))
    parser.add_argument(
        "--refresh", action="store_true", help="land this year's list again (weekly job)"
    )
    args = parser.parse_args()

    from pathlib import Path

    transport = UrllibTransport()
    transport.establish_session()
    fetcher = Fetcher(transport)
    landing = Landing(Path(args.landing))

    if args.refresh:
        from eulerlab.ingest.nse_eod import today_ist

        done = refresh(fetcher, landing, today_ist())
        for year, outcome in done.items():
            print(f"{year}: {outcome}")
        return 0 if all(o in ("downloaded", "skipped") for o in done.values()) else 1
    counts = backfill(fetcher, landing, from_year=args.from_year, to_year=args.to_year)
    for outcome, n in sorted(counts.items()):
        print(f"{outcome}: {n}")
    return 0 if counts.get("failed", 0) == 0 and counts.get("malformed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
