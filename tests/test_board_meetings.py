"""NSE board-meeting intimations captured into a results calendar (ADR-105)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from eulerlab.agents import brief_content
from eulerlab.ingest import board_meetings

FEED = b"""<rss version="2.0"><channel><title>NSE News - Board Meetings</title>
<item><title>NLC India Limited</title><description>NLC India Limited has informed the Exchange about Board Meeting to be held on 04-Nov-2026 to consider the Financial Results. |Meeting Date: 04-Nov-2026</description><link>https://nsearchives.nseindia.com/a.xml</link><pubDate>31-Oct-2026 19:00:08</pubDate></item>
<item><title>Denta Water and Infra Solutions Ltd.</title><description>Board Meeting Intimation |Meeting Date: 06-Nov-2026</description><link>https://nsearchives.nseindia.com/b.xml</link></item>
<item><title>No Date Limited</title><description>Something else</description></item>
</channel></rss>"""


def test_parse_reads_company_meeting_date_and_results_flag() -> None:
    rows = board_meetings.parse(FEED, {"nlc india": "NLCINDIA"}) or []
    assert [(r["company"], r["symbol"], r["meeting"], r["results"]) for r in rows] == [
        ("NLC India Limited", "NLCINDIA", "2026-11-04", True),
        ("Denta Water and Infra Solutions Ltd.", "", "2026-11-06", False),
    ]
    assert board_meetings.parse(b"<html></html>", {}) is None


def test_record_appends_only_new_and_upcoming_respects_window_and_as_of(tmp_path: Path) -> None:
    out = tmp_path / "bm.jsonl"
    rows = board_meetings.parse(FEED, {"nlc india": "NLCINDIA"}) or []
    assert board_meetings.record(rows, "2026-10-31T19:30:00+05:30", out) == 2
    assert board_meetings.record(rows, "2026-11-01T19:30:00+05:30", out) == 0
    held = board_meetings.held(out)
    assert all(r["event_time"] == r["meeting"] and r["knowledge_time"] for r in held)
    soon = board_meetings.upcoming(date(2026, 11, 1), rows=held)
    assert [r["symbol"] for r in soon] == ["NLCINDIA"]  # the other is not a results meeting
    assert board_meetings.upcoming(date(2026, 11, 1), rows=held, as_of="2026-10-30") == []
    assert board_meetings.upcoming(date(2026, 11, 5), rows=held) == []


def test_the_brief_names_held_companies_with_results_due() -> None:
    results = [{"company": "NLC India Limited", "symbol": "NLCINDIA", "meeting": "2026-11-04"}]
    out = brief_content.coming_up(
        today=date(2026, 11, 2),
        ctx={},
        events=[],
        reports={},
        held={"NLCINDIA"},
        results=results,
        results_since="2026-10-31",
    )
    item = out["items"][0]
    assert item["what"] == "Results due: 1 companies, including yours: NLCINDIA"
    assert any("before 2026-10-31" in n for n in out["not_covered"])
