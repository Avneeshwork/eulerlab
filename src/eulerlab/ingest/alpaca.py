"""US market data from Alpaca — bars, news and corporate actions.

### Why Alpaca for the US

Measured 2026-08-24 (docs/RESEARCH/024): multi-symbol bars back to at least
2016, news carrying the article body and publisher-assigned tickers, and
corporate actions — all on the keys already in `.env`. FMP's free plan answers
**402** on every news endpoint and costs one call per symbol for EOD, which is
what kept a US panel out of reach on a 250-a-day budget.

The keys are **paper** keys: `paper-api` returns an account, `api` returns 401.
Market data is unaffected, and orders can only ever reach the paper venue,
which is the right way round for a platform whose deploy path defaults to
paper.

### On the S&P 500 list specifically

The constituent list is landed as a **dated snapshot** and is deliberately not
used to select a backtest universe. ADR-008 rejects published index membership
for exactly this reason: today's list applied across history silently drops
every company that was removed, and a strategy tested on the survivors looks
better than it was. The tradable universe is ranked from landed turnover, the
same way `all_liquid` is built for NSE.

So the list answers "what is in the index today", and never "what was in it in
2019".
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

LANDING = Path("data/landing/us")
DATA = "https://data.alpaca.markets"
PAPER = "https://paper-api.alpaca.markets"

KEY_VAR = "Alpaca_Key"
SECRET_VAR = "Alpaca_Secret"

BAR_BATCH = 100
"""Symbols per bars request. The endpoint is multi-symbol and paginates by
`next_page_token`; batching is what turns a 500-name universe from five hundred
calls into five."""

PAGE_LIMIT = 10_000
"""Rows per page. Alpaca caps at 10,000 and returns a token for the rest."""


class MissingKey(RuntimeError):
    """No Alpaca credentials. Raised rather than returning empty, because an
    empty result reads as "the market did nothing", which is a different and
    much worse claim than "we never asked"."""


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    env = Path(".env")
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            key, _, raw = line.partition("=")
            if key.strip() == name:
                return raw.strip().strip('"').strip("'")
    return ""


def headers() -> dict[str, str]:
    key, secret = _env(KEY_VAR), _env(SECRET_VAR)
    if not key or not secret:
        raise MissingKey(f"{KEY_VAR} and {SECRET_VAR} must be set (see .env.example)")
    return {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "User-Agent": "eulerlab/1.0",
        "Accept": "application/json",
    }


def keys_present() -> bool:
    return bool(_env(KEY_VAR) and _env(SECRET_VAR))


def _get(url: str, *, timeout: int = 45, retries: int = 3) -> dict[str, object]:
    """One request, with backoff. 429 is retried; 4xx otherwise is not."""
    request = urllib.request.Request(url, headers=headers())
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                return payload if isinstance(payload, dict) else {}
        except urllib.error.HTTPError as exc:
            # 429 is the documented rate limit and is worth waiting out. A 403
            # or 422 will not improve on a retry and is raised immediately.
            if exc.code != 429 or attempt == retries - 1:
                raise
            time.sleep(5 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries - 1:
                raise
            time.sleep(3 * (attempt + 1))
    return {}


def _paged(url: str, key: str) -> list[dict[str, object]]:
    """Follow `next_page_token` until the server stops offering one."""
    out: list[dict[str, object]] = []
    token = ""
    while True:
        page = _get(url + (f"&page_token={urllib.parse.quote(token)}" if token else ""))
        rows = page.get(key)
        if isinstance(rows, list):
            out.extend(r for r in rows if isinstance(r, dict))
        nxt = page.get("next_page_token")
        if not isinstance(nxt, str) or not nxt:
            return out
        token = nxt


@dataclass(frozen=True)
class Bar:
    """One OHLCV bar, with its provenance."""

    symbol: str
    day: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    trades: int
    vwap: float
    knowledge_time: str

    def to_row(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "event_time": self.day,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "trades": self.trades,
            "vwap": self.vwap,
            "knowledge_time": self.knowledge_time,
        }


def daily_bars(
    symbols: list[str], *, start: str, end: str = "", feed: str = "iex"
) -> tuple[dict[str, list[Bar]], str]:
    """Daily bars for many symbols. Returns (by symbol, error).

    `feed` defaults to **iex** rather than `sip`. Both answered when probed,
    which is surprising because SIP is the paid consolidated tape — and
    building a backfill on what may be an entitlement accident is a poor
    foundation. IEX is a subset of the tape and is unambiguously included; the
    difference is volume coverage, not price validity, and it is stated here
    rather than discovered later.
    """
    if not symbols:
        return {}, ""

    stamp = datetime.now(UTC).isoformat()
    out: dict[str, list[Bar]] = {}
    for index in range(0, len(symbols), BAR_BATCH):
        batch = symbols[index : index + BAR_BATCH]
        query = urllib.parse.urlencode(
            {
                "symbols": ",".join(batch),
                "timeframe": "1Day",
                "start": start,
                "limit": PAGE_LIMIT,
                "feed": feed,
                "adjustment": "raw",
                **({"end": end} if end else {}),
            }
        )
        # Paged, because the server caps a response at PAGE_LIMIT rows and
        # hands back a token for the rest. Reading one page looked like it
        # worked — twenty symbols returned exactly 10,000 bars, which is the
        # cap rather than the answer, and four symbols got nothing at all
        # because the first sixteen used the budget up.
        collected: dict[str, list[dict[str, object]]] = {}
        token = ""
        while True:
            url = f"{DATA}/v2/stocks/bars?{query}"
            if token:
                url += f"&page_token={urllib.parse.quote(token)}"
            try:
                page = _get(url)
            except Exception as exc:
                return out, f"{type(exc).__name__}: {str(exc)[:110]}"

            bars_page = page.get("bars")
            if isinstance(bars_page, dict):
                for symbol, rows in bars_page.items():
                    if isinstance(rows, list):
                        collected.setdefault(str(symbol), []).extend(
                            r for r in rows if isinstance(r, dict)
                        )
            nxt = page.get("next_page_token")
            if not isinstance(nxt, str) or not nxt:
                break
            token = nxt

        bars: object = collected
        if not isinstance(bars, dict):
            continue
        for symbol, rows in bars.items():
            if not isinstance(rows, list):
                continue
            kept: list[Bar] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    kept.append(
                        Bar(
                            symbol=str(symbol),
                            day=str(row["t"])[:10],
                            open=float(row["o"]),
                            high=float(row["h"]),
                            low=float(row["l"]),
                            close=float(row["c"]),
                            volume=float(row.get("v", 0.0)),
                            trades=int(row.get("n", 0)),
                            vwap=float(row.get("vw", 0.0)),
                            knowledge_time=stamp,
                        )
                    )
                except (KeyError, TypeError, ValueError):
                    # A malformed bar is dropped, never defaulted. A zero close
                    # is a stock that went to nothing, which is a claim.
                    continue
            if kept:
                out.setdefault(str(symbol), []).extend(kept)
    return out, ""


def bars_path(symbol: str, month: str, *, root: Path = LANDING) -> Path:
    return root / "bars" / symbol / f"{month}.jsonl.gz"


def _merge(path: Path, rows: list[dict[str, object]], key: str) -> tuple[int, int]:
    """Merge rows into a file by `key`. Returns (total, new)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, dict[str, object]] = {}
    if path.exists():
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    try:
                        old = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    existing[str(old.get(key, ""))] = old

    before = len(existing)
    for row in rows:
        existing[str(row.get(key, ""))] = row

    tmp = path.with_suffix(".partial")
    with gzip.open(tmp, "wt", encoding="utf-8") as handle:
        for row in sorted(existing.values(), key=lambda r: str(r.get(key, ""))):
            handle.write(json.dumps(row) + "\n")
    tmp.replace(path)
    return len(existing), len(existing) - before


def land_bars(
    symbols: list[str], *, start: str, end: str = "", root: Path = LANDING
) -> tuple[int, int, str]:
    """Fetch and land daily bars. Returns (symbols written, rows new, error)."""
    fetched, error = daily_bars(symbols, start=start, end=end)
    written = new = 0
    for symbol, bars in fetched.items():
        by_month: dict[str, list[dict[str, object]]] = {}
        for bar in bars:
            by_month.setdefault(bar.day[:7], []).append(bar.to_row())
        touched = False
        for month, rows in sorted(by_month.items()):
            _, added = _merge(bars_path(symbol, month, root=root), rows, "event_time")
            new += added
            touched = True
        written += int(touched)
    return written, new, error


SP500_SOURCE = (
    "https://en.wikipedia.org/w/api.php?action=parse"
    "&page=List_of_S%26P_500_companies&prop=wikitext&section=1&format=json"
)


def sp500_snapshot() -> tuple[list[dict[str, str]], str]:
    """Today's S&P 500 constituents. Returns (rows, error).

    From Wikipedia because it is keyless and current; FMP has the same list on
    its free tier and was rate limited when this was written, so the fallback
    became the primary.

    **This is a snapshot, not a history.** ADR-008 rejects published index
    membership for backtest universes: applying today's list across past years
    silently drops every company that was removed, and a strategy tested only
    on the survivors reads better than it was. Landed dated, so a year of daily
    runs accumulates the changes; used for labelling, never for selection.
    """
    import re

    request = urllib.request.Request(
        SP500_SOURCE,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
            )
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        text = payload["parse"]["wikitext"]["*"]
    except Exception as exc:
        return [], f"{type(exc).__name__}: {str(exc)[:100]}"

    stamp = datetime.now(UTC).isoformat()
    rows: list[dict[str, str]] = []

    # The ticker is wrapped in an exchange template, not written bare:
    #   || {{NasdaqSymbol|AAPL}}
    #   || [[Apple Inc.]]
    #   || Information Technology
    # Matching a bare upper-case cell found nothing at all, which is how the
    # first version of this parser landed zero constituents while reporting
    # success on 84,000 characters of wikitext.
    for block in text.split("\n|-"):
        ticker = re.search(r"\{\{(?:Nasdaq|Nyse|BATS|NYSEArca)Symbol\|([A-Z.\-]{1,7})\}\}", block)
        if not ticker:
            continue
        cells = [c.strip() for c in block.split("\n||")]
        name = sector = ""
        if len(cells) > 2:
            name = re.sub(r"[\[\]]", "", cells[2]).split("|")[-1].strip()
        if len(cells) > 3:
            sector = re.sub(r"[\[\]]", "", cells[3]).split("|")[-1].strip()
        rows.append(
            {
                "symbol": ticker.group(1),
                "name": name[:80],
                "sector": sector[:60],
                "knowledge_time": stamp,
            }
        )
    return rows, "" if rows else "parsed no constituents"


def land_sp500(*, root: Path = LANDING) -> tuple[int, str]:
    """Land today's constituent snapshot. Returns (rows, error)."""
    rows, error = sp500_snapshot()
    if not rows:
        return 0, error
    day = datetime.now(UTC).date().isoformat()
    path = root / "sp500" / f"{day}.jsonl.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".partial")
    with gzip.open(tmp, "wt", encoding="utf-8") as handle:
        for row in sorted(rows, key=lambda r: r["symbol"]):
            handle.write(json.dumps(row) + "\n")
    tmp.replace(path)
    return len(rows), error


def sp500_symbols(*, root: Path = LANDING, allow_cloud: bool = True) -> list[str]:
    """Symbols from the newest landed snapshot, disk or bucket.

    Reads the bucket too. The local-only version returned an empty list the
    moment `prune-local` moved the snapshot to B2, and every caller treated
    empty as "no work to do" — `land_actions` exited on `if not symbols` and
    **reported success having fetched nothing**.

    That is the fourth reader in this codebase written against the disk alone,
    after the catalog, `crypto_daily` and `indices.load`. Each one works right
    up until the prune, which is the step that proves the data is safe.
    """
    folder = root / "sp500"
    files = sorted(folder.glob("????-??-??.jsonl.gz")) if folder.exists() else []

    payloads: list[bytes] = []
    if files:
        payloads.append(files[-1].read_bytes())
    elif allow_cloud:
        from eulerlab.ingest import landing_reader

        remote = sorted(landing_reader.available("us", "sp500/*.jsonl.gz"))
        if remote:
            try:
                payloads.append(landing_reader.read(remote[-1]))
            except (OSError, ValueError):
                return []

    out: list[str] = []
    for payload in payloads:
        text = gzip.decompress(payload).decode("utf-8", errors="replace")
        for line in text.splitlines():
            if line.strip():
                try:
                    out.append(str(json.loads(line)["symbol"]))
                except (json.JSONDecodeError, KeyError):
                    continue
    return sorted(set(out))


MINUTE_FIRST = "2024-01-01"
"""Earliest minute bar this feed serves.

Measured 2026-08-24: requests from 2016 and 2020 return **zero** bars while
2024 returns a full session. Daily bars reach 2016 on the same key, so the
limit is specific to intraday depth, not to the account. Asking for 2016
minute data returns success and nothing, which is the failure mode worth
naming — a backfill would appear to work and land an empty archive.
"""


def _num(value: object) -> float:
    """A JSON number, or a raised error. Never a silent zero."""
    if isinstance(value, (int, float)):
        return float(value)
    raise ValueError(f"not a number: {value!r}")


def minute_path(symbol: str, month: str, *, root: Path = LANDING) -> Path:
    return root / "minute" / symbol / f"{month}.jsonl.gz"


def land_minute(
    symbols: list[str], *, start: str = MINUTE_FIRST, end: str = "", root: Path = LANDING
) -> tuple[int, int, str]:
    """Fetch and land 1-minute bars. Returns (symbols written, rows new, error).

    Sized before it was written: one symbol-month is about 8,900 bars and 1 MB
    of raw JSON, so a symbol-year is roughly 2 MB gzipped and the full S&P 500
    across the available window is about **3 GB** — against 4 GB of free disk.
    That is why the runner syncs and prunes between batches rather than landing
    everything and hoping.
    """
    if not symbols:
        return 0, 0, ""

    stamp = datetime.now(UTC).isoformat()
    written = new = 0
    for index in range(0, len(symbols), BAR_BATCH):
        batch = symbols[index : index + BAR_BATCH]
        query = urllib.parse.urlencode(
            {
                "symbols": ",".join(batch),
                "timeframe": "1Min",
                "start": start,
                "limit": PAGE_LIMIT,
                "feed": "iex",
                "adjustment": "raw",
                **({"end": end} if end else {}),
            }
        )
        collected: dict[str, list[dict[str, object]]] = {}
        token = ""
        while True:
            url = f"{DATA}/v2/stocks/bars?{query}"
            if token:
                url += f"&page_token={urllib.parse.quote(token)}"
            try:
                page = _get(url)
            except Exception as exc:
                return written, new, f"{type(exc).__name__}: {str(exc)[:110]}"
            rows_page = page.get("bars")
            if isinstance(rows_page, dict):
                for symbol, rows in rows_page.items():
                    if isinstance(rows, list):
                        collected.setdefault(str(symbol), []).extend(
                            r for r in rows if isinstance(r, dict)
                        )
            nxt = page.get("next_page_token")
            if not isinstance(nxt, str) or not nxt:
                break
            token = nxt

        for symbol, rows in collected.items():
            by_month: dict[str, list[dict[str, object]]] = {}
            for row in rows:
                # Coerced through a helper rather than called on `object`
                # directly: the payload is untyped JSON, and a bar whose price
                # will not parse is dropped rather than defaulted to zero. A
                # zero close is a company that went to nothing, which is a
                # claim this ingest is in no position to make.
                try:
                    when = str(row["t"])
                    by_month.setdefault(when[:7], []).append(
                        {
                            "symbol": symbol,
                            "event_time": when,
                            "open": _num(row.get("o")),
                            "high": _num(row.get("h")),
                            "low": _num(row.get("l")),
                            "close": _num(row.get("c")),
                            "volume": _num(row.get("v")),
                            "trades": int(_num(row.get("n"))),
                            "vwap": _num(row.get("vw")),
                            "knowledge_time": stamp,
                        }
                    )
                except (KeyError, TypeError, ValueError):
                    continue
            touched = False
            for month, month_rows in sorted(by_month.items()):
                _, added = _merge(minute_path(symbol, month, root=root), month_rows, "event_time")
                new += added
                touched = True
            written += int(touched)
    return written, new, ""


ACTION_TYPES = "cash_dividend,forward_split,reverse_split"
"""What the panel's adjustment cares about, and what the endpoint accepts.

Dividends and splits move a price series without anything happening to the
company, which is precisely the distortion a back-adjustment exists to undo.
`merger` and `spinoff` were in this list and the endpoint answers **400** for
them — not an empty result, a rejection, so the whole request failed.
"""


def land_actions(
    symbols: list[str], *, start: str, end: str = "", root: Path = LANDING
) -> tuple[int, str]:
    """Land corporate actions. Returns (rows written, error).

    These are what the equity panel currently **infers**. A back-adjusted
    series is built by detecting a jump and assuming a split or dividend
    caused it; this is the record of what actually happened, which is a
    different and better thing to adjust against.

    Landed by `process_date` month, not `ex_date`: the file a row belongs to
    should not move when an exchange corrects a date after the fact.
    """
    if not symbols:
        return 0, ""

    stamp = datetime.now(UTC).isoformat()
    written = 0
    for index in range(0, len(symbols), BAR_BATCH):
        batch = symbols[index : index + BAR_BATCH]
        query = urllib.parse.urlencode(
            {
                "symbols": ",".join(batch),
                "types": ACTION_TYPES,
                "start": start,
                "limit": 1000,
                **({"end": end} if end else {}),
            }
        )
        token = ""
        rows: list[dict[str, object]] = []
        while True:
            url = f"{DATA}/v1/corporate-actions?{query}"
            if token:
                url += f"&page_token={urllib.parse.quote(token)}"
            try:
                page = _get(url)
            except Exception as exc:
                return written, f"{type(exc).__name__}: {str(exc)[:110]}"

            actions = page.get("corporate_actions")
            if isinstance(actions, dict):
                for kind, entries in actions.items():
                    if not isinstance(entries, list):
                        continue
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        rows.append(
                            {
                                **entry,
                                "action_type": str(kind),
                                "knowledge_time": stamp,
                            }
                        )
            nxt = page.get("next_page_token")
            if not isinstance(nxt, str) or not nxt:
                break
            token = nxt

        by_month: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            when = str(row.get("process_date") or row.get("ex_date") or "")[:7]
            if when:
                by_month.setdefault(when, []).append(row)
        for month, month_rows in sorted(by_month.items()):
            path = root / "actions" / f"{month}.jsonl.gz"
            _, added = _merge(path, month_rows, "id")
            written += added
    return written, ""


def land_news(
    symbols: list[str], *, start: str, limit: int = 50, root: Path = LANDING
) -> tuple[int, str]:
    """Land US news. Returns (rows written, error).

    Free here, and **402 on FMP's every news endpoint**. It carries the article
    body and publisher-assigned tickers, where the Google News layer this
    platform already runs has headlines only and must infer relevance from the
    title. For US listings this is strictly better data; it does not replace
    Google News, which covers NSE.
    """
    if not symbols:
        return 0, ""

    stamp = datetime.now(UTC).isoformat()
    written = 0
    for index in range(0, len(symbols), 50):
        batch = symbols[index : index + 50]
        query = urllib.parse.urlencode(
            {"symbols": ",".join(batch), "start": start, "limit": limit, "sort": "desc"}
        )
        try:
            page = _get(f"{DATA}/v1beta1/news?{query}")
        except Exception as exc:
            return written, f"{type(exc).__name__}: {str(exc)[:110]}"

        rows: list[dict[str, object]] = []
        entries = page.get("news")
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            when = str(entry.get("created_at", ""))
            if not when:
                continue
            rows.append(
                {
                    "id": str(entry.get("id", "")),
                    "headline": str(entry.get("headline", "")),
                    "summary": str(entry.get("summary", ""))[:2000],
                    "source": str(entry.get("source", "")),
                    "author": str(entry.get("author", "")),
                    "symbols": [str(x) for x in (entry.get("symbols") or [])],
                    "event_time": when,
                    # When we pulled it, not when it was published. Backdating
                    # knowledge to the publish stamp is the leak the read API
                    # exists to prevent.
                    "knowledge_time": stamp,
                }
            )

        by_month: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            by_month.setdefault(str(row["event_time"])[:7], []).append(row)
        for month, month_rows in sorted(by_month.items()):
            path = root / "news" / f"{month}.jsonl.gz"
            _, added = _merge(path, month_rows, "id")
            written += added
    return written, ""
