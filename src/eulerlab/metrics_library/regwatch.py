"""The regulator watch: SEBI, RBI and NSE feeds landed daily, new items found (ADR-104).

Each feed in `config/knowledge_sources.yaml` is fetched once per IST day and
landed unedited under `data/landing/regwatch/` (one file per feed per day,
read-only, in the manifest). Its items are compared with every item seen
before, kept in `data/derived/regwatch_items.jsonl` (append-only, each row with
the item's own date as `event_time` and the landing time as `knowledge_time`).
A new item is linked to the metric pages its words match, by the topic list.

What an item says is untrusted text from a web feed: it is shown and linked,
never followed.
"""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import BaseModel, ConfigDict, Field

from eulerlab.config import CONFIG_DIR
from eulerlab.ingest.fetch import FetchResult, Outcome
from eulerlab.ingest.landing import Landing

LANDING = Path("data/landing/regwatch")
ITEMS = Path("data/derived/regwatch_items.jsonl")
TAG = re.compile(r"<[^>]+>")


class Getter(Protocol):
    """What `watch` needs from a fetcher: `ingest.fetch.Fetcher` is one."""

    def get(self, url: str) -> FetchResult: ...


class Feed(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,40}$")
    title: str
    url: str = Field(pattern=r"^https://")


class Topic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    keywords: list[str]
    pages: list[str]


class Sources(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    feeds: list[Feed]
    topics: list[Topic] = Field(default_factory=list)
    skip_titles: list[str] = Field(default_factory=list)


def load_sources(config_dir: Path | None = None) -> Sources:
    path = (config_dir or CONFIG_DIR) / "knowledge_sources.yaml"
    return Sources.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


@dataclass(frozen=True)
class FeedItem:
    feed: str
    title: str
    link: str
    published: str
    """The item's own date, ISO, or '' when the feed gives none."""
    summary: str
    key: str
    pages: list[str] = field(default_factory=list)


def _text(node: ET.Element | None) -> str:
    if node is None or node.text is None:
        return ""
    return " ".join(TAG.sub(" ", node.text).split())


def _date(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    try:
        return parsedate_to_datetime(raw).date().isoformat()
    except (TypeError, ValueError, IndexError):
        pass
    # SEBI writes "30 Oct, 2026 +0530".
    for fmt in ("%d %b, %Y", "%d %b %Y"):
        try:
            parsed = datetime.strptime(raw.split(" +")[0].strip(), fmt).replace(tzinfo=UTC)
            return parsed.date().isoformat()
        except ValueError:
            continue
    return ""


def parse(feed: str, payload: bytes) -> list[FeedItem] | None:
    """RSS 2.0 items, or None when the payload is not a feed we can read.

    A document type declaration is refused outright: feeds do not need one, and
    refusing it closes the door on entity-expansion tricks in untrusted XML.
    """
    head = payload[:2048].lower()
    if b"<!doctype" in head or b"<!entity" in payload.lower():
        return None
    try:
        root = ET.fromstring(payload.lstrip(b"\xef\xbb\xbf").strip())
    except ET.ParseError:
        return None
    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        return None
    out: list[FeedItem] = []
    for node in channel.findall("item"):
        title = _text(node.find("title"))
        link = _text(node.find("link"))
        if not title:
            continue
        identity = link or title
        out.append(
            FeedItem(
                feed=feed,
                title=title[:300],
                link=link[:500],
                published=_date(_text(node.find("pubDate"))),
                summary=_text(node.find("description"))[:600],
                key=hashlib.sha256(f"{feed}|{identity}".encode()).hexdigest()[:16],
            )
        )
    return out


def _matches(keyword: str, text: str) -> bool:
    word = re.escape(keyword.lower())
    return re.search(rf"(?<![a-z0-9]){word}", text) is not None


def link_pages(
    item: FeedItem, topics: Sequence[Topic], skip_titles: Sequence[str] = ()
) -> list[str]:
    """Pages whose topic words appear in the item's title. Descriptions are not read."""
    if any(item.title.lower().startswith(s.lower()) for s in skip_titles):
        return []
    text = item.title.lower()
    pages: list[str] = []
    for topic in topics:
        if any(_matches(k, text) for k in topic.keywords):
            pages += [p for p in topic.pages if p not in pages]
    return pages


def seen(path: Path | None = None) -> dict[str, dict[str, Any]]:
    path = path or ITEMS
    out: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("key"):
            out[str(row["key"])] = row
    return out


def record(
    items: Iterable[FeedItem],
    knowledge_time: str,
    path: Path | None = None,
    *,
    baseline: bool = False,
) -> None:
    """Append items. `baseline` marks what a feed already listed on the first run: never news."""
    path = path or ITEMS
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for item in items:
            row = asdict(item)
            row["event_time"] = item.published or knowledge_time[:10]
            row["knowledge_time"] = knowledge_time
            row["baseline"] = baseline
            handle.write(json.dumps(row, sort_keys=True) + "\n")


@dataclass
class WatchResult:
    new: list[FeedItem] = field(default_factory=list)
    status: dict[str, str] = field(default_factory=dict)
    """Per feed: downloaded, skipped (already landed today), failed or unreadable."""


def watch(
    fetcher: Getter,
    sources: Sources,
    *,
    today: date,
    landing: Landing | None = None,
    items_path: Path | None = None,
    knowledge_time: str,
) -> WatchResult:
    """Fetch and land each feed once today, then record and return the items not seen before."""
    landing = landing or Landing(LANDING)
    items_path = items_path or ITEMS
    known = seen(items_path)
    baseline = not known
    result = WatchResult()
    for feed in sources.feeds:
        held = landing.entries().get((today.isoformat(), feed.name))
        if held is not None and (landing.root / held.path).exists():
            payload = (landing.root / held.path).read_bytes()
            result.status[feed.name] = "skipped"
        else:
            got = fetcher.get(feed.url)
            if got.outcome is not Outcome.OK or got.payload is None:
                result.status[feed.name] = f"failed ({got.detail or got.status})"
                continue
            payload = got.payload
            parsed_check = parse(feed.name, payload)
            if parsed_check is None:
                result.status[feed.name] = "unreadable (not an RSS feed)"
                continue
            landing.write(
                trade_date=today,
                segment=feed.name,
                file_format="rss",
                url=feed.url,
                payload=payload,
                rows=len(parsed_check),
                inner_name=f"{feed.name}_{today.isoformat()}.xml",
                suffix="xml",
            )
            result.status[feed.name] = "downloaded"
        parsed = parse(feed.name, payload) or []
        fresh = []
        for item in parsed:
            if item.key in known:
                continue
            linked = FeedItem(
                **{**asdict(item), "pages": link_pages(item, sources.topics, sources.skip_titles)}
            )
            fresh.append(linked)
            known[item.key] = asdict(linked)
        record(fresh, knowledge_time, items_path, baseline=baseline)
        result.new += fresh
    return result


def summarise(items: Sequence[FeedItem], first_run: bool) -> Mapping[str, Any]:
    """Counts for the run's summary line."""
    linked = [i for i in items if i.pages]
    return {"new": len(items), "linked": len(linked), "first_run": first_run}
