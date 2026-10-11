"""Minute bars: fetch only days not held, and judge the Kite token by 06:00 IST.

T-4036. Every run re-fetched the whole year because its windows were cut from a
start that moves daily (`2898 total, 2898 to fetch`, 2026-10-08).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from eulerlab.broker.kite_session import Session, expires_at, is_fresh
from eulerlab.ingest.backfill_minute import last_complete_session
from eulerlab.ingest.kite_minute import uncovered_chunks


def _spans(held: list[tuple[date, date]], start: date, end: date) -> list[tuple[date, date]]:
    return [(c.start, c.end) for c in uncovered_chunks("ACME", 1, start, end, held)]


def test_a_fully_held_range_fetches_nothing() -> None:
    held = [(date(2026, 8, 3), date(2026, 10, 1)), (date(2026, 10, 2), date(2026, 10, 8))]
    assert _spans(held, date(2026, 8, 3), date(2026, 10, 8)) == []


def test_only_the_new_session_is_fetched() -> None:
    held = [(date(2025, 10, 8), date(2026, 10, 8))]
    assert _spans(held, date(2025, 10, 9), date(2026, 10, 9)) == [
        (date(2026, 10, 9), date(2026, 10, 9))
    ]


def test_a_weekend_does_not_split_a_gap_and_is_never_fetched_alone() -> None:
    held = [(date(2026, 10, 1), date(2026, 10, 8))]
    # Fri 9 Oct and Mon 12 Oct missing: one chunk, across the weekend.
    assert _spans(held, date(2026, 10, 1), date(2026, 10, 12)) == [
        (date(2026, 10, 9), date(2026, 10, 12))
    ]
    # Only Sat-Sun uncovered: nothing to fetch.
    assert _spans(held, date(2026, 10, 1), date(2026, 10, 4)) == []
    held_through_friday = [(date(2026, 10, 1), date(2026, 10, 9))]
    assert _spans(held_through_friday, date(2026, 10, 1), date(2026, 10, 11)) == []


def test_a_new_symbol_gets_the_whole_window_in_sixty_day_chunks() -> None:
    spans = _spans([], date(2026, 1, 1), date(2026, 6, 30))
    assert spans[0][0] == date(2026, 1, 1) and spans[-1][1] == date(2026, 6, 30)
    assert all((b - a).days < 60 for a, b in spans)


def test_today_is_fetched_only_after_the_close() -> None:
    before = datetime(2026, 10, 9, 9, 0, tzinfo=UTC)  # 14:30 IST
    after = datetime(2026, 10, 9, 10, 30, tzinfo=UTC)  # 16:00 IST
    assert last_complete_session(before) == date(2026, 10, 8)
    assert last_complete_session(after) == date(2026, 10, 9)


def _minted(iso: str) -> Session:
    return Session(access_token="t", user_id="u", minted_at=iso)


def test_a_token_lasts_until_0600_ist_not_until_utc_midnight() -> None:
    evening = _minted("2026-10-09T12:43:00+00:00")  # 18:13 IST on the 9th
    assert is_fresh(evening, datetime(2026, 10, 9, 23, 0, tzinfo=UTC))  # 04:30 IST, 10th
    assert is_fresh(evening, datetime(2026, 10, 10, 0, 15, tzinfo=UTC))  # 05:45 IST
    assert not is_fresh(evening, datetime(2026, 10, 10, 0, 45, tzinfo=UTC))  # 06:15 IST
    assert expires_at(evening) == datetime(2026, 10, 10, 0, 30, tzinfo=UTC)


def test_a_token_minted_before_0600_dies_at_0600_the_same_day() -> None:
    early = _minted("2026-10-09T23:30:00+00:00")  # 05:00 IST on the 10th
    assert is_fresh(early, datetime(2026, 10, 10, 0, 15, tzinfo=UTC))
    assert not is_fresh(early, datetime(2026, 10, 10, 1, 0, tzinfo=UTC))
    assert not is_fresh(None) and not is_fresh(_minted("not a date"))
