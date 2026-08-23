"""Google News ingest — query construction, relevance scoring, and merging."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from eulerlab.ingest import news


def _rss(*items: tuple[str, str, str]) -> bytes:
    """A feed body. Each item is (title, guid, publisher)."""
    body = "".join(
        f"<item><title>{t}</title><link>https://x/{g}</link>"
        f"<guid>{g}</guid><pubDate>Fri, 21 Aug 2026 11:07:00 GMT</pubDate>"
        f"<source url='https://p'>{p}</source></item>"
        for t, g, p in items
    )
    return f"<rss><channel><title>feed</title>{body}</channel></rss>".encode()


def test_query_form_differs_by_asset_class() -> None:
    """A pair ticker is not a phrase anyone writes.

    "EURUSD" appears in no headline; "EUR USD" does. Same for BTCUSDT, whose
    quote leg is an artefact of the exchange, not part of the story.
    """
    assert news.query_for("RELIANCE", "equity").text == "RELIANCE share price NSE"
    assert news.query_for("EURUSD", "fx").text == "EUR USD forex"
    assert news.query_for("BTCUSDT", "crypto").text == "BTC crypto price"
    assert news.query_for("BTCUSD", "crypto").text == "BTC crypto price"


def test_a_pair_is_matched_whole_never_by_its_legs() -> None:
    """The scoring bug this rule exists to prevent.

    "EUR/USD and GBP/USD Outlook" contains both legs of EUR/GBP and is not a
    EUR/GBP story. Splitting pair names would score it as one, inflating the
    match rate exactly where it is least deserved.
    """
    assert news.name_tokens("EUR/GBP") == ("eur/gbp",)

    query = news.query_for("EURGBP", "fx")
    names = {"EURGBP": "EUR/GBP"}
    items = news.parse_feed(
        _rss(
            ("EUR/USD and GBP/USD Outlook - FX", "a", "FX"),
            ("EUR/GBP: COT Data Favours the Pound - FX", "b", "FX"),
        ),
        query,
        names,
    )
    assert [i.matched for i in items] == [False, True]


def test_knowledge_time_is_the_fetch_not_the_publish() -> None:
    """Backdating knowledge to the publish stamp would let a backtest read a
    story hours before we actually had it."""
    now = datetime(2026, 8, 21, 18, 0, tzinfo=UTC)
    item = news.parse_feed(
        _rss(("A story", "g1", "Reuters")), news.query_for("X", "equity"), {}, now=now
    )[0]
    assert item.event_time.startswith("2026-08-21T11:07")
    assert item.knowledge_time == now.isoformat()
    assert item.knowledge_time > item.event_time


def test_the_publisher_suffix_is_trimmed_from_the_headline() -> None:
    """Google formats titles as "Headline - Publisher"; keeping it would make
    the same story look different across sources."""
    item = news.parse_feed(
        _rss(("Fed holds - Reuters", "g1", "Reuters")), news.query_for("X", "equity"), {}
    )[0]
    assert item.title == "Fed holds"
    assert item.publisher == "Reuters"


def test_one_story_under_two_tickers_keeps_both(tmp_path: Path) -> None:
    """A sector piece names four banks. Overwriting would unlink it from three.

    The first sighting's knowledge_time must also survive: the story was
    knowable then, whichever ticker surfaced it second.
    """
    early = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
    late = datetime(2026, 8, 21, 15, 0, tzinfo=UTC)
    feed = _rss(("Banks rally - ET", "shared", "ET"))
    path = news.day_path("equity", "2026-08-21", root=tmp_path)

    first = news.parse_feed(feed, news.query_for("HDFCBANK", "equity"), {}, now=early)
    news._merge(path, [i.to_row() for i in first])
    second = news.parse_feed(feed, news.query_for("ICICIBANK", "equity"), {}, now=late)
    total, new = news._merge(path, [i.to_row() for i in second])

    assert (total, new) == (1, 0)
    row = news.read_all(asset_class="equity", root=tmp_path, allow_cloud=False)[0]
    assert row["symbols"] == ["HDFCBANK", "ICICIBANK"]
    assert row["knowledge_time"] == early.isoformat()


def test_an_unreachable_symbol_is_named_not_zeroed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Zero would read as "no news about this company today" — a claim this
    module is in no position to make."""

    def boom(url: str, **kw: object) -> bytes:
        raise TimeoutError("blocked")

    monkeypatch.setattr(news, "_open", boom)
    result = news.land(["RELIANCE", "TCS"], "equity", root=tmp_path, names={})
    assert result.failed == ("RELIANCE", "TCS")
    assert result.items == 0


def test_relevance_is_recorded_never_enforced() -> None:
    """An off-topic story is flagged and kept. Dropping it would be a second,
    invisible quality failure on top of the first."""
    items = news.parse_feed(
        _rss(("Something unrelated - X", "a", "X"), ("RELIANCE gains 3% - ET", "b", "ET")),
        news.query_for("RELIANCE", "equity"),
        {},
    )
    assert len(items) == 2, "nothing is dropped"
    assert [i.matched for i in items] == [False, True]


def test_india_is_a_stopword_in_company_names() -> None:
    """Otherwise every Indian company matches every story about the country."""
    assert "india" not in news.name_tokens("Nestle India Limited")
    assert "nestle" in news.name_tokens("Nestle India Limited")


def test_a_name_of_only_stopwords_still_scores() -> None:
    assert news.name_tokens("The India Company") != ()


def test_undated_or_untitled_rows_are_dropped_not_defaulted() -> None:
    feed = b"<rss><channel><title>f</title><item><title>No date</title></item></channel></rss>"
    assert news.parse_feed(feed, news.query_for("X", "equity"), {}) == []
