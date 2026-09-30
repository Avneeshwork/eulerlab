"""FMP news ingest — the parts that hold without a key."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from eulerlab.ingest import fmp


def _row(title: str = "Fed holds rates", url: str = "https://x.com/a") -> dict[str, object]:
    return {
        "title": title,
        "publishedDate": "2026-08-22 14:30:00",
        "publisher": "Reuters",
        "url": url,
        "symbol": "AAPL",
        "text": "body",
        "site": "reuters.com",
    }


def test_knowledge_time_is_the_fetch_not_the_publish() -> None:
    """The whole point of the bitemporal contract.

    Backdating knowledge to the publish stamp would let a backtest read a story
    at the moment it was written rather than the moment we pulled it, which is
    the exact leak `as_of` exists to prevent.
    """
    now = datetime(2026, 8, 22, 18, 0, tzinfo=UTC)
    article = fmp.to_articles([_row()], "general", now=now)[0]
    assert article.event_time.startswith("2026-08-22T14:30")
    assert article.knowledge_time == now.isoformat()
    assert article.knowledge_time > article.event_time


def test_rows_without_a_title_or_date_are_dropped_not_defaulted() -> None:
    """An absent row shows up in the count. An invented one does not."""
    rows: list[dict[str, object]] = [
        _row(),
        {"title": "", "publishedDate": "2026-08-22 14:30:00"},
        {"title": "x"},
    ]
    assert len(fmp.to_articles(rows, "general")) == 1


def test_a_restated_story_keeps_the_moment_we_first_saw_it(tmp_path: Path) -> None:
    """Re-fetching must not move knowledge_time forward.

    A story seen at 09:00 and again at 15:00 was knowable at 09:00. Letting the
    later fetch overwrite would quietly delay every signal built on it.
    """
    early = datetime(2026, 8, 22, 9, 0, tzinfo=UTC)
    late = datetime(2026, 8, 22, 15, 0, tzinfo=UTC)

    first = fmp.to_articles([_row()], "general", now=early)
    path = fmp.day_path("general", "2026-08-22", root=tmp_path)
    fmp._merge(path, [a.to_row() for a in first])

    second = fmp.to_articles([_row(title="Fed holds rates (updated)")], "general", now=late)
    total, new = fmp._merge(path, [a.to_row() for a in second])

    assert (total, new) == (1, 0), "same URL is the same story"
    landed = fmp.read_all(root=tmp_path, allow_cloud=False)
    assert landed[0]["knowledge_time"] == early.isoformat()
    assert landed[0]["title"] == "Fed holds rates (updated)", "later content wins"


def test_two_stories_without_urls_do_not_collide(tmp_path: Path) -> None:
    """The URL is the only unique field; the fallback must stay distinct."""
    rows = [_row(title="A", url=""), _row(title="B", url="")]
    articles = fmp.to_articles(rows, "general")
    assert len({a.key for a in articles}) == 2


def test_a_missing_key_raises_rather_than_reporting_no_news(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty would read as "nothing happened today", which is a different and
    much worse claim than "we never asked"."""
    monkeypatch.chdir(tmp_path)  # no .env here
    monkeypatch.delenv(fmp.KEY_VAR, raising=False)
    assert not fmp.key_present()
    with pytest.raises(fmp.MissingKey):
        fmp.api_key()


def test_the_probe_list_stays_within_a_fraction_of_the_daily_budget() -> None:
    """A probe that cost most of the day's 250 calls would be unusable."""
    assert len(fmp.PROBE_ENDPOINTS) < fmp.FREE_DAILY_CALLS // 5


def test_press_releases_never_merge_into_general_news() -> None:
    """A company's own statement and a wire story are different kinds of claim.

    They land in separate trees so nothing downstream can treat one as the
    other by accident.
    """
    a = fmp.day_path("press", "2026-08-22")
    b = fmp.day_path("general", "2026-08-22")
    assert a != b and a.parent != b.parent
