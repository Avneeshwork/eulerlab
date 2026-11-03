"""Finding papers: arXiv, OpenAlex, SSRN, NBER, CORE and Semantic Scholar, all free, all read-only.

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
  calls a day, which is 100 searches. A free key (`OPENALEX_API_KEY` or
  `OPEN_ALEX_API_KEY`) raises that to $1 (measured 2026-11-03 from the
  `X-RateLimit-Limit-USD` header). Abstracts arrive as an inverted index and are
  rebuilt here.
- **SSRN** (ADR-129): its own site refuses automated access (HTTP 403
  "Content Blocked", 2026-11-03), so it is searched through OpenAlex, which
  indexes it as source `S4210172589` ("SSRN Electronic Journal"). Abstracts are
  usually missing there and come from Crossref.
- **NBER working papers** (ADR-129): searched on Crossref by NBER's DOI prefix
  `10.3386`; Crossref holds no abstracts for them, OpenAlex does (by DOI).
- **CORE** (`api.core.ac.uk/v3/search/works`, ADR-131): open-access papers from
  repositories worldwide, abstracts included. Key `CORE_API_KEY` or `CORE_API`,
  sent as `Authorization: Bearer`. A registered personal key gets 1,000 tokens a
  day; the response header said 10 a minute (research 146), so `SPACING` waits
  6 seconds between CORE searches.
- **Semantic Scholar** (`api.semanticscholar.org/graph/v1/paper/search`,
  ADR-131): key `SEMANTIC_SCHOLAR_API_KEY` or `Semantic_API`, sent as
  `x-api-key`, 1 request a second. Its relevance search answers HTTP 429 now and
  then even with a key (2026-11-03), so a 429 is retried twice after a pause.
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
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any

ARXIV_API = "https://export.arxiv.org/api/query"
ARXIV_HTML = "https://arxiv.org/html/"
OPENALEX_API = "https://api.openalex.org/works"
OPENALEX_KEY_ENV = "OPENALEX_API_KEY"
OPENALEX_KEYS = (OPENALEX_KEY_ENV, "OPEN_ALEX_API_KEY")
CORE_API = "https://api.core.ac.uk/v3/search/works"
CORE_KEYS = ("CORE_API_KEY", "CORE_API")
S2_API = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_KEYS = ("SEMANTIC_SCHOLAR_API_KEY", "Semantic_API")
S2_FIELDS = "title,abstract,year,authors,externalIds,url,openAccessPdf"
S2_RETRIES = 2
S2_WAIT = 5.0
"""Seconds to wait before retrying a Semantic Scholar 429."""
CROSSREF_API = "https://api.crossref.org/works/"
CROSSREF_SEARCH = "https://api.crossref.org/works"
SSRN_SOURCE = "S4210172589"
"""OpenAlex's id for SSRN (`/sources?search=SSRN`, 2026-11-03: 1,374,524 works)."""
NBER_PREFIX = "10.3386"
"""NBER's DOI prefix; working papers are `10.3386/w<number>`."""
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

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        """The HTTP status, when the service answered with one."""


def api_key(names: Iterable[str]) -> str:
    """The first of these `.env` names that holds a value, or "".

    Several names because the operator's `.env` spells some keys its own way
    (`OPEN_ALEX_API_KEY` where the code read only `OPENALEX_API_KEY`, HISTORY #69).
    Loads `.env` first: a search can run before anything else has loaded it.
    """
    from eulerlab.env import load_env

    load_env()
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


@dataclass(frozen=True)
class Candidate:
    """One paper as a search service described it. Nothing here is inferred."""

    source: str
    """A name in `SOURCES`: `arxiv`, `openalex`, `ssrn`, `nber`, `core`, `semantic_scholar`."""
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
    arxiv: str = ""
    """The arXiv number a non-arXiv service says this paper also has."""

    @property
    def arxiv_id(self) -> str:
        """`2501.01234` from an arXiv link, or empty."""
        if self.arxiv:
            return self.arxiv.split("v")[0]
        match = re.search(r"arxiv\.org/(?:abs|pdf|html)/([0-9]{4}\.[0-9]{4,5})", self.url)
        if match:
            return match.group(1)
        return self.source_id if self.source == "arxiv" else ""


def fetch(url: str, headers: dict[str, str] | None = None) -> bytes:
    """GET one URL. The only place this module touches the network."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body: bytes = response.read()
            return body
    except urllib.error.HTTPError as exc:
        raise SearchFailed(
            f"{urllib.parse.urlsplit(url).hostname} returned HTTP {exc.code}", exc.code
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SearchFailed(f"could not reach {urllib.parse.urlsplit(url).hostname}: {exc}") from exc


def with_headers(get: Fetch, headers: dict[str, str]) -> Fetch:
    """`get` that sends these headers when it is the real `fetch`.

    A test's recorded responses take a URL only, and are returned unchanged.
    """
    if get is fetch and headers:
        return lambda url: fetch(url, headers)
    return get


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


def search_ssrn(
    topic: str, *, limit: int = 10, since_year: int = 2015, get: Fetch = fetch
) -> list[Candidate]:
    """SSRN papers on the topic, through OpenAlex's index of SSRN (its own site blocks robots)."""
    params = {
        "search": topic,
        "filter": f"primary_location.source.id:{SSRN_SOURCE},publication_year:>{since_year - 1}",
        "per_page": str(min(limit, MAX_RESULTS)),
    }
    key = api_key(OPENALEX_KEYS)
    if key:
        params["api_key"] = key
    found = parse_openalex(
        get(f"{OPENALEX_API}?{urllib.parse.urlencode(params)}"), fetched_at=_now()
    )
    return [replace(c, source="ssrn") for c in found]


def parse_crossref(body: bytes, *, source: str, fetched_at: str) -> list[Candidate]:
    try:
        items = json.loads(body).get("message", {}).get("items", [])
    except (json.JSONDecodeError, AttributeError) as exc:
        raise SearchFailed(f"Crossref sent something that is not a work list: {exc}") from exc
    out: list[Candidate] = []
    for row in items if isinstance(items, list) else []:
        doi = str(row.get("DOI") or "").strip()
        title = _clean(" ".join(row.get("title") or []))
        if not doi or not title:
            continue
        parts = ((row.get("published") or row.get("issued") or {}).get("date-parts") or [[None]])[0]
        year = parts[0] if parts and isinstance(parts[0], int) else None
        abstract = _clean(re.sub(r"<[^>]+>", " ", str(row.get("abstract") or "")))
        out.append(
            Candidate(
                source=source,
                source_id=doi,
                title=title,
                authors=[
                    _clean(f"{a.get('given', '')} {a.get('family', '')}")
                    for a in row.get("author") or []
                    if isinstance(a, dict)
                ][:20],
                year=year,
                abstract=re.sub(r"^(abstract|summary)[:.\s]+", "", abstract, flags=re.IGNORECASE),
                url=f"https://doi.org/{doi}",
                fetched_at=fetched_at,
                doi=doi.lower(),
            )
        )
    return out


def search_nber(
    topic: str, *, limit: int = 10, since_year: int = 2015, get: Fetch = fetch
) -> list[Candidate]:
    """NBER working papers on the topic, from Crossref by NBER's DOI prefix."""
    params = {
        "query.bibliographic": topic,
        "filter": f"prefix:{NBER_PREFIX},from-pub-date:{since_year}-01-01",
        "rows": str(min(limit, MAX_RESULTS)),
        "select": "DOI,title,author,published,issued,abstract",
    }
    body = get(f"{CROSSREF_SEARCH}?{urllib.parse.urlencode(params)}")
    return parse_crossref(body, source="nber", fetched_at=_now())


def openalex_abstract(doi: str, *, get: Fetch = fetch) -> str:
    """The abstract OpenAlex holds for a DOI, or "". Never raises."""
    if not doi:
        return ""
    try:
        row = json.loads(get(f"{OPENALEX_API}/doi:{urllib.parse.quote(doi)}"))
    except (SearchFailed, ValueError):
        return ""
    return rebuild_abstract(row.get("abstract_inverted_index")) if isinstance(row, dict) else ""


def fuller_abstract(doi: str, *, get: Fetch = fetch) -> tuple[str, str]:
    """A missing abstract from Crossref, else OpenAlex: (text, where it came from)."""
    for name, look in (("Crossref", crossref_abstract), ("OpenAlex", openalex_abstract)):
        text = look(doi, get=get)
        if len(text) >= MIN_ABSTRACT:
            return text, name
    return "", ""


def search_openalex(
    topic: str, *, limit: int = 10, since_year: int = 2015, get: Fetch = fetch
) -> list[Candidate]:
    params = {
        "search": topic,
        "filter": f"publication_year:>{since_year - 1},type:article|preprint",
        "per_page": str(min(limit, MAX_RESULTS)),
    }
    key = api_key(OPENALEX_KEYS)
    if key:
        params["api_key"] = key
    url = f"{OPENALEX_API}?{urllib.parse.urlencode(params)}"
    return parse_openalex(get(url), fetched_at=_now())


# --- CORE and Semantic Scholar (ADR-131) ----------------------------------


def core_query(topic: str, since_year: int) -> str:
    """Every content word of the topic in the abstract, about stocks, since a year.

    Plain words search CORE's full text and return papers on anything (a
    'momentum' query found nutrition policy, 2026-11-03); `abstract:"word"`
    terms keep it on the topic (research 146).
    """
    words = [
        w
        for w in re.findall(r"[a-z0-9][a-z0-9-]+", topic.lower())
        if w not in TOPIC_STOP and len(w) > 2
    ]
    if not words:
        raise ValueError("the topic has no searchable words")
    terms = " AND ".join(f'abstract:"{w}"' for w in words[:6])
    return f'{terms} AND (abstract:"stock" OR abstract:"equity") AND yearPublished>={since_year}'


def parse_core(body: bytes, *, fetched_at: str) -> list[Candidate]:
    try:
        rows = json.loads(body).get("results", [])
    except (json.JSONDecodeError, AttributeError) as exc:
        raise SearchFailed(f"CORE sent something that is not a work list: {exc}") from exc
    out: list[Candidate] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        title = _clean(str(row.get("title") or ""))
        if not title:
            continue
        links = [x.get("url", "") for x in row.get("links") or [] if isinstance(x, dict)]
        display = [u for u in links if "/works/" in u]
        year = row.get("yearPublished")
        doi = doi_of(str(row.get("doi") or ""))
        out.append(
            Candidate(
                source="core",
                source_id=str(row["id"]),
                title=title,
                authors=[
                    _clean(str(a.get("name") or ""))
                    for a in row.get("authors") or []
                    if isinstance(a, dict)
                ][:20],
                year=int(year) if isinstance(year, int) else None,
                abstract=_clean(str(row.get("abstract") or "")),
                url=display[0] if display else f"https://core.ac.uk/works/{row['id']}",
                fetched_at=fetched_at,
                pdf_url=str(row.get("downloadUrl") or ""),
                doi=doi.lower(),
                arxiv=str(row.get("arxivId") or ""),
            )
        )
    return out


def search_core(
    topic: str, *, limit: int = 10, since_year: int = 2015, get: Fetch = fetch
) -> list[Candidate]:
    """Open-access papers on the topic from CORE, abstracts included."""
    params = {
        "q": core_query(topic, since_year),
        "limit": str(min(limit, MAX_RESULTS)),
        "exclude": "fullText",
    }
    key = api_key(CORE_KEYS)
    look = with_headers(get, {"Authorization": f"Bearer {key}"} if key else {})
    return parse_core(look(f"{CORE_API}?{urllib.parse.urlencode(params)}"), fetched_at=_now())


def parse_semantic_scholar(body: bytes, *, fetched_at: str) -> list[Candidate]:
    try:
        rows = json.loads(body).get("data", [])
    except (json.JSONDecodeError, AttributeError) as exc:
        raise SearchFailed(f"Semantic Scholar sent something that is not a list: {exc}") from exc
    out: list[Candidate] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        title = _clean(str(row.get("title") or ""))
        url = str(row.get("url") or "")
        if not title or not url.startswith("https://"):
            continue
        ids = row.get("externalIds") or {}
        year = row.get("year")
        pdf = row.get("openAccessPdf") or {}
        out.append(
            Candidate(
                source="semantic_scholar",
                source_id=str(row.get("paperId") or ""),
                title=title,
                authors=[
                    _clean(str(a.get("name") or ""))
                    for a in row.get("authors") or []
                    if isinstance(a, dict)
                ][:20],
                year=int(year) if isinstance(year, int) else None,
                abstract=_clean(str(row.get("abstract") or "")),
                url=url,
                fetched_at=fetched_at,
                pdf_url=str(pdf.get("url") or "") if isinstance(pdf, dict) else "",
                doi=str(ids.get("DOI") or "").lower(),
                arxiv=str(ids.get("ArXiv") or ""),
            )
        )
    return out


def search_semantic_scholar(
    topic: str,
    *,
    limit: int = 10,
    since_year: int = 2015,
    get: Fetch = fetch,
    sleep: Callable[[float], Any] = time.sleep,
) -> list[Candidate]:
    """Papers on the topic in economics and business, from Semantic Scholar."""
    params = {
        "query": topic,
        "limit": str(min(limit, MAX_RESULTS)),
        "fields": S2_FIELDS,
        "year": f"{since_year}-",
        "fieldsOfStudy": "Economics,Business",
    }
    key = api_key(S2_KEYS)
    look = with_headers(get, {"x-api-key": key} if key else {})
    url = f"{S2_API}?{urllib.parse.urlencode(params)}"
    for attempt in range(S2_RETRIES + 1):
        try:
            return parse_semantic_scholar(look(url), fetched_at=_now())
        except SearchFailed as exc:
            if exc.status != 429 or attempt == S2_RETRIES:
                raise
            sleep(S2_WAIT * (attempt + 1))
    return []


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


# --- one paper, many links (ADR-129) ---------------------------------------

TITLE_STOP = frozenset(
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
        "via",
        "vs",
        "versus",
        "evidence",
        "study",
        "analysis",
        "new",
    ]
)
NEAR_TITLE = 0.85
"""Word overlap (Jaccard) at which two titles of five or more words are one paper:
SSRN lists a revision under a new DOI, often with a reworded title (A-099)."""


def identities(title: str = "", url: str = "", doi: str = "", arxiv: str = "") -> set[str]:
    """Every name a paper goes by: DOI, arXiv number without version, SSRN and NBER
    numbers, and its normalised title. Two records sharing any one are one paper."""
    out: set[str] = set()
    text = f"{url} {doi}".lower()
    found_doi = doi.lower() or doi_of(url).lower()
    if found_doi:
        out.add(f"doi:{found_doi.rstrip('/.')}")
    match = re.search(r"arxiv\.org/(?:abs|pdf|html)/([0-9]{4}\.[0-9]{4,5})", text)
    if arxiv or match:
        out.add(f"arxiv:{(arxiv or (match.group(1) if match else '')).split('v')[0]}")
    match = re.search(r"(?:10\.2139/ssrn\.|abstract_id=)(\d+)", text)
    if match:
        out.add(f"ssrn:{match.group(1)}")
    match = re.search(r"(?:10\.3386/|nber\.org/papers/)(w\d+)", text)
    if match:
        out.add(f"nber:{match.group(1)}")
    match = re.search(r"core\.ac\.uk/works/(\d+)", text)
    if match:
        out.add(f"core:{match.group(1)}")
    match = re.search(r"semanticscholar\.org/paper/([0-9a-f]{40})", text)
    if match:
        out.add(f"s2:{match.group(1)}")
    if normalise_title(title):
        out.add(f"title:{normalise_title(title)}")
    return out


def title_words(title: str) -> frozenset[str]:
    return frozenset(w for w in normalise_title(title).split() if w not in TITLE_STOP)


def near_titles(a: frozenset[str], b: frozenset[str]) -> bool:
    if min(len(a), len(b)) < 5:
        return False
    return len(a & b) / len(a | b) >= NEAR_TITLE


@dataclass
class Known:
    """Papers already held, read or rejected, by every name they go by."""

    ids: set[str] = field(default_factory=set)
    titles: list[frozenset[str]] = field(default_factory=list)

    def add(self, title: str = "", url: str = "", doi: str = "", arxiv: str = "") -> None:
        self.ids |= identities(title, url, doi, arxiv)
        words = title_words(title)
        if words:
            self.titles.append(words)

    def add_candidate(self, c: Candidate) -> None:
        self.add(c.title, c.url, c.doi, c.arxiv_id)

    def holds(self, c: Candidate) -> bool:
        if identities(c.title, c.url, c.doi, c.arxiv_id) & self.ids:
            return True
        words = title_words(c.title)
        return any(near_titles(words, held) for held in self.titles)


Search = Callable[..., list[Candidate]]

SOURCES: dict[str, Search] = {
    "arxiv": search_arxiv,
    "openalex": search_openalex,
    "ssrn": search_ssrn,
    "nber": search_nber,
    "core": search_core,
    "semantic_scholar": search_semantic_scholar,
}
"""Every source the research agent may search, by the name `config/agents/research.yaml`
lists. A new source is one function here and one line there (ADR-129)."""

DEFAULT_SOURCES = ("arxiv", "openalex", "ssrn", "nber")
"""What a caller that names no sources searches. The research agent names its
own in `config/agents/research.yaml`, which adds `core` and `semantic_scholar`."""

# ASSUMPTION: CORE allows 10 searches a minute and Semantic Scholar 1 a second (A-100).
SPACING = {"arxiv": ARXIV_SPACING, "core": 6.0, "semantic_scholar": 1.0}
"""Seconds to wait after a search on each source: arXiv's terms ask for 3; CORE's
response header said 10 a minute; Semantic Scholar allows a key 1 a second."""


def search(
    topic: str,
    *,
    sources: Iterable[str] = DEFAULT_SOURCES,
    limit: int = 10,
    get: Fetch = fetch,
    sleep: Callable[[float], Any] = time.sleep,
) -> tuple[list[Candidate], list[str]]:
    """Every source's results, one per paper, and a line for each that failed.

    A failed source does not stop the others: a paper found on one is still a
    paper. The failures are returned so the run's record says what was not
    searched. A paper two sources both return (SSRN through OpenAlex and plain
    OpenAlex often do) is kept once, from the first source listed.
    """
    found: list[Candidate] = []
    failures: list[str] = []
    for source in sources:
        look = SOURCES.get(source)
        if look is None:
            failures.append(f"{source}: unknown source")
            continue
        try:
            if source == "semantic_scholar":
                found += look(topic, limit=limit, get=get, sleep=sleep)
            else:
                found += look(topic, limit=limit, get=get)
            if source in SPACING:
                sleep(SPACING[source])
        except (SearchFailed, ValueError) as exc:
            failures.append(f"{source}: {exc}")
    seen = Known()
    unique: list[Candidate] = []
    for candidate in found:
        if candidate.title and not seen.holds(candidate):
            seen.add_candidate(candidate)
            unique.append(candidate)
    return unique, failures
