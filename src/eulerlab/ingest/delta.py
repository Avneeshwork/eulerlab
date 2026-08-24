"""Delta Exchange India — live tickers, candles and funding.

### Why this and not FMP for crypto

Delta is the venue this platform would actually trade crypto on, so its mark is
the price an order would meet. FMP's quote is a third party's opinion of what
BTC is worth; Delta's is what BTC costs *here*. That is the same reasoning that
makes Zerodha primary for India, and it matters more for crypto because the
fees already charged against these strategies are Delta's.

It also carries what no aggregator does: **open interest and the funding rate,
per contract**. The `funding_drift` signal is named for a number the platform
could not previously measure, and A-026 records funding as explicitly
unmodelled because there was no source for it.

### The public API needs no key

Measured 2026-08-24: tickers (1,285 instruments), candles at 1m through 1d,
L2 orderbook, trades, products and assets all answer unauthenticated. Daily
candles reach 2023-12-29. Credentials exist in `.env` for the private side and
are **not** used here — positions and orders touch a real account, and reading
prices does not need them.

### One thing to settle before comparing venues

Delta's `BTCUSD` is a USD-margined perpetual with a contract value; Binance's
`BTCUSDT` is a spot pair. The archive this platform holds is Binance. They
track each other closely and they are not the same instrument, so a difference
between a Binance backtest and a Delta backtest could be a contract-spec
artefact rather than a venue effect. Recorded rather than assumed away.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime

BASE = "https://api.india.delta.exchange"
USER_AGENT = "eulerlab/1.0"

MAJORS: tuple[tuple[str, str], ...] = (
    ("BTCUSD", "BITCOIN"),
    ("ETHUSD", "ETHEREUM"),
    ("SOLUSD", "SOLANA"),
    ("XRPUSD", "XRP"),
    ("BNBUSD", "BNB"),
    ("DOGEUSD", "DOGECOIN"),
)
"""Perpetuals, matched to the six the crypto tab already shows so the two
sources can be compared rather than silently swapped."""


@dataclass(frozen=True)
class Ticker:
    """One contract's live state."""

    symbol: str
    name: str
    mark: float
    change_24h: float
    open_interest: float
    funding_rate: float
    volume: float
    at: str


@dataclass
class Live:
    tickers: list[Ticker] = field(default_factory=list)
    error: str = ""

    @property
    def any(self) -> bool:
        return bool(self.tickers)


def _get(path: str, *, timeout: int = 25) -> object:
    request = urllib.request.Request(
        BASE + path, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload.get("result") if isinstance(payload, dict) else None


def _num(value: object) -> float:
    """A number from Delta's JSON, which sends several as strings."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def live(symbols: tuple[tuple[str, str], ...] = MAJORS) -> Live:
    """Live marks for the named contracts, in one request.

    The whole ticker list comes back at once — 1,285 instruments — so asking
    for six costs exactly as much as asking for all of them, and filtering
    locally is cheaper than six round trips.
    """
    try:
        result = _get("/v2/tickers")
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return Live(error=f"{type(exc).__name__}: {str(exc)[:100]}")

    rows = result if isinstance(result, list) else []
    by_symbol = {str(row.get("symbol", "")): row for row in rows if isinstance(row, dict)}
    stamp = datetime.now(UTC).isoformat()

    out: list[Ticker] = []
    for symbol, name in symbols:
        row = by_symbol.get(symbol)
        if not row:
            continue
        mark = _num(row.get("mark_price")) or _num(row.get("close"))
        if not mark:
            continue
        out.append(
            Ticker(
                symbol=symbol,
                name=name,
                mark=mark,
                change_24h=_num(row.get("mark_change_24h")),
                open_interest=_num(row.get("oi")),
                funding_rate=_num(row.get("funding_rate")),
                volume=_num(row.get("volume")),
                at=stamp,
            )
        )
    return Live(tickers=out, error="" if out else "no requested contracts in the ticker list")


def candles(
    symbol: str, *, resolution: str = "1d", start: int, end: int
) -> tuple[list[dict[str, float]], str]:
    """OHLCV from the venue itself. Returns (candles oldest-first, error).

    Delta returns newest-first; reversed here so it matches every other bar
    reader in this platform. A silent ordering difference between sources is
    the kind of thing that produces a backtest running backwards.
    """
    query = urllib.parse.urlencode(
        {"resolution": resolution, "symbol": symbol, "start": start, "end": end}
    )
    try:
        result = _get(f"/v2/history/candles?{query}", timeout=40)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return [], f"{type(exc).__name__}: {str(exc)[:100]}"

    rows = result if isinstance(result, list) else []
    out: list[dict[str, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "time": _num(row.get("time")),
                "open": _num(row.get("open")),
                "high": _num(row.get("high")),
                "low": _num(row.get("low")),
                "close": _num(row.get("close")),
                "volume": _num(row.get("volume")),
            }
        )
    out.sort(key=lambda c: c["time"])
    return out, ""
