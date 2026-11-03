"""CORE and Semantic Scholar as paper sources, and keys under the operator's names (ADR-131)."""

from __future__ import annotations

import json
import urllib.parse
from typing import Any

import pytest

from eulerlab.research import paper_search

CORE_PAGE = json.dumps(
    {
        "totalHits": 2,
        "results": [
            {
                "id": 353990150,
                "title": "Retail investor attention and short-term return reversal",
                "authors": [{"name": "Lee, Ann"}, {"name": "Rao, B."}],
                "yearPublished": 2020,
                "abstract": "We show short-term reversal is stronger in stocks with "
                "high retail attention. " * 5,
                "doi": "10.2139/ssrn.3722540",
                "arxivId": None,
                "downloadUrl": "https://core.ac.uk/download/574458456.pdf",
                "links": [
                    {"type": "download", "url": "https://core.ac.uk/download/574458456.pdf"},
                    {"type": "display", "url": "https://core.ac.uk/works/353990150"},
                ],
            },
            {"id": 7, "title": ""},
        ],
    }
).encode()

S2_PAGE = json.dumps(
    {
        "total": 1,
        "data": [
            {
                "paperId": "65e12dcda56c1efd453d90010b1d7a6cce8a8e39",
                "title": "Is short-term reversal driven by liquidity provision in emerging markets?",
                "url": "https://www.semanticscholar.org/paper/65e12dcda56c1efd453d90010b1d7a6cce8a8e39",
                "year": 2022,
                "authors": [{"authorId": "1", "name": "Chen Wei"}],
                "abstract": "Liquidity provision explains reversal in China. " * 6,
                "externalIds": {"DOI": "10.1016/J.FRL.2022.103220", "ArXiv": "2201.01234v2"},
                "openAccessPdf": {"url": "https://example.org/a.pdf", "status": "HYBRID"},
            },
            {"paperId": "x", "title": "No link", "url": ""},
        ],
    }
).encode()


@pytest.fixture(autouse=True)
def _no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests choose their own keys; the operator's `.env` is never read here."""
    monkeypatch.setattr("eulerlab.env.load_env", lambda path=None: {})
    for name in (*paper_search.OPENALEX_KEYS, *paper_search.CORE_KEYS, *paper_search.S2_KEYS):
        monkeypatch.delenv(name, raising=False)


def test_the_operators_spelling_of_each_key_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPEN_ALEX_API_KEY", " oa ")
    monkeypatch.setenv("CORE_API", "core")
    monkeypatch.setenv("Semantic_API", "s2")
    assert paper_search.api_key(paper_search.OPENALEX_KEYS) == "oa"
    assert paper_search.api_key(paper_search.CORE_KEYS) == "core"
    assert paper_search.api_key(paper_search.S2_KEYS) == "s2"


def test_the_standard_name_wins_over_the_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENALEX_API_KEY", "first")
    monkeypatch.setenv("OPEN_ALEX_API_KEY", "second")
    assert paper_search.api_key(paper_search.OPENALEX_KEYS) == "first"


def test_openalex_sends_the_key_under_the_operators_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPEN_ALEX_API_KEY", "oa-key")
    asked: list[str] = []

    def get(url: str) -> bytes:
        asked.append(url)
        return b'{"results": []}'

    paper_search.search_openalex("momentum", get=get)
    paper_search.search_ssrn("momentum", get=get)
    assert all("api_key=oa-key" in u for u in asked)


def test_core_query_keeps_to_the_topic_words_in_the_abstract() -> None:
    q = paper_search.core_query("short-term reversal Indian equities", 2015)
    assert q.startswith('abstract:"short-term" AND abstract:"reversal" AND')
    assert "indian" not in q and q.endswith("yearPublished>=2015")
    with pytest.raises(ValueError):
        paper_search.core_query("the Indian stock market", 2015)


def test_core_results_keep_the_link_core_returned() -> None:
    asked: list[str] = []

    def get(url: str) -> bytes:
        asked.append(url)
        return CORE_PAGE

    rows = paper_search.search_core("short-term reversal", get=get)
    assert asked[0].startswith(paper_search.CORE_API + "?")
    assert "exclude=fullText" in asked[0]
    [c] = rows
    assert c.source == "core" and c.url == "https://core.ac.uk/works/353990150"
    assert c.doi == "10.2139/ssrn.3722540" and c.year == 2020
    assert c.pdf_url.endswith("574458456.pdf") and len(c.abstract) > 200
    assert c.authors == ["Lee, Ann", "Rao, B."]


def test_semantic_scholar_results_carry_doi_and_arxiv_number() -> None:
    rows = paper_search.search_semantic_scholar("reversal", get=lambda _u: S2_PAGE)
    [c] = rows
    assert c.source == "semantic_scholar" and c.url.startswith("https://www.semanticscholar.org/")
    assert c.doi == "10.1016/j.frl.2022.103220"
    assert c.arxiv_id == "2201.01234"  # so arXiv's full text can be read
    assert c.pdf_url == "https://example.org/a.pdf"


def test_semantic_scholar_429_is_retried_then_succeeds() -> None:
    calls: list[str] = []
    waits: list[float] = []

    def get(url: str) -> bytes:
        calls.append(url)
        if len(calls) < 3:
            raise paper_search.SearchFailed("api.semanticscholar.org returned HTTP 429", 429)
        return S2_PAGE

    rows = paper_search.search_semantic_scholar("reversal", get=get, sleep=waits.append)
    assert len(calls) == 3 and len(rows) == 1 and waits == [5.0, 10.0]


def test_semantic_scholar_gives_up_after_its_retries() -> None:
    def get(_url: str) -> bytes:
        raise paper_search.SearchFailed("api.semanticscholar.org returned HTTP 429", 429)

    found, failures = paper_search.search(
        "reversal", sources=["semantic_scholar"], get=get, sleep=lambda _s: None
    )
    assert found == [] and failures == [
        "semantic_scholar: api.semanticscholar.org returned HTTP 429"
    ]


def test_other_errors_are_not_retried() -> None:
    calls: list[str] = []

    def get(url: str) -> bytes:
        calls.append(url)
        raise paper_search.SearchFailed("api.semanticscholar.org returned HTTP 500", 500)

    with pytest.raises(paper_search.SearchFailed):
        paper_search.search_semantic_scholar("x", get=get, sleep=lambda _s: None)
    assert len(calls) == 1


def test_core_and_semantic_scholar_are_paced() -> None:
    waits: list[float] = []

    def get(url: str) -> bytes:
        return CORE_PAGE if url.startswith(paper_search.CORE_API) else S2_PAGE

    found, failures = paper_search.search(
        "short-term reversal", sources=["core", "semantic_scholar"], get=get, sleep=waits.append
    )
    assert failures == [] and len(found) == 2 and waits == [6.0, 1.0]


def test_a_paper_core_and_ssrn_both_hold_is_kept_once() -> None:
    known = paper_search.Known()
    known.add("A different title", "https://doi.org/10.2139/ssrn.3722540")
    [c] = paper_search.parse_core(CORE_PAGE, fetched_at="t")
    assert known.holds(c)
    assert "core:353990150" in paper_search.identities(url=c.url)
    s2 = "https://www.semanticscholar.org/paper/65e12dcda56c1efd453d90010b1d7a6cce8a8e39"
    assert "s2:65e12dcda56c1efd453d90010b1d7a6cce8a8e39" in paper_search.identities(url=s2)


def test_keys_go_in_headers_only_with_the_real_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: dict[str, Any] = {}

    class Reply:
        def __enter__(self) -> Reply:
            return self

        def __exit__(self, *_a: object) -> None:
            return None

        def read(self) -> bytes:
            return S2_PAGE

    def urlopen(request: Any, timeout: float) -> Reply:
        sent["url"] = request.full_url
        sent["headers"] = {k.lower(): v for k, v in request.header_items()}
        return Reply()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    monkeypatch.setenv("Semantic_API", "s2-key")
    paper_search.search_semantic_scholar("reversal")
    assert sent["headers"]["x-api-key"] == "s2-key"
    assert "s2-key" not in urllib.parse.unquote(sent["url"])
    fake = lambda _u: b"{}"  # noqa: E731
    assert paper_search.with_headers(fake, {"x": "y"}) is fake


def test_the_research_agent_searches_core_and_semantic_scholar() -> None:
    from eulerlab.agents.spec import all_effective

    sources = all_effective()["research"].spec.options["sources"]
    assert {"core", "semantic_scholar"} <= set(sources)
