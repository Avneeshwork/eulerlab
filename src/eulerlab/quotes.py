"""Live prices, from Zerodha first and Yahoo second.

### Why two, and in this order

Zerodha is the broker this platform trades through, so its quote is the price
an order would actually meet. Yahoo is a public convenience with no such
relationship. Where they disagree the broker is right by definition, which is
why it is primary rather than merely first-tried.

Zerodha's cost is that its access token **expires at 6 AM the next day** — a
regulatory requirement, not a design choice — so a token minted yesterday buys
nothing today. That is precisely when a fallback earns its place.

### There is currently no working fallback, and that is measured

Two were tried on 2026-08-23:

- **Yahoo** — `query1`, `query2`, the v8 chart and v7 quote endpoints all
  return **429** on a first request from a plain client. A block on scripted
  access, not a rate limit earned by traffic.
- **NSE's own** `quote-equity` — **403**, even with the cookie bootstrap that
  works for the corporate-announcements endpoint. That path is more protected.

So Zerodha is not merely primary, it is presently the only source. That matters
operationally: the Kite token dies at 6 AM and until it is minted there are no
live quotes at all, rather than degraded ones. The band says so instead of
showing an empty column and letting the reader assume nothing moved.

### Yahoo is implemented and currently blocked

Measured 2026-08-23: `query1` and `query2`, the v8 chart and v7 quote endpoints
all return **HTTP 429**, on the first request of the day, from a plain client.
That is a block on scripted access rather than a rate limit earned by traffic —
the same wall the Yahoo RSS feed hit earlier (docs/RESEARCH/023).

It is written anyway, because the alternative is pretending there is no
fallback at all, and because a block can lift. What is not done is presenting
it as working: `live()` reports which source answered, and a caller that gets
nothing is told the reason rather than shown an empty screen.

### End-of-day is not a live quote

The snapshot's other numbers come from the EOD panel. Mixing a live last-price
into a table of settled closes without saying so would make the whole table
look current, which is the more damaging error — so every quote carries its
source and its timestamp, and the band says which it is showing.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
)

ZERODHA_BATCH = 200
"""Instruments per `quote()` call. Kite accepts more; batching keeps one bad
symbol from failing the whole universe in a single request."""


@dataclass(frozen=True)
class Quote:
    """One instrument's live price."""

    symbol: str
    last: float
    previous_close: float
    source: str
    """`zerodha` or `yahoo`. Recorded per quote, not per run: a fallback that
    covered half the universe would otherwise be indistinguishable from one
    that covered all of it."""

    at: str

    @property
    def change_pct(self) -> float:
        if not self.previous_close:
            return 0.0
        return (self.last - self.previous_close) / self.previous_close * 100.0


@dataclass
class QuoteResult:
    """What a quote sweep produced, and what it could not."""

    quotes: dict[str, Quote] = field(default_factory=dict)
    sources: dict[str, int] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    """Source name → why it produced nothing. Kept because "Zerodha returned no
    quotes" and "Zerodha was never asked" are different facts, and only one of
    them means the operator should mint a token."""

    @property
    def live(self) -> bool:
        return bool(self.quotes)

    @property
    def primary_source(self) -> str:
        if not self.sources:
            return ""
        return max(self.sources.items(), key=lambda kv: kv[1])[0]


def _env(name: str) -> str:
    import os

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


def from_zerodha(symbols: list[str]) -> tuple[dict[str, Quote], str]:
    """Live quotes from Kite. Returns (quotes, error).

    An expired token is the expected failure, not an exceptional one — it
    happens every morning at 6 — so it comes back as a message to show rather
    than an exception to handle.
    """
    if not symbols:
        return {}, ""
    try:
        from kiteconnect import KiteConnect

        from eulerlab.broker import kite_session
    except ImportError as exc:
        return {}, f"kiteconnect unavailable: {exc}"

    session = kite_session.load()
    if session is None:
        return {}, "no Kite session — run `make kite-login` to mint a token"

    api_key = _env("ZERODHA_API_KEY")
    if not api_key:
        return {}, "ZERODHA_API_KEY is not set"

    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(session.access_token)

    stamp = datetime.now(UTC).isoformat()
    out: dict[str, Quote] = {}
    for start in range(0, len(symbols), ZERODHA_BATCH):
        batch = symbols[start : start + ZERODHA_BATCH]
        try:
            payload = kite.quote([f"NSE:{s}" for s in batch])
        except Exception as exc:
            # Broad on purpose, and surfaced verbatim: "Incorrect `api_key` or
            # `access_token`" is the message that tells the operator to mint a
            # new token, and swallowing it would leave an empty band instead.
            return out, f"{type(exc).__name__}: {str(exc)[:120]}"

        for key, row in payload.items():
            symbol = key.split(":", 1)[-1]
            last = row.get("last_price")
            close = (row.get("ohlc") or {}).get("close")
            if not isinstance(last, (int, float)) or not last:
                continue
            out[symbol] = Quote(
                symbol=symbol,
                last=float(last),
                previous_close=float(close) if isinstance(close, (int, float)) else 0.0,
                source="zerodha",
                at=stamp,
            )
    return out, ""


def from_yahoo(symbols: list[str], *, suffix: str = ".NS") -> tuple[dict[str, Quote], str]:
    """Live quotes from Yahoo's public chart endpoint. Returns (quotes, error).

    Blocked as of 2026-08-23 — every endpoint answers 429 on a first request.
    Kept so the fallback exists if that lifts, and so the reason is reported
    rather than showing as an unexplained absence.
    """
    if not symbols:
        return {}, ""
    stamp = datetime.now(UTC).isoformat()
    out: dict[str, Quote] = {}
    blocked = ""
    for symbol in symbols:
        url = YAHOO.format(symbol=urllib.parse.quote(f"{symbol}{suffix}"))
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                # One 429 means every following request is one too. Stop rather
                # than spend a minute proving it symbol by symbol.
                return out, "Yahoo returned 429 (blocked for scripted access)"
            blocked = f"HTTP {exc.code}"
            continue
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            blocked = type(exc).__name__
            continue

        try:
            meta = payload["chart"]["result"][0]["meta"]
            last = float(meta["regularMarketPrice"])
            close = float(meta.get("previousClose") or meta.get("chartPreviousClose") or 0.0)
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        out[symbol] = Quote(
            symbol=symbol, last=last, previous_close=close, source="yahoo", at=stamp
        )
    return out, blocked


def live(symbols: list[str]) -> QuoteResult:
    """Live quotes, broker first, Yahoo for whatever the broker did not cover.

    Yahoo is asked only about the remainder rather than about everything: it is
    the fallback, and re-quoting a symbol the broker already priced would spend
    requests to produce a number this platform would not trade on.
    """
    wanted = list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))
    result = QuoteResult()
    if not wanted:
        return result

    primary, error = from_zerodha(wanted)
    result.quotes.update(primary)
    if primary:
        result.sources["zerodha"] = len(primary)
    if error:
        result.errors["zerodha"] = error

    missing = [s for s in wanted if s not in result.quotes]
    if missing:
        secondary, yahoo_error = from_yahoo(missing)
        result.quotes.update(secondary)
        if secondary:
            result.sources["yahoo"] = len(secondary)
        if yahoo_error:
            result.errors["yahoo"] = yahoo_error
    return result


def nse_universe(symbols: list[str]) -> tuple[dict[str, Quote], str]:
    """Live quotes for a whole NSE universe. Returns (quotes, error).

    Kite answers **500 instruments in 0.2 seconds**, so the entire liquid
    universe is six calls and under two seconds — which is what makes a live
    map possible at all rather than a nightly one.

    Symbols the broker does not recognise are simply absent from the result:
    six of a five-hundred batch, typically renamed or delisted names still in
    our universe file. Absent rather than zeroed, because a zero would render
    as a stock that fell 100%.
    """
    if not symbols:
        return {}, ""
    try:
        from kiteconnect import KiteConnect

        from eulerlab.broker import kite_session
    except ImportError as exc:
        return {}, f"kiteconnect unavailable: {exc}"

    session = kite_session.load()
    if session is None:
        return {}, "no Kite session — run `make kite-login` to mint a token"
    api_key = _env("ZERODHA_API_KEY")
    if not api_key:
        return {}, "ZERODHA_API_KEY is not set"

    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(session.access_token)

    stamp = datetime.now(UTC).isoformat()
    out: dict[str, Quote] = {}
    for start in range(0, len(symbols), ZERODHA_BATCH):
        batch = symbols[start : start + ZERODHA_BATCH]
        try:
            payload = kite.quote([f"NSE:{s}" for s in batch])
        except Exception as exc:
            return out, f"{type(exc).__name__}: {str(exc)[:120]}"

        for key, row in payload.items():
            symbol = key.split(":", 1)[-1]
            last = row.get("last_price")
            ohlc = row.get("ohlc") or {}
            close = ohlc.get("close")
            if not isinstance(last, (int, float)) or not last:
                continue
            out[symbol] = Quote(
                symbol=symbol,
                last=float(last),
                previous_close=float(close) if isinstance(close, (int, float)) else 0.0,
                source="zerodha",
                at=stamp,
            )
    return out, ""
