"""Financial Modeling Prep: news, and a prober that measures what a key unlocks.

### The free plan does not include news

Read off FMP's own pricing page on 2026-08-23, the Basic (free) plan is:

- **250 calls per day**, and a trailing 500 MB per 30 days
- **End-of-day** timeframe, not real-time
- **5 years** of history
- Profile and reference data

"Financial Market News" and "Crypto and Forex" are both listed one tier up, on
Starter ($22/mo). So the news endpoints this module wraps are, on the published
plan matrix, *the one thing the free tier excludes*.

That is what the page says. It is not what this module assumes. Vendors move
endpoints between tiers and pricing pages go stale, so `probe()` asks the API
itself and reports what actually answers. Use the measurement, not the table.

### The budget is the design constraint

250 calls a day is small enough that it shapes the code rather than sitting in
a comment. A fifteen-minute poll of a single endpoint is 96 calls — two such
polls and the day is gone. So every request goes through `_get`, which counts,
and `land_news` takes an explicit `budget` and stops when it is reached rather
than discovering the ceiling as a 429 halfway through a merge.

Paging is where this bites hardest: `limit` caps at 250 per call, so a wide
backfill is not a slow operation here, it is an impossible one.

### Bitemporal, and honest about knowledge_time

An article carries `publishedDate` — when it went out — which is `event_time`.
`knowledge_time` is the fetch, not the publish: we could not have known the
story until we pulled it, and backdating knowledge to the publish stamp is
exactly the leak the read API exists to prevent. For a poll running every few
hours the two differ by hours, and that gap is real.
"""

from __future__ import annotations

import gzip
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

LANDING = Path("data/landing/fmpnews")
BASE = "https://financialmodelingprep.com/stable/"
KEY_VAR = "FMP_API_KEY"
USER_AGENT = "eulerlab/1.0"

MAX_LIMIT = 250
"""Largest `limit` the news endpoints accept per call."""

FREE_DAILY_CALLS = 250
"""Basic-plan ceiling, from the pricing page on 2026-08-23. Also the reason
`land_news` takes a budget: the ceiling is low enough to hit by accident."""


class MissingKey(RuntimeError):
    """No API key configured. Raised rather than returning empty.

    An empty list would read as "no news today", which is a different and much
    worse statement than "we never asked".
    """


def api_key() -> str:
    """The key, from the environment or `.env`. Never logged, never returned
    in an API response — same handling as every other credential here."""
    key = os.environ.get(KEY_VAR, "").strip()
    if key:
        return key
    env = Path(".env")
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == KEY_VAR:
                return value.strip().strip('"').strip("'")
    raise MissingKey(
        f"{KEY_VAR} is not set. Add it to .env — a free key comes from "
        "https://site.financialmodelingprep.com/developer/docs"
    )


def key_present() -> bool:
    """Whether a key is configured, without revealing it."""
    try:
        return bool(api_key())
    except MissingKey:
        return False


CALLS = 0
"""Requests made this process. Counted because the daily budget is 250 and a
loop that quietly spends it leaves nothing for the rest of the day."""


def _get(endpoint: str, params: dict[str, object], *, timeout: int = 30) -> object:
    """One call, with the key appended and the counter incremented."""
    global CALLS
    query = {k: str(v) for k, v in params.items() if v is not None}
    query["apikey"] = api_key()
    url = BASE + endpoint + "?" + urllib.parse.urlencode(query)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    CALLS += 1
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


NEWS_ENDPOINTS = {
    "general": "news/general-latest",
    "stock": "news/stock-latest",
    "press": "news/press-releases-latest",
    "crypto": "news/crypto-latest",
    "forex": "news/forex-latest",
    "articles": "fmp-articles",
}
"""The feeds worth landing, from the documented endpoint list (258 endpoints,
read 2026-08-23). Keyed by the short name used in file paths."""

PROBE_ENDPOINTS: tuple[tuple[str, str, dict[str, object]], ...] = (
    ("news: general", "news/general-latest", {"limit": 1}),
    ("news: stock", "news/stock-latest", {"limit": 1}),
    ("news: press releases", "news/press-releases-latest", {"limit": 1}),
    ("news: crypto", "news/crypto-latest", {"limit": 1}),
    ("news: forex", "news/forex-latest", {"limit": 1}),
    ("news: by symbol", "news/stock", {"symbols": "AAPL", "limit": 1}),
    ("news: FMP articles", "fmp-articles", {"limit": 1}),
    ("quote", "quote", {"symbol": "AAPL"}),
    ("quote: index", "quote", {"symbol": "^GSPC"}),
    ("quote: forex", "quote", {"symbol": "EURUSD"}),
    ("quote: crypto", "quote", {"symbol": "BTCUSD"}),
    ("movers: gainers", "biggest-gainers", {}),
    ("movers: losers", "biggest-losers", {}),
    ("movers: most active", "most-actives", {}),
    ("sector performance", "sector-performance-snapshot", {"date": "2026-08-21"}),
    ("industry performance", "industry-performance-snapshot", {"date": "2026-08-21"}),
    ("sector PE", "sector-pe-snapshot", {"date": "2026-08-21"}),
    ("economic calendar", "economic-calendar", {"from": "2026-08-20", "to": "2026-08-28"}),
    ("earnings calendar", "earnings-calendar", {"from": "2026-08-20", "to": "2026-08-28"}),
    ("treasury rates", "treasury-rates", {"from": "2026-08-01", "to": "2026-08-22"}),
    ("economic indicators", "economic-indicators", {"name": "GDP"}),
    ("EOD prices", "historical-price-eod/light", {"symbol": "AAPL"}),
    ("company profile", "profile", {"symbol": "AAPL"}),
    ("symbol search", "search-symbol", {"query": "RELIANCE"}),
    ("market hours", "exchange-market-hours", {"exchange": "NASDAQ"}),
)
"""What to ask the key about.

Chosen as the endpoints this platform would actually use — the news feeds the
operator asked for, plus the snapshot's existing gaps (index levels, live
quotes, movers) and the reference data that is plausibly free. Twenty-five
calls, so a probe costs a tenth of a free day's budget.
"""


@dataclass(frozen=True)
class ProbeResult:
    """What one endpoint answered."""

    label: str
    endpoint: str
    status: int
    """HTTP status. 200 is access; 401/402/403 is the plan refusing."""

    rows: int = 0
    fields: tuple[str, ...] = ()
    detail: str = ""

    @property
    def allowed(self) -> bool:
        return self.status == 200

    @property
    def empty_but_allowed(self) -> bool:
        """Answered, but with nothing in it.

        Worth separating: an endpoint that returns `[]` on the free plan is not
        the same as one that returns data, and calling both "available" would
        overstate what the key buys.
        """
        return self.status == 200 and self.rows == 0


def probe(
    endpoints: tuple[tuple[str, str, dict[str, object]], ...] = PROBE_ENDPOINTS,
) -> list[ProbeResult]:
    """Ask the API what this key can actually reach.

    Reports the plan's refusal as a status rather than raising, because the
    refusals are the finding: which endpoints 402 is precisely the shape of the
    free tier, and a probe that stopped at the first one would measure nothing.
    """
    out: list[ProbeResult] = []
    for label, endpoint, params in endpoints:
        try:
            payload = _get(endpoint, params)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:160]
            out.append(
                ProbeResult(label, endpoint, exc.code, detail=body.replace("\n", " ").strip())
            )
            continue
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            out.append(ProbeResult(label, endpoint, 0, detail=f"{type(exc).__name__}: {exc}"))
            continue

        if isinstance(payload, list):
            rows = len(payload)
            first = payload[0] if payload and isinstance(payload[0], dict) else {}
        elif isinstance(payload, dict):
            rows, first = 1, payload
        else:
            rows, first = 0, {}
        out.append(ProbeResult(label, endpoint, 200, rows=rows, fields=tuple(sorted(first))[:12]))
        # Gentle on the wire: the free plan is a daily cap, not a rate cap, but
        # twenty-five requests in a burst is a poor way to introduce yourself.
        time.sleep(0.2)
    return out


@dataclass(frozen=True)
class Article:
    """One news item, with its provenance attached."""

    title: str
    publisher: str
    url: str
    symbol: str
    text: str
    site: str
    image: str
    feed: str
    """Which endpoint it came from — `general`, `stock`, `crypto`, `forex`,
    `press`, `articles`. Kept because a press release and a wire story are
    different kinds of claim and should never silently merge into "news"."""

    event_time: str
    """When it was published."""

    knowledge_time: str
    """When we fetched it. Deliberately not the publish stamp: we did not know
    the story until we pulled it, and pretending otherwise is the exact leak
    the `as_of` read API is built to make impossible."""

    receipt_time: str

    @property
    def key(self) -> str:
        """URL where there is one, else title plus timestamp.

        The URL is the only genuinely unique field: the same story runs under
        the same headline on a dozen sites, and the same site re-publishes with
        an edited title. Falling back to title+time keeps a URL-less row from
        colliding with every other URL-less row.
        """
        return self.url.strip() or f"{self.event_time}|{self.title}"

    def to_row(self) -> dict[str, object]:
        return {
            "title": self.title,
            "publisher": self.publisher,
            "url": self.url,
            "symbol": self.symbol,
            "text": self.text,
            "site": self.site,
            "image": self.image,
            "feed": self.feed,
            "event_time": self.event_time,
            "knowledge_time": self.knowledge_time,
            "receipt_time": self.receipt_time,
            "key": self.key,
        }


def _stamp(value: object) -> str:
    """A published date into UTC ISO, or empty when it cannot be read.

    FMP writes `2026-08-22 14:30:00` without a zone. Read as UTC, which is what
    their timestamps are, and recorded rather than corrected — a guessed local
    zone would be a fabricated field.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    for form in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, form).replace(tzinfo=UTC).isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw).astimezone(UTC).isoformat()
    except ValueError:
        return ""


def to_articles(
    raw: list[dict[str, object]], feed: str, *, now: datetime | None = None
) -> list[Article]:
    """Raw feed rows into records. Rows without a title or date are dropped.

    Dropped rather than defaulted, for the same reason the FX parser drops
    unreadable bars: an absent row shows up in the count, an invented one does
    not.
    """
    stamp = (now or datetime.now(UTC)).isoformat()
    out: list[Article] = []
    for row in raw:
        title = str(row.get("title") or "").strip()
        when = _stamp(row.get("publishedDate") or row.get("date"))
        if not title or not when:
            continue
        out.append(
            Article(
                title=title,
                publisher=str(row.get("publisher") or row.get("site") or "").strip(),
                url=str(row.get("url") or row.get("link") or "").strip(),
                symbol=str(row.get("symbol") or "").strip(),
                text=str(row.get("text") or row.get("content") or "").strip()[:2000],
                site=str(row.get("site") or "").strip(),
                image=str(row.get("image") or "").strip(),
                feed=feed,
                event_time=when,
                knowledge_time=stamp,
                receipt_time=stamp,
            )
        )
    return out


def day_path(feed: str, day: str, *, root: Path = LANDING) -> Path:
    """One file per feed per publication day."""
    return root / feed / f"{day}.jsonl.gz"


def _merge(path: Path, rows: list[dict[str, object]]) -> tuple[int, int]:
    """Merge rows into a day file by key. Returns (total, new)."""
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
                existing[str(old.get("key", ""))] = old

    before = len(existing)
    for row in rows:
        key = str(row.get("key", ""))
        # First fetch wins on knowledge_time: a story seen at 09:00 and again
        # at 15:00 was known at 09:00, and overwriting would quietly move the
        # moment we could first have acted six hours later.
        if key in existing:
            row = {
                **row,
                "knowledge_time": existing[key].get("knowledge_time", row["knowledge_time"]),
            }
        existing[key] = row

    tmp = path.with_suffix(".partial")
    with gzip.open(tmp, "wt", encoding="utf-8") as handle:
        for row in sorted(existing.values(), key=lambda r: str(r.get("event_time", ""))):
            handle.write(json.dumps(row) + "\n")
    tmp.replace(path)
    return len(existing), len(existing) - before


def land_news(
    feeds: tuple[str, ...] = ("general", "stock", "press"),
    *,
    limit: int = MAX_LIMIT,
    budget: int = 20,
    root: Path = LANDING,
    now: datetime | None = None,
) -> dict[str, tuple[int, int]]:
    """Fetch each feed's latest page and merge it. Returns feed -> (total, new).

    `budget` is a hard call ceiling, checked before each request. On a 250-call
    day an unbounded loop is not a performance problem, it is the whole day.

    A feed the plan refuses is recorded as `(-1, -1)` and the others still run:
    if news is a paid tier, that is a fact to report once, not a reason to land
    nothing.
    """
    spent = 0
    out: dict[str, tuple[int, int]] = {}
    for feed in feeds:
        endpoint = NEWS_ENDPOINTS.get(feed)
        if endpoint is None or spent >= budget:
            continue
        try:
            payload = _get(endpoint, {"limit": min(limit, MAX_LIMIT), "page": 0})
        except urllib.error.HTTPError as exc:
            out[feed] = (-1, -1) if exc.code in (401, 402, 403) else (0, 0)
            spent += 1
            continue
        spent += 1
        rows = payload if isinstance(payload, list) else []
        articles = to_articles([r for r in rows if isinstance(r, dict)], feed, now=now)

        by_day: dict[str, list[dict[str, object]]] = {}
        for article in articles:
            by_day.setdefault(article.event_time[:10], []).append(article.to_row())

        total = new = 0
        for day, day_rows in sorted(by_day.items()):
            a, b = _merge(day_path(feed, day, root=root), day_rows)
            total += a
            new += b
        out[feed] = (total, new)
    return out


def read_all(*, root: Path = LANDING, allow_cloud: bool = True) -> list[dict[str, object]]:
    """Every landed article, from disk or the bucket."""
    from eulerlab.ingest import landing_reader

    out: list[dict[str, object]] = []
    if allow_cloud:
        paths = landing_reader.available("fmpnews", "*/*.jsonl.gz")
        for relative in paths:
            try:
                payload = landing_reader.read(relative)
            except (OSError, ValueError):
                continue
            for line in gzip.decompress(payload).decode("utf-8").splitlines():
                if line.strip():
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return out

    for path in sorted(root.glob("*/*.jsonl.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    return out


def _report_probe() -> None:
    """Print what the configured key reaches. `make fmp-probe`."""
    results = probe()
    allowed = [r for r in results if r.allowed and not r.empty_but_allowed]
    empty = [r for r in results if r.empty_but_allowed]
    denied = [r for r in results if not r.allowed]

    print(f"probed {len(results)} endpoints, {CALLS} calls spent\n")
    print(f"REACHABLE WITH DATA ({len(allowed)})")
    for r in allowed:
        print(f"  {r.label:24s} {r.rows:>4} rows  {', '.join(r.fields[:6])}")
    if empty:
        print(f"\nANSWERED BUT EMPTY ({len(empty)})")
        for r in empty:
            print(f"  {r.label:24s} 200, zero rows")
    if denied:
        print(f"\nREFUSED ({len(denied)})")
        for r in denied:
            print(f"  {r.label:24s} {r.status}  {r.detail[:70]}")


if __name__ == "__main__":
    import sys

    if not key_present():
        print(f"{KEY_VAR} is not set in .env — nothing to probe.")
        sys.exit(1)
    if "--probe" in sys.argv:
        _report_probe()
    else:
        landed = land_news()
        for feed, (total, new) in sorted(landed.items()):
            if total < 0:
                print(f"  {feed:10s} refused by plan")
            else:
                print(f"  {feed:10s} {total:>5} in file, {new:>4} new")
        print(f"{CALLS} calls spent of {FREE_DAILY_CALLS}/day")
