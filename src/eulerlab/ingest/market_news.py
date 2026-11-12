"""Market-wide and geopolitical news for the brief, from Currents API (ADR-134, research 148).

`ingest/news.py` searches per instrument. This module searches by theme: the
Indian market, policy, geopolitics, the Fed, crude and the rupee, from the
fixed list in `config/market_news.yaml`. Currents API (key `CURRENT_NEWS_API`)
returns a title, a description of up to 300 characters, categories and a
publication time; Google News RSS is the fallback when the key is missing or
a search fails, and gives titles only. NewsData.io (key `News_Data_io`) runs
the same searches as a second source (ADR-135): its free plan carries its own
sentiment per story, kept as `newsdata_tone` beside ours.

**Landing.** Rows land in `data/landing/news/market/<month>.jsonl.gz`, merged
by `guid` with `news._merge` (the first sighting's `knowledge_time` wins; the
searches that found a story are unioned into `symbols`), so the nightly
`upload-tree TREES=news` carries them to B2 with the rest of the news.

**Derived.** `DERIVED` (`data/derived/market_news.jsonl`) holds every story with
its relevance flag and its tone from `forecast/news_tone.py`, scored once. The
brief reads this table, not the landing files, because those leave the machine
once uploaded.

**Knowledge time is when we first saw it.** The first run searches 30 days
back; those stories carry the run's time as `knowledge_time`, not their
publication time, so no reader dated before the run can see them. They show
today's tone against the month, but cannot test whether news forecast past
sessions (that needs GDELT's history, T-4433).
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from eulerlab.config import CONFIG_DIR
from eulerlab.ingest import news
from eulerlab.paths import data_path

CURRENTS = "https://api.currentsapi.services/v1/search"
KEY_NAMES = ("CURRENT_NEWS_API", "CURRENTS_API_KEY")
NEWSDATA = "https://newsdata.io/api/1/latest"
NEWSDATA_KEYS = ("News_Data_io", "NEWSDATA_API_KEY")
LANDING = news.LANDING
DERIVED = data_path("derived/market_news.jsonl")
CLASS = "market"
# Currents allows at most 7 days in one search on the free plan, and answers 400
# "Max range is 7 days" to exactly 7 (measured 2026-11-04).
SPAN = timedelta(days=7) - timedelta(hours=1)

Scorer = Callable[[Sequence[str]], list[dict[str, float]]]


class Search(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    topic: str
    keywords: str
    country: str = ""


class Setup(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    searches: list[Search]
    page_size: int
    backfill_days: int
    relevant: list[str]
    ignore: list[str]
    judge: int


def setup(config_dir: Path | None = None) -> Setup:
    path = (config_dir or CONFIG_DIR) / "market_news.yaml"
    return Setup.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def api_key() -> str:
    from eulerlab.research.paper_search import api_key as first

    return first(KEY_NAMES)


def newsdata_key() -> str:
    from eulerlab.research.paper_search import api_key as first

    return first(NEWSDATA_KEYS)


def _words(words: Iterable[str]) -> re.Pattern[str]:
    return re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b", re.IGNORECASE)


def relevant(title: str, description: str, s: Setup) -> bool:
    """A story about markets, policy or geopolitics, not a fraud payout or a film."""
    text = f"{title} {description}"
    return bool(_words(s.relevant).search(text)) and not _words(s.ignore).search(text)


def guid(url: str, title: str) -> str:
    return hashlib.sha1((url or title).encode("utf-8")).hexdigest()[:16]


def _published(raw: str) -> str:
    """Currents' "2026-11-04 04:14:00 +0000" into UTC ISO, or "" when unreadable."""
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S %z").astimezone(UTC).isoformat()
    except ValueError:
        return ""


def parse_currents(
    body: Mapping[str, Any], search: Search, s: Setup, now: datetime
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for a in body.get("news") or []:
        title = str(a.get("title") or "").strip()
        when = _published(str(a.get("published") or ""))
        if not title or not when:
            continue
        description = str(a.get("description") or "").strip()[:300]
        url = str(a.get("url") or "")
        out.append(
            {
                "guid": guid(url, title),
                "title": title,
                "description": description,
                "link": url,
                "publisher": urllib.parse.urlparse(url).netloc,
                "symbols": [search.topic],
                "provider": "currents",
                "matched": relevant(title, description, s),
                "event_time": when,
                "knowledge_time": now.isoformat(),
                "receipt_time": now.isoformat(),
            }
        )
    return out


def search_currents(
    search: Search, key: str, s: Setup, now: datetime, start: datetime, end: datetime
) -> list[dict[str, Any]]:
    params = {
        "keywords": search.keywords,
        "language": "en",
        "page_size": str(s.page_size),
        "start_date": start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_date": end.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if search.country:
        params["country"] = search.country
    request = urllib.request.Request(
        f"{CURRENTS}?{urllib.parse.urlencode(params)}",
        headers={"Authorization": f"Bearer {key}", "User-Agent": news.USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not isinstance(body, dict) or body.get("status") != "ok":
        msg = f"currents answered {str(body)[:120]}"
        raise ValueError(msg)
    return parse_currents(body, search, s, now)


def parse_newsdata(
    body: Mapping[str, Any], search: Search, s: Setup, now: datetime
) -> list[dict[str, Any]]:
    """NewsData.io's latest results; its sentiment percentages become a score from -1 to +1."""
    out: list[dict[str, Any]] = []
    results = body.get("results")
    for a in results if isinstance(results, list) else []:
        title = str(a.get("title") or "").strip()
        try:
            when = (
                datetime.strptime(str(a.get("pubDate") or ""), "%Y-%m-%d %H:%M:%S")
                .replace(tzinfo=UTC)
                .isoformat()
            )
        except ValueError:
            continue
        if not title:
            continue
        description = str(a.get("description") or "").strip()[:300]
        url = str(a.get("link") or "")
        row: dict[str, Any] = {
            "guid": guid(url, title),
            "title": title,
            "description": description,
            "link": url,
            "publisher": str(a.get("source_name") or a.get("source_id") or ""),
            "symbols": [search.topic],
            "provider": "newsdata",
            "matched": relevant(title, description, s),
            "event_time": when,
            "knowledge_time": now.isoformat(),
            "receipt_time": now.isoformat(),
        }
        stats = a.get("sentiment_stats")
        if isinstance(stats, dict) and all(
            isinstance(stats.get(k), int | float) for k in ("positive", "negative")
        ):
            pos, neg = float(stats["positive"]) / 100, float(stats["negative"]) / 100
            row["newsdata_tone"] = {
                "positive": round(pos, 4),
                "negative": round(neg, 4),
                "score": round(pos - neg, 4),
                "label": str(a.get("sentiment") or ""),
            }
        out.append(row)
    return out


def search_newsdata(search: Search, key: str, s: Setup, now: datetime) -> list[dict[str, Any]]:
    """One search on NewsData's latest news (the free plan holds 48 hours, 10 results a credit)."""
    params = {"apikey": key, "q": search.keywords, "language": "en", "size": "10"}
    if search.country:
        params["country"] = search.country.lower()
    request = urllib.request.Request(
        f"{NEWSDATA}?{urllib.parse.urlencode(params)}", headers={"User-Agent": news.USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not isinstance(body, dict) or body.get("status") != "success":
        # The body can echo the request; never the key.
        msg = f"newsdata answered status {body.get('status') if isinstance(body, dict) else '?'}"
        raise ValueError(msg)
    return parse_newsdata(body, search, s, now)


def parse_rss(payload: bytes, search: Search, s: Setup, now: datetime) -> list[dict[str, Any]]:
    """Google News RSS: titles only, the publisher trimmed from the end."""
    try:
        root = ET.fromstring(payload.decode("utf-8", errors="replace"))
    except ET.ParseError:
        return []
    out: list[dict[str, Any]] = []
    for node in root.iterfind(".//item"):
        title = (node.findtext("title") or "").strip()
        when = news._published((node.findtext("pubDate") or "").strip())
        source = node.find("source")
        publisher = (source.text or "").strip() if source is not None else ""
        if publisher and title.endswith(f" - {publisher}"):
            title = title[: -len(publisher) - 3].strip()
        if not title or not when:
            continue
        url = (node.findtext("link") or "").strip()
        out.append(
            {
                "guid": guid(url, title),
                "title": title,
                "description": "",
                "link": url,
                "publisher": publisher,
                "symbols": [search.topic],
                "provider": "google_news",
                "matched": relevant(title, "", s),
                "event_time": when,
                "knowledge_time": now.isoformat(),
                "receipt_time": now.isoformat(),
            }
        )
    return out


def search_rss(search: Search, s: Setup, now: datetime) -> list[dict[str, Any]]:
    where = "&gl=IN&ceid=IN:en&hl=en-IN" if search.country == "IN" else "&gl=US&ceid=US:en&hl=en-US"
    q = urllib.parse.quote(f"{search.keywords} when:1d")
    # Google returns up to 100 a search; Currents 20. The same cap keeps a day's count
    # comparable whichever source answered (2026-11-04: 556 Google stories in one day).
    rows = parse_rss(news._open(f"https://news.google.com/rss/search?q={q}{where}"), search, s, now)
    return rows[: s.page_size]


def windows(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """[start, end) in spans Currents accepts, newest first."""
    out: list[tuple[datetime, datetime]] = []
    while end > start:
        out.append((max(start, end - SPAN), end))
        end -= SPAN
    return out


# --- the derived table ----------------------------------------------------------------------------


def held(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or DERIVED
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def merge(
    existing: Sequence[Mapping[str, Any]], rows: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """By guid, oldest event first; the first sighting's knowledge time and tone are kept."""
    by: dict[str, dict[str, Any]] = {str(r["guid"]): dict(r) for r in existing}
    for row in rows:
        prior = by.get(str(row["guid"]))
        if prior is None:
            by[str(row["guid"])] = dict(row)
            continue
        prior["symbols"] = sorted({*prior.get("symbols", []), *row.get("symbols", [])})
        if not prior.get("description") and row.get("description"):
            prior["description"] = row["description"]
            prior.pop("tone", None)
        if "newsdata_tone" in row and "newsdata_tone" not in prior:
            prior["newsdata_tone"] = row["newsdata_tone"]
    return sorted(by.values(), key=lambda r: (str(r["event_time"]), str(r["guid"])))


def score_missing(rows: list[dict[str, Any]], scorer: Scorer | None, model: str) -> int:
    """Tone for relevant rows that have none. Returns how many were scored."""
    todo = [r for r in rows if r.get("matched") and "tone" not in r]
    if not todo or scorer is None:
        return 0
    tones = scorer([text(r) for r in todo])
    for row, tone in zip(todo, tones, strict=True):
        row["tone"] = tone | {"model": model}
    return len(todo)


def text(row: Mapping[str, Any]) -> str:
    """What the tone model reads: the headline, then the summary."""
    d = str(row.get("description") or "")
    return f"{row['title']}. {d}" if d else str(row["title"])


def save(rows: Sequence[Mapping[str, Any]], path: Path | None = None) -> None:
    p = path or DERIVED
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".partial")
    tmp.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(p)


# --- one refresh ----------------------------------------------------------------------------------


def refresh(
    *,
    now: datetime | None = None,
    s: Setup | None = None,
    scorer: Scorer | None = None,
    model: str = "",
    path: Path | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Search every theme since the last story held (or `backfill_days`), land, merge, score."""
    now = now or datetime.now(UTC)
    s = s or setup()
    rows = held(path)
    latest = max((datetime.fromisoformat(str(r["event_time"])) for r in rows), default=None)
    start = (latest - timedelta(hours=6)) if latest else now - timedelta(days=s.backfill_days)
    # Currents refuses a search reaching past 30 days ("Max lookback is 30 days"): an hour's margin.
    start = max(start, now - timedelta(days=min(s.backfill_days, 30)) + timedelta(hours=1))
    key = api_key()
    nd_key = newsdata_key()
    nd_requests = 0
    found: list[dict[str, Any]] = []
    failed: list[str] = []
    requests = 0
    for search in s.searches:
        got: list[dict[str, Any]] = []
        worked = False
        for a, b in windows(start, now) if key else []:
            requests += 1
            try:
                got += search_currents(search, key, s, now, a, b)
                worked = True
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                code = getattr(exc, "code", "")
                failed.append(
                    f"{search.topic}/{search.keywords} {a.date()}: {type(exc).__name__} {code}".strip()
                )
        if not worked:
            try:
                got = search_rss(search, s, now)
            except (urllib.error.URLError, TimeoutError, OSError):
                failed.append(f"{search.topic}/{search.keywords}: google news failed too")
        if nd_key:
            nd_requests += 1
            try:
                got += search_newsdata(search, nd_key, s, now)
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                code = getattr(exc, "code", "")
                failed.append(
                    f"newsdata {search.topic}/{search.keywords}: {type(exc).__name__} {code}".strip()
                )
        found += got
    by_month: dict[str, list[dict[str, object]]] = {}
    for row in found:
        by_month.setdefault(str(row["event_time"])[:7], []).append(row)
    landed = 0
    for month, batch in sorted(by_month.items()):
        _, new = news._merge(news.month_path(CLASS, month, root=root or LANDING), batch)
        landed += new
    merged = merge(rows, found)
    scored = score_missing(merged, scorer, model)
    save(merged, path)
    return {
        "found": len(found),
        "new": len(merged) - len(rows),
        "landed": landed,
        "scored": scored,
        "requests": requests,
        "newsdata_requests": nd_requests,
        "failed": failed,
        "provider": "currents" if key else "google_news",
        "held": len(merged),
    }


def main() -> int:
    from eulerlab.forecast import news_rules, news_tone, stock_tone

    scorer = news_tone.scorer()
    out = refresh(scorer=scorer, model=news_tone.MODEL_ID if scorer else "")
    try:
        table = stock_tone.build(
            now=datetime.now(UTC),
            scorer=scorer,
            model=news_tone.MODEL_ID,
            rules=news_rules.all_rules(),
        )
        print(f"stock news: {len(table['stocks'])} stocks with headlines in {table['days']} days")
    except (OSError, ValueError, KeyError) as exc:
        print(f"stock news: not built ({type(exc).__name__}: {str(exc)[:100]})")
    print(
        f"market-news: {out['found']} found, {out['new']} new, {out['scored']} scored, "
        f"{out['requests']} {out['provider']} and {out['newsdata_requests']} newsdata requests, "
        f"{out['held']} held"
        + (f"; failed: {'; '.join(out['failed'])}" if out["failed"] else "")
        + ("" if scorer else "; tone model not installed (`uv sync --extra news`)")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
