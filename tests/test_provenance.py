"""The download timestamp is not the knowledge time.

Conflating the two is the single most destructive thing that could happen to
this project's backtests, and it is invisible when it happens: the frame just
comes back empty, or worse, comes back full because someone "fixed" the filter.
"""

from __future__ import annotations

import json
from datetime import datetime, time, timedelta
from pathlib import Path

import pytest

from eulerlab.bitemporal.provenance import (
    IST,
    PUBLICATION_TIME_IST,
    Provenance,
    Vintage,
    from_manifest_row,
    knowable_at,
    read_manifest,
    session_close,
)


def _row(
    trade_date: str = "2015-01-05", segment: str = "cm", fetched: str = "2026-08-18T02:27:17+00:00"
) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "segment": segment,
        "path": f"{segment}/x.zip",
        "knowledge_time": fetched,
    }


# --- the distinction itself ---


def test_knowledge_time_comes_from_the_trade_date_not_the_download() -> None:
    """The whole point. A 2015 file downloaded in 2026 was knowable in 2015."""
    p = from_manifest_row(_row())
    assert p.knowledge_time.year == 2015
    assert p.receipt_time.year == 2026


def test_a_backfilled_file_is_knowable_the_evening_it_traded() -> None:
    p = from_manifest_row(_row(trade_date="2015-01-05"))
    assert p.knowledge_time == datetime(2015, 1, 5, 20, 0, tzinfo=IST)


def test_the_event_time_is_the_session_close_not_midnight() -> None:
    """A bhavcopy describes a session, so the event is when the session ended."""
    assert session_close("2015-01-05") == datetime(2015, 1, 5, 15, 30, tzinfo=IST)


def test_knowledge_time_is_never_before_event_time() -> None:
    """Publication follows the close. If this inverts, Record would reject it."""
    p = from_manifest_row(_row())
    assert p.knowledge_time > p.event_time


# --- vintage: what we can and cannot claim about content ---


def test_a_backfilled_file_is_not_claimed_as_point_in_time() -> None:
    """We hold today's version. Saying otherwise would be a quiet lie."""
    assert from_manifest_row(_row()).vintage is Vintage.FINAL


def test_a_same_day_capture_is_point_in_time() -> None:
    p = from_manifest_row(_row(trade_date="2026-08-18", fetched="2026-08-18T21:00:00+05:30"))
    assert p.vintage is Vintage.LIVE


def test_the_live_window_has_an_edge_and_it_is_enforced() -> None:
    late = from_manifest_row(_row(trade_date="2026-08-01", fetched="2026-08-10T20:00:00+05:30"))
    assert late.vintage is Vintage.FINAL


# --- the guard that caught a wrong assumption on real data ---


def test_fetching_before_publication_is_rejected_not_absorbed() -> None:
    """This fired on the real manifest and exposed a wrong publication hour.

    A file cannot be fetched before it exists. If that appears to have
    happened, either the publication assumption or a clock is wrong, and
    guessing which would bake the error in permanently.
    """
    with pytest.raises(ValueError, match="before it was publishable"):
        from_manifest_row(_row(trade_date="2026-08-18", fetched="2026-08-18T10:00:00+05:30"))


def test_the_participant_oi_hour_is_bounded_by_the_measurement_that_set_it() -> None:
    """19:09 IST is an observed same-day fetch, not a rounded guess.

    If someone later relaxes it past the evidence, that is a leak, so the
    bound is asserted rather than trusted to a comment.
    """
    assert PUBLICATION_TIME_IST["participant_oi"] <= time(19, 9)


def test_an_unknown_segment_falls_back_to_the_late_default() -> None:
    """A new feed must not silently inherit an early, unsafe hour."""
    assert knowable_at("2026-08-18", "a_feed_we_have_not_seen").time() == time(20, 0)


# --- reading the real manifest shape ---


def test_a_naive_download_timestamp_is_read_as_utc_not_local() -> None:
    """Older manifest rows may lack an offset. Guessing local time would shift
    the receipt by five and a half hours."""
    p = from_manifest_row(_row(fetched="2026-08-18T02:27:17"))
    assert p.receipt_time.utcoffset() == timedelta(0)


def test_read_manifest_parses_a_real_shaped_file(tmp_path: Path) -> None:
    path = tmp_path / "manifest.jsonl"
    path.write_text(
        "\n".join(json.dumps(_row(trade_date=d)) for d in ("2015-01-05", "2015-01-06")) + "\n",
        encoding="utf-8",
    )
    records = list(read_manifest(path))
    assert [r.trade_date for r in records] == ["2015-01-05", "2015-01-06"]
    assert all(isinstance(r, Provenance) for r in records)


def test_blank_lines_do_not_become_records(tmp_path: Path) -> None:
    path = tmp_path / "manifest.jsonl"
    path.write_text(json.dumps(_row()) + "\n\n", encoding="utf-8")
    assert len(list(read_manifest(path))) == 1
