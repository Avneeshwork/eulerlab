"""Google News ingest — query construction, relevance scoring, and merging."""

from __future__ import annotations

from collections.abc import Iterator
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
    path = news.month_path("equity", "2026-08", root=tmp_path)

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


def test_a_pair_prefix_company_is_not_its_namesake() -> None:
    """The false explanation this matcher exists to prevent.

    `RELIANCE` is not an abbreviation, it is the word that begins Reliance
    Industries, Communications, Power and Infrastructure alike. Printing one
    beside another's price is not a weak reason, it is a wrong one.
    """
    name = "Reliance Industries Limited"
    assert news.strong_match("Reliance Industries shares rise 3%", "RELIANCE", name)
    for other in (
        "Reliance Communications (RCOM) subsidiary news",
        "Reliance Power surges 5%",
        "Reliance Infrastructure gains",
    ):
        assert not news.strong_match(other, "RELIANCE", name), other


def test_an_abbreviation_ticker_is_evidence_on_its_own() -> None:
    """`TCS` and `INFY` appear nowhere but their own company, so finding one
    settles the question without needing the registered name."""
    assert news.strong_match("Top 10 Firms: Airtel, TCS, SBI", "TCS", "Tata Consultancy Services")
    assert news.strong_match("Infosys wins deal", "INFY", "Infosys Limited")


def test_a_name_of_only_generic_words_identifies_nothing() -> None:
    """ "W S Industries (I) Limited" keeps only `industries` once initials and
    legal form are dropped, which tagged it onto every headline containing the
    word — including "Reliance Industries Q2 profit rises"."""
    assert not news.strong_match(
        "Reliance Industries Q2 profit rises 12%", "WSI", "W S Industries (I) Limited"
    )


def test_a_name_with_no_distinctive_word_falls_back_to_nothing() -> None:
    """ "B & A Limited" is single letters and a legal suffix.

    Falling back to the raw words gave ('b', 'a', 'limited'), so the match
    needed only a headline containing "b" and "a" — which tagged B & A Ltd onto
    "Cupid shares reclassified from BSE Group B to Group A".
    """
    assert news.strong_tokens("B & A Limited") == ()
    assert not news.strong_match(
        "Cupid reclassified from Group B to Group A", "BNALTD", "B & A Limited"
    )


# A few rows of NSE's EQUITY_L list, so tagging is tested offline. The real
# list used to be downloaded into data/ by these tests (HISTORY #48).
_NAMES = {
    "HDFCBANK": "HDFC Bank Limited",
    "ICICIBANK": "ICICI Bank Limited",
    "RELIANCE": "Reliance Industries Limited",
    "TCS": "Tata Consultancy Services Limited",
    "HINDALCO": "Hindalco Industries Limited",
}


@pytest.fixture
def _listed(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(news, "load_names", lambda *a, **k: _NAMES)
    news._company_index.cache_clear()
    yield
    news._company_index.cache_clear()


@pytest.mark.usefixtures("_listed")
def test_tagging_finds_every_company_a_headline_names() -> None:
    """A sector piece naming several lenders is one event with several
    exposures, and a reader on one mover needs to see the others."""
    hit = news.affected("HDFC Bank and ICICI Bank lead banking rally")
    assert "HDFCBANK" in hit.symbols and "ICICIBANK" in hit.symbols


@pytest.mark.usefixtures("_listed")
def test_tagging_finds_nothing_in_an_index_headline() -> None:
    """ "Nifty ends flat as metals drag" names no listed company. Tagging one
    would invent an exposure that is not there."""
    assert news.affected("Nifty ends flat as metals drag").symbols == ()
