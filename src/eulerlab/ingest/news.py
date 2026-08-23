"""Per-instrument news from Google News RSS, across every market we trade.

### Why this and not a vendor

Survey in `docs/RESEARCH/023`: no commercial provider covers India, US, crypto
and FX. The two that plausibly could — FMP and EODHD — put India behind a
paywall and will not let you verify it before paying (EODHD's demo key serves
`AAPL.US` and `BTC-USD.CC`, then 403s on `RELIANCE.NSE`).

Google News RSS covers all four, per instrument, keyless. Measured 2026-08-23:
100 items for Indian large-, mid- and small-caps, US equities, BTC, SOL, EURUSD
and USDINR. Twenty NSE symbols at six workers finished in **5.9 seconds, 20/20,
no throttling** — so `WORKERS = 6` is a measurement, not a guess.

### What it is not

Headlines and links. No article body, no sentiment, no symbol tagging. It is a
*search* feed, which means a badly built query returns a hundred irrelevant
stories rather than an error — a silent quality failure, and the main risk
this module has to manage.

### The query form is measured, and the result was not the obvious one

Two forms were compared over ten deliberately awkward tickers (ITC, LT, MRF,
BEL, SBIN, DIVISLAB…), scoring a story as relevant when its headline carries
either the ticker or a significant token of the registered company name:

    "{symbol} share price NSE"      88% relevant
    "{company name} share price"    83% relevant

The ticker wins. So the NSE name list is loaded for **scoring** relevance, not
for building the query — the reverse of what seemed obvious before measuring.

`SBIN` is the known floor at 8/20: the registered name is "State Bank of
India", the press writes "SBI", and no part of that abbreviation appears in
either the ticker or the name. Recorded rather than papered over — an
abbreviation table would be invented data unless sourced.

### Relevance is recorded, not enforced

Every item carries `matched`. Nothing is dropped for failing it: a story can
discuss a company without naming it in the headline, and silently discarding
those would be a second, invisible quality failure on top of the first.
Downstream filters on the flag; the rate is reported so it stays visible.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

LANDING = Path("data/landing/news")
NAMES_LANDING = Path("data/landing/names")
NAMES_DERIVED = Path("data/derived/nse_names.json")

FEED = "https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={gl}:{lang}"
EQUITY_LIST = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
)

WORKERS = 6
"""Measured clean at 20 symbols in 5.9s with zero failures. Not raised on
speculation: the ceiling above this is untested and Google publishes no limit
for this endpoint, so a higher number would be a guess dressed as a setting."""

QUOTES = ("USDT", "USDC", "BUSD", "USD", "INR", "EUR", "JPY", "GBP")
"""Quote currencies, longest first, so `BTCUSDT` splits before `BTCUSD` can."""

NAME_STOPWORDS = frozenset(
    {
        "limited",
        "ltd",
        "india",
        "indian",
        "company",
        "co",
        "corporation",
        "the",
        "of",
        "and",
        "industries",
        "enterprises",
        "services",
        "group",
    }
)
"""Dropped before name matching. "India" has to go or every Indian company
matches every story about the country."""


@dataclass(frozen=True)
class Query:
    """One instrument's search, and the locale to run it in."""

    symbol: str
    asset_class: str
    text: str
    hl: str = "en-IN"
    gl: str = "IN"

    @property
    def url(self) -> str:
        return FEED.format(
            q=urllib.parse.quote(self.text), hl=self.hl, gl=self.gl, lang=self.hl[:2]
        )


def query_for(symbol: str, asset_class: str) -> Query:
    """The search for one instrument.

    Equity uses the ticker plus an exchange word, which measured best. Crypto
    and FX are split into their legs because "EURUSD" is not a phrase anyone
    writes, while "EUR USD" is.
    """
    if asset_class == "crypto":
        base = symbol.upper()
        for quote in QUOTES:
            if base.endswith(quote) and len(base) > len(quote):
                base = base[: -len(quote)]
                break
        return Query(symbol, asset_class, f"{base} crypto price", "en-US", "US")

    if asset_class == "fx":
        pair = symbol.upper()
        if len(pair) == 6:
            return Query(symbol, asset_class, f"{pair[:3]} {pair[3:]} forex", "en-US", "US")
        return Query(symbol, asset_class, f"{pair} forex", "en-US", "US")

    if asset_class == "us_equity":
        return Query(symbol, asset_class, f"{symbol} stock", "en-US", "US")

    return Query(symbol, asset_class, f"{symbol} share price NSE", "en-IN", "IN")


def _open(url: str, *, timeout: int = 30, retries: int = 3) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return bytes(response.read())
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))
    return b""


def land_names(*, root: Path = NAMES_LANDING) -> Path:
    """Land NSE's official symbol → company name list, immutably by date."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"EQUITY_L-{datetime.now(UTC).date().isoformat()}.csv.gz"
    if path.exists():
        return path
    payload = _open(EQUITY_LIST)
    tmp = path.with_suffix(".partial")
    tmp.write_bytes(gzip.compress(payload))
    tmp.replace(path)
    return path


def build_names(*, root: Path = NAMES_LANDING) -> dict[str, str]:
    """Symbol → registered company name, from the newest landed list."""
    files = sorted(root.glob("EQUITY_L-*.csv.gz"))
    if not files:
        files = [land_names(root=root)]
    text = gzip.decompress(files[-1].read_bytes()).decode("utf-8", errors="replace")
    out: dict[str, str] = {}
    for row in csv.DictReader(io.StringIO(text)):
        symbol = (row.get("SYMBOL") or "").strip()
        # The column has no leading space, unlike every other column in this
        # file. Checked both spellings so a change at the source cannot
        # silently empty the mapping.
        name = (row.get("NAME OF COMPANY") or row.get(" NAME OF COMPANY") or "").strip()
        if symbol and name:
            out[symbol] = name
    return out


def load_names(path: Path = NAMES_DERIVED, *, root: Path = NAMES_LANDING) -> dict[str, str]:
    """The mapping, cached. Rebuilt from the landed list when absent."""
    if path.exists():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in loaded.items()}
    names = build_names(root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(names, indent=1, sort_keys=True), encoding="utf-8")
    return names


def name_tokens(name: str) -> tuple[str, ...]:
    """Tokens that count as naming an instrument, for relevance scoring.

    A pair name is matched **whole**, never by its legs. "EUR/GBP" split into
    `eur` and `gbp` would score the headline "EUR/USD and GBP/USD Outlook" as a
    EURGBP story, which it is not — the legs appear, the pair does not. That
    would inflate the match rate precisely where it is least deserved.
    """
    clean = name.strip().lower()
    if not clean:
        return ()
    if "/" in clean:
        return (clean,)
    words = [w for w in re.split(r"[^A-Za-z0-9]+", clean) if w]
    kept = [w for w in words if w not in NAME_STOPWORDS and len(w) > 2]
    # A name that is *entirely* stopwords keeps its raw words rather than
    # scoring nothing as relevant.
    return tuple(kept or words)


def names_for(asset_class: str, *, limit: int = 250) -> dict[str, str]:
    """The symbol → name table to score one asset class against.

    Equities come from NSE's registered-name list; crypto and FX from the
    catalog, which already carries the form the press actually writes —
    `EUR/USD` rather than `EURUSD`, `AAVE` rather than `AAVEUSDT`. Sourced
    either way: a hand-written coin-name table would be invented data.
    """
    if asset_class in ("equity", "us_equity"):
        return load_names()
    from eulerlab.strategies import catalog

    return {
        i.symbol: i.name for i in catalog.search(limit=limit, asset_class=asset_class) if i.name
    }


@dataclass(frozen=True)
class Item:
    """One story."""

    guid: str
    title: str
    link: str
    publisher: str
    symbols: tuple[str, ...]
    asset_class: str
    matched: bool
    """Whether the headline names the instrument, by ticker or company-name
    token. Recorded, never enforced — see the module docstring."""

    event_time: str
    knowledge_time: str
    """When we fetched it, not when it was published. Backdating knowledge to
    the publish stamp would let a backtest read a story before we had it."""

    receipt_time: str

    def to_row(self) -> dict[str, object]:
        return {
            "guid": self.guid,
            "title": self.title,
            "link": self.link,
            "publisher": self.publisher,
            "symbols": list(self.symbols),
            "asset_class": self.asset_class,
            "matched": self.matched,
            "event_time": self.event_time,
            "knowledge_time": self.knowledge_time,
            "receipt_time": self.receipt_time,
        }


def _published(raw: str) -> str:
    """RFC-822 pubDate into UTC ISO, or empty when unreadable."""
    try:
        return parsedate_to_datetime(raw).astimezone(UTC).isoformat()
    except (TypeError, ValueError):
        return ""


def parse_feed(
    payload: bytes, query: Query, names: dict[str, str], *, now: datetime | None = None
) -> list[Item]:
    """One RSS body into items. Unparseable entries are dropped, not defaulted."""
    stamp = (now or datetime.now(UTC)).isoformat()
    try:
        root = ET.fromstring(payload.decode("utf-8", errors="replace"))
    except ET.ParseError:
        return []

    tokens = (query.symbol.lower(), *name_tokens(names.get(query.symbol, "")))
    out: list[Item] = []
    for node in root.iterfind(".//item"):
        title = (node.findtext("title") or "").strip()
        when = _published((node.findtext("pubDate") or "").strip())
        if not title or not when:
            continue

        source = node.find("source")
        publisher = (source.text or "").strip() if source is not None else ""
        # Google formats titles as "Headline - Publisher". Trimming the
        # trailing publisher keeps the headline comparable across sources.
        headline = title
        if publisher and headline.endswith(f" - {publisher}"):
            headline = headline[: -len(publisher) - 3].strip()

        low = headline.lower()
        out.append(
            Item(
                guid=(node.findtext("guid") or node.findtext("link") or headline).strip(),
                title=headline,
                link=(node.findtext("link") or "").strip(),
                publisher=publisher,
                symbols=(query.symbol,),
                asset_class=query.asset_class,
                matched=any(t and t in low for t in tokens),
                event_time=when,
                knowledge_time=stamp,
                receipt_time=stamp,
            )
        )
    return out


def fetch(query: Query, names: dict[str, str], *, now: datetime | None = None) -> list[Item]:
    """One instrument's stories."""
    return parse_feed(_open(query.url), query, names, now=now)


def day_path(asset_class: str, day: str, *, root: Path = LANDING) -> Path:
    return root / asset_class / f"{day}.jsonl.gz"


def _merge(path: Path, rows: list[dict[str, object]]) -> tuple[int, int]:
    """Merge by guid into a day file. Returns (total, new).

    Symbols are **unioned** rather than overwritten. One story often surfaces
    under several instruments — a sector piece names four banks — and keeping
    only the last would silently unlink it from the other three.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, dict[str, object]] = {}
    if path.exists():
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    old = json.loads(line)
                except json.JSONDecodeError:
                    continue
                existing[str(old.get("guid", ""))] = old

    before = len(existing)
    for row in rows:
        guid = str(row.get("guid", ""))
        prior = existing.get(guid)
        if prior is not None:
            merged = sorted({*_as_list(prior.get("symbols")), *_as_list(row.get("symbols"))})
            row = {
                **row,
                "symbols": merged,
                # First sighting wins: a story found at 09:00 and again at
                # 15:00 under another ticker was knowable at 09:00.
                "knowledge_time": prior.get("knowledge_time", row["knowledge_time"]),
                "matched": bool(prior.get("matched")) or bool(row.get("matched")),
            }
        existing[guid] = row

    tmp = path.with_suffix(".partial")
    with gzip.open(tmp, "wt", encoding="utf-8") as handle:
        for row in sorted(existing.values(), key=lambda r: str(r.get("event_time", ""))):
            handle.write(json.dumps(row) + "\n")
    tmp.replace(path)
    return len(existing), len(existing) - before


def _as_list(value: object) -> list[str]:
    return [str(v) for v in value] if isinstance(value, list) else []


@dataclass
class LandResult:
    """What one sweep did."""

    symbols: int = 0
    failed: tuple[str, ...] = ()
    items: int = 0
    new: int = 0
    matched: int = 0

    @property
    def match_rate(self) -> float:
        return self.matched / self.items if self.items else 0.0


def land(
    symbols: list[str],
    asset_class: str = "equity",
    *,
    root: Path = LANDING,
    names: dict[str, str] | None = None,
    now: datetime | None = None,
) -> LandResult:
    """Sweep a list of instruments and merge what comes back.

    A symbol whose fetch fails is **named in `failed`**, not counted as zero.
    Zero would read as "no news about this company today", which is a claim
    this module is in no position to make.
    """
    table = names if names is not None else load_names()
    result = LandResult(symbols=len(symbols))

    def one(symbol: str) -> tuple[str, list[Item] | None]:
        try:
            return symbol, fetch(query_for(symbol, asset_class), table, now=now)
        except (urllib.error.URLError, TimeoutError, OSError):
            return symbol, None

    failed: list[str] = []
    by_day: dict[str, list[dict[str, object]]] = {}
    with ThreadPoolExecutor(WORKERS) as pool:
        for symbol, items in pool.map(one, symbols):
            if items is None:
                failed.append(symbol)
                continue
            for item in items:
                result.items += 1
                result.matched += int(item.matched)
                by_day.setdefault(item.event_time[:10], []).append(item.to_row())

    result.failed = tuple(failed)
    for day, rows in sorted(by_day.items()):
        _, new = _merge(day_path(asset_class, day, root=root), rows)
        result.new += new
    return result


def read_all(
    *, asset_class: str = "", root: Path = LANDING, allow_cloud: bool = True
) -> list[dict[str, object]]:
    """Every landed story, from disk or the bucket."""
    from eulerlab.ingest import landing_reader

    pattern = f"{asset_class}/*.jsonl.gz" if asset_class else "*/*.jsonl.gz"
    out: list[dict[str, object]] = []

    if allow_cloud:
        for relative in landing_reader.available("news", pattern):
            try:
                payload = gzip.decompress(landing_reader.read(relative))
            except (OSError, ValueError):
                continue
            out.extend(_lines(payload.decode("utf-8", errors="replace")))
        return out

    for path in sorted(root.glob(pattern)):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            out.extend(_lines(handle.read()))
    return out


def _lines(text: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in text.splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _main() -> None:
    """`make news` — sweep each asset class and report what landed."""
    import sys

    from eulerlab.strategies import catalog

    limit = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 25
    for asset_class in ("equity", "crypto", "fx"):
        symbols = [i.symbol for i in catalog.search(limit=limit, asset_class=asset_class)]
        if not symbols:
            print(f"  {asset_class:8s} no instruments")
            continue
        result = land(symbols, asset_class, names=names_for(asset_class))
        note = (
            f", {len(result.failed)} failed: {', '.join(result.failed[:4])}"
            if result.failed
            else ""
        )
        print(
            f"  {asset_class:8s} {result.symbols:>3} symbols  "
            f"{result.items:>5} items  {result.new:>5} new  "
            f"{result.match_rate:5.0%} on-topic{note}"
        )


if __name__ == "__main__":
    _main()
