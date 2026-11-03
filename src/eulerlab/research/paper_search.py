"""Finding papers: arXiv and OpenAlex, both free, both read-only.

The paper agent (`paper_agent.py`) starts here. This module only answers
"which papers match this topic, and what does each one say about itself" —
title, authors, year, abstract and the link it came from. It never decides
what a paper means.

**The link is the one field that must not be invented.** Every `Candidate`
carries the URL the search service returned and the time it was fetched. The
agent copies those into the drafts; the language model is never asked for a
source and anything it offers is discarded. `CLAUDE.md` forbids inventing a
source, and this is where that is made structural rather than hoped for.

Sources, their limits and their terms: research 124.

- **arXiv** (`export.arxiv.org/api/query`): Atom feed, no key. Its terms ask
  for no more than one request every three seconds on one connection, across
  every machine you run. `ARXIV_SPACING` enforces that inside one process.
- **OpenAlex** (`api.openalex.org/works`): JSON, no key needed for $0.10 of
  calls a day, which is 100 searches. A free key (`OPENALEX_API_KEY`) raises
  that to $1. Abstracts arrive as an inverted index and are rebuilt here.
- **Crossref** (`api.crossref.org/works/<doi>`): no key. Asked only for a paper
  OpenAlex found with no usable abstract, one request each (research 144). Some
  abstracts there are the publisher's copyright, so a fetched abstract is only
  sent to the model, never written into the repository.

The network is reached through `fetch`, a single function, so tests replace it
with recorded responses and never touch the internet (S-040).
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any

ARXIV_API = "https://export.arxiv.org/api/query"
ARXIV_HTML = "https://arxiv.org/html/"
OPENALEX_API = "https://api.openalex.org/works"
OPENALEX_KEY_ENV = "OPENALEX_API_KEY"
CROSSREF_API = "https://api.crossref.org/works/"
MIN_ABSTRACT = 200
"""Characters below which an abstract is too short to judge a paper from."""
USER_AGENT = "EulerLab-paper-agent/0.1"
TIMEOUT_SECONDS = 30
ARXIV_SPACING = 3.0
"""Seconds between arXiv requests. Its API terms, fetched 2026-10-29 (research 124)."""

MAX_RESULTS = 25
FULL_TEXT_CHARS = 16_000
"""How much of a paper's text goes to the model. Groq's free tier allows 8,000
tokens a minute on `openai/gpt-oss-120b`; 16,000 characters is about 4,000
tokens, leaving room for the instructions and the reply (research 123)."""

_ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

Fetch = Callable[[str], bytes]


class SearchFailed(RuntimeError):
    """A search service could not be reached or answered nonsense."""


@dataclass(frozen=True)
class Candidate:
    """One paper as a search service described it. Nothing here is inferred."""

    source: str
    """`arxiv` or `openalex`."""
    source_id: str
    title: str
    authors: list[str]
    year: int | None
    abstract: str
    url: str
    """The landing page the service returned. Copied into every draft."""
    fetched_at: str
    """ISO time the service answered: the card's fetch date."""
    pdf_url: str = ""
    categories: list[str] = field(default_factory=list)
    doi: str = ""
    """`10.2139/ssrn.123`, when the service gave one. Used to find a missing abstract."""

    @property
    def arxiv_id(self) -> str:
        """`2501.01234` from an arXiv link, or empty."""
        match = re.search(r"arxiv\.org/(?:abs|pdf|html)/([0-9]{4}\.[0-9]{4,5})", self.url)
        if match:
            return match.group(1)
        return self.source_id if self.source == "arxiv" else ""


def fetch(url: str) -> bytes:
    """GET one URL. The only place this module touches the network."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body: bytes = response.read()
            return body
    except urllib.error.HTTPError as exc:
        raise SearchFailed(
            f"{urllib.parse.urlsplit(url).hostname} returned HTTP {exc.code}"
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SearchFailed(f"could not reach {urllib.parse.urlsplit(url).hostname}: {exc}") from exc


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


# --- arXiv -----------------------------------------------------------------


def arxiv_query(topic: str, categories: Iterable[str] = ("q-fin",)) -> str:
    """`all:` terms from the topic, limited to the given category prefixes.

    `cat:q-fin.*` is used for "any quantitative-finance category". The manual
    documents the `cat:` prefix but not the wildcard (research 124).
    """
    words = [w for w in re.findall(r"[A-Za-z0-9-]+", topic) if len(w) > 1]
    if not words:
        raise ValueError("the topic has no searchable words")
    terms = " AND ".join(f"all:{w}" for w in words[:8])
    cats = list(categories)
    if not cats:
        return terms
    # ASSUMPTION: arXiv accepts a trailing `*` on a category (A-064).
    scope = " OR ".join(f"cat:{c}.*" if "." not in c else f"cat:{c}" for c in cats)
    return f"({terms}) AND ({scope})"


def parse_arxiv(body: bytes, *, fetched_at: str) -> list[Candidate]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise SearchFailed(f"arXiv sent something that is not Atom: {exc}") from exc
    out: list[Candidate] = []
    for entry in root.findall("a:entry", _ATOM):
        url = _clean(entry.findtext("a:id", "", _ATOM)).replace("http://", "https://", 1)
        title = _clean(entry.findtext("a:title", "", _ATOM))
        if not url or not title:
            continue
        match = re.search(r"/abs/([^v/]+)", url)
        published = entry.findtext("a:published", "", _ATOM)
        pdf = ""
        for link in entry.findall("a:link", _ATOM):
            if link.get("title") == "pdf":
                pdf = (link.get("href") or "").replace("http://", "https://", 1)
        out.append(
            Candidate(
                source="arxiv",
                source_id=match.group(1) if match else url,
                title=title,
                authors=[
                    _clean(a.findtext("a:name", "", _ATOM))
                    for a in entry.findall("a:author", _ATOM)
                ],
                year=int(published[:4]) if published[:4].isdigit() else None,
                abstract=_clean(entry.findtext("a:summary", "", _ATOM)),
                url=url,
                fetched_at=fetched_at,
                pdf_url=pdf,
                categories=[c.get("term", "") for c in entry.findall("a:category", _ATOM)],
            )
        )
    return out


def search_arxiv(topic: str, *, limit: int = 10, get: Fetch = fetch) -> list[Candidate]:
    params = {
        "search_query": arxiv_query(topic),
        "start": "0",
        "max_results": str(min(limit, MAX_RESULTS)),
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"
    return parse_arxiv(get(url), fetched_at=_now())


# --- OpenAlex --------------------------------------------------------------


def rebuild_abstract(index: dict[str, list[int]] | None) -> str:
    """OpenAlex ships abstracts as {word: [positions]} for legal reasons."""
    if not index:
        return ""
    placed: dict[int, str] = {}
    for word, positions in index.items():
        for position in positions:
            placed[int(position)] = word
    return " ".join(placed[i] for i in sorted(placed))


def parse_openalex(body: bytes, *, fetched_at: str) -> list[Candidate]:
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SearchFailed(f"OpenAlex sent something that is not JSON: {exc}") from exc
    rows = data.get("results") if isinstance(data, dict) else None
    out: list[Candidate] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        title = _clean(str(row.get("display_name") or row.get("title") or ""))
        # ASSUMPTION: `primary_location.landing_page_url` and
        # `authorships[].author.display_name` are where OpenAlex puts the
        # link and names; the attribute page points elsewhere for both (A-065).
        location = row.get("primary_location") or {}
        url = str(location.get("landing_page_url") or row.get("doi") or row.get("id") or "")
        if not title or not url.startswith(("https://", "http://")):
            continue
        open_access = row.get("open_access") or {}
        year = row.get("publication_year")
        out.append(
            Candidate(
                source="openalex",
                source_id=str(row.get("id") or "").rsplit("/", 1)[-1],
                title=title,
                authors=[
                    _clean(str((a.get("author") or {}).get("display_name") or ""))
                    for a in row.get("authorships") or []
                    if isinstance(a, dict)
                ][:20],
                year=int(year) if isinstance(year, int) else None,
                abstract=rebuild_abstract(row.get("abstract_inverted_index")),
                url=url,
                fetched_at=fetched_at,
                pdf_url=str(location.get("pdf_url") or open_access.get("oa_url") or ""),
                doi=doi_of(str(row.get("doi") or "")),
            )
        )
    return out


def doi_of(link: str) -> str:
    """`10.x/y` from `https://doi.org/10.x/y`, or empty."""
    match = re.search(r"(10\.\d{4,9}/\S+)", link)
    return match.group(1) if match else ""


def crossref_abstract(doi: str, *, get: Fetch = fetch) -> str:
    """The abstract Crossref holds for a DOI, as plain text, or "".

    Publishers deposit it as JATS XML (`<jats:p>...`); the tags are dropped.
    Never raises: a missing abstract is the usual answer, not an error.
    """
    if not doi:
        return ""
    try:
        body = json.loads(get(CROSSREF_API + urllib.parse.quote(doi)))
    except (SearchFailed, ValueError):
        return ""
    message = body.get("message") if isinstance(body, dict) else None
    raw = message.get("abstract") if isinstance(message, dict) else None
    if not isinstance(raw, str):
        return ""
    text = _clean(re.sub(r"<[^>]+>", " ", raw))
    return re.sub(r"^(abstract|summary)[:.\s]+", "", text, flags=re.IGNORECASE)


TOPIC_STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "the",
        "of",
        "in",
        "on",
        "for",
        "with",
        "from",
        "to",
        "by",
        "at",
        "as",
        "is",
        "are",
        "its",
        "into",
        "over",
        "under",
        "using",
        "india",
        "indian",
        "stock",
        "stocks",
        "market",
        "markets",
        "equity",
        "equities",
        "return",
        "returns",
        "evidence",
        "study",
        "analysis",
        "strategy",
        "strategies",
        "trading",
    ]
)
"""Words that say nothing about which effect a paper is about."""


def topic_words(topic: str) -> list[str]:
    """The topic's content words, cut to five letters so 'momentum' meets 'moment'."""
    words = re.findall(r"[a-z][a-z0-9]+", topic.lower())
    return sorted({w[:5] for w in words if w not in TOPIC_STOP and len(w) > 2})


def topic_score(candidate: Candidate, words: list[str]) -> float:
    """The share of the topic's content words the title and abstract use."""
    if not words:
        return 1.0
    have = {
        w[:5]
        for w in re.findall(r"[a-z][a-z0-9]+", f"{candidate.title} {candidate.abstract}".lower())
    }
    return sum(1 for w in words if w in have) / len(words)


def search_openalex(
    topic: str, *, limit: int = 10, since_year: int = 2015, get: Fetch = fetch
) -> list[Candidate]:
    params = {
        "search": topic,
        "filter": f"publication_year:>{since_year - 1},type:article|preprint",
        "per_page": str(min(limit, MAX_RESULTS)),
    }
    key = os.environ.get(OPENALEX_KEY_ENV, "").strip()
    if key:
        params["api_key"] = key
    url = f"{OPENALEX_API}?{urllib.parse.urlencode(params)}"
    return parse_openalex(get(url), fetched_at=_now())


# --- full text -------------------------------------------------------------


class _Text(HTMLParser):
    """Visible text of an HTML page, without scripts, styles or navigation."""

    SKIP = frozenset({"script", "style", "nav", "header", "footer", "math", "svg"})

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self._skipping += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skipping:
            self._skipping -= 1

    def handle_data(self, data: str) -> None:
        if not self._skipping and data.strip():
            self.parts.append(data.strip())


def html_text(body: bytes) -> str:
    parser = _Text()
    parser.feed(body.decode("utf-8", errors="replace"))
    return _clean(" ".join(parser.parts))


def full_text(candidate: Candidate, *, get: Fetch = fetch) -> str:
    """arXiv's HTML rendering of the paper, cut to `FULL_TEXT_CHARS`, or "".

    Only arXiv: its HTML version is text without a PDF parser, and its terms
    allow retrieval for research use (research 124). A paper with no HTML
    version is read from its abstract, and the draft says so.
    """
    if not candidate.arxiv_id:
        return ""
    try:
        text = html_text(get(f"{ARXIV_HTML}{candidate.arxiv_id}"))
    except SearchFailed:
        return ""
    if len(text) < 2_000:  # a "no HTML for this paper" page, not a paper
        return ""
    return text[:FULL_TEXT_CHARS]


# --- the combined search ---------------------------------------------------


def normalise_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def search(
    topic: str,
    *,
    sources: Iterable[str] = ("arxiv", "openalex"),
    limit: int = 10,
    get: Fetch = fetch,
    sleep: Callable[[float], Any] = time.sleep,
) -> tuple[list[Candidate], list[str]]:
    """Every source's results, one per title, and a line for each that failed.

    A failed source does not stop the others: a paper found on one is still a
    paper. The failures are returned so the run's record says what was not
    searched.
    """
    found: list[Candidate] = []
    failures: list[str] = []
    for source in sources:
        try:
            if source == "arxiv":
                found += search_arxiv(topic, limit=limit, get=get)
                sleep(ARXIV_SPACING)
            elif source == "openalex":
                found += search_openalex(topic, limit=limit, get=get)
            else:
                failures.append(f"{source}: unknown source")
        except (SearchFailed, ValueError) as exc:
            failures.append(f"{source}: {exc}")
    seen: set[str] = set()
    unique: list[Candidate] = []
    for candidate in found:
        key = normalise_title(candidate.title)
        if key and key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique, failures
