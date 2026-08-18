"""URL construction for both bhavcopy formats.

The URLs below were confirmed by actual download on 2026-08-18 (research note
002). If NSE changes a path these tests will keep passing while the downloader
starts returning 404s — that is what the ingest report's failure counts are
for. These tests guard against *us* breaking the construction, not against NSE
moving the goalposts.
"""

from __future__ import annotations

from datetime import date

from eulerlab.ingest.nse_urls import (
    FileFormat,
    Segment,
    candidates,
    url_for,
)


def test_udiff_equity_url_matches_the_verified_one() -> None:
    assert url_for(date(2026, 8, 14), Segment.CM, FileFormat.UDIFF) == (
        "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_20260814_F_0000.csv.zip"
    )


def test_udiff_fo_url_matches_the_verified_one() -> None:
    assert url_for(date(2026, 8, 14), Segment.FO, FileFormat.UDIFF) == (
        "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_20260814_F_0000.csv.zip"
    )


def test_legacy_equity_url_matches_the_verified_one() -> None:
    assert url_for(date(2015, 1, 2), Segment.CM, FileFormat.LEGACY) == (
        "https://nsearchives.nseindia.com/content/historical/EQUITIES/2015/JAN/"
        "cm02JAN2015bhav.csv.zip"
    )


def test_legacy_fo_url_uses_the_derivatives_directory() -> None:
    assert url_for(date(2015, 1, 2), Segment.FO, FileFormat.LEGACY) == (
        "https://nsearchives.nseindia.com/content/historical/DERIVATIVES/2015/JAN/"
        "fo02JAN2015bhav.csv.zip"
    )


def test_legacy_day_is_zero_padded() -> None:
    assert "cm02JAN2015bhav" in url_for(date(2015, 1, 2), Segment.CM, FileFormat.LEGACY)


def test_month_names_are_locale_independent() -> None:
    # strftime("%b") would follow the machine locale and break the URL abroad.
    for month, abbr in enumerate(
        ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"],
        start=1,
    ):
        url = url_for(date(2015, month, 1), Segment.CM, FileFormat.LEGACY)
        assert f"/{abbr}/" in url
        assert f"01{abbr}2015" in url


def test_old_dates_try_legacy_first() -> None:
    order = [fmt for fmt, _ in candidates(date(2015, 6, 1), Segment.CM)]
    assert order == [FileFormat.LEGACY, FileFormat.UDIFF]


def test_recent_dates_try_udiff_first() -> None:
    order = [fmt for fmt, _ in candidates(date(2026, 1, 5), Segment.CM)]
    assert order == [FileFormat.UDIFF, FileFormat.LEGACY]


def test_both_formats_are_always_offered() -> None:
    # The cutover date is inferred, not sourced (A-009). Never let a wrong
    # guess turn a present trading day into a missing one.
    for day in (date(2024, 3, 1), date(2024, 8, 1), date(2015, 1, 2), date(2026, 8, 14)):
        assert len(candidates(day, Segment.FO)) == 2
