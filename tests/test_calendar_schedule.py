"""A calendar release the source moved shows once, at its new time (T-4345)."""

from __future__ import annotations

from eulerlab.ingest.forexfactory import Event, latest_schedule


def _event(at: str, known: str, title: str = "BOJ Policy Rate") -> Event:
    return Event(
        title=title,
        country="JPY",
        event_time=at,
        impact="High",
        forecast="",
        previous="",
        knowledge_time=known,
        receipt_time=known,
    )


def test_a_moved_release_keeps_only_its_latest_time() -> None:
    first = _event("2026-10-30T08:00:00+05:30", "2026-10-26T10:00:00+00:00")
    moved = _event("2026-10-30T08:32:00+05:30", "2026-10-29T10:00:00+00:00")
    assert latest_schedule([first, moved]) == [moved]


def test_different_releases_on_one_day_both_stay() -> None:
    rate = _event("2026-10-30T08:00:00+05:30", "2026-10-26T10:00:00+00:00")
    outlook = _event("2026-10-30T08:00:00+05:30", "2026-10-26T10:00:00+00:00", "BOJ Outlook Report")
    assert len(latest_schedule([rate, outlook])) == 2
