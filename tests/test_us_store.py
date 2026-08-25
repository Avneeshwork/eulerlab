"""The US minute reader, and the session cut that makes it usable.

Alpaca's bars carry pre- and post-market prints. Every opening-range signal in
the library reads its range off the first bars of the session, so an unfiltered
file makes an 08:01 pre-market tick the "open" — a quiet, plausible-looking
wrong answer rather than a loud one.
"""

from __future__ import annotations

from datetime import UTC, datetime

from eulerlab.intraday import us_store


def test_premarket_is_outside_the_session() -> None:
    # 12:01 UTC is 08:01 in New York during EDT — a real bar in the raw file.
    assert not us_store.in_session(datetime(2026, 8, 3, 12, 1, tzinfo=UTC))


def test_the_cash_open_is_inside() -> None:
    assert us_store.in_session(datetime(2026, 8, 3, 13, 30, tzinfo=UTC))


def test_the_close_is_exclusive() -> None:
    """16:00 belongs to the next thing, not this session."""
    assert us_store.in_session(datetime(2026, 8, 3, 19, 59, tzinfo=UTC))
    assert not us_store.in_session(datetime(2026, 8, 3, 20, 0, tzinfo=UTC))


def test_the_window_follows_daylight_saving() -> None:
    """The reason this is computed in New York rather than as a UTC offset.

    In January the cash open is 14:30 UTC, not 13:30. A fixed offset would drop
    the first hour of every winter session and still return a plausible number.
    """
    assert not us_store.in_session(datetime(2026, 1, 15, 13, 30, tzinfo=UTC))
    assert us_store.in_session(datetime(2026, 1, 15, 14, 30, tzinfo=UTC))
    assert not us_store.in_session(datetime(2026, 1, 15, 21, 0, tzinfo=UTC))


def test_month_filter_skips_files_outside_the_window() -> None:
    """Checked on the name so a 90-day scan does not fetch two years."""
    from datetime import date

    relative = "us/minute/QQQ/2026-06.jsonl.gz"
    assert us_store._in_range(relative, date(2026, 6, 1), date(2026, 8, 23))
    assert not us_store._in_range(relative, date(2026, 9, 1), date(2026, 9, 30))
    assert not us_store._in_range(relative, date(2025, 1, 1), date(2025, 3, 1))


def test_unparseable_names_are_read_rather_than_skipped() -> None:
    """A file that might hold the window is cheaper to open than a gap is to find."""
    from datetime import date

    assert us_store._in_range("us/minute/QQQ/weird.jsonl.gz", date(2026, 6, 1), date(2026, 8, 1))
