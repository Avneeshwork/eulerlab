"""Macro series from TradingView's public scanner — keyless, and it fills gaps.

### Why this exists alongside FMP

FMP's free plan serves a Treasury curve and three metals, and answers **402
Payment Required** for WTI, natural gas and the dollar index. Those are not
optional extras for a macro band: crude is the single largest input to India's
import bill, and DXY is the number every EM currency is read against.

TradingView's scanner — the endpoint behind their own screeners — answers
without a key, without a signup, and without a daily budget. Measured
2026-08-24, it serves everything FMP paywalls **plus** sovereign yields for
seven countries including India's 10-year, which no other free source here
reaches at all.

### What that buys, and what it costs

One POST returns every symbol at once, so a full macro sweep is **one request**
rather than the twenty-nine a comparable FMP sweep costs. That difference is
what makes this affordable to refresh often rather than once a day.

The cost is that it is undocumented. It powers a public product and has no
published contract, so it can change shape without notice. Everything here
treats a missing symbol as ordinary — the sweep reports what resolved and what
did not, rather than failing whole — and nothing else in the platform depends
on it.

### Not a substitute for the broker

These are TradingView's marks, same as the chart. India's own index levels
still come from Zerodha, because that is the venue this platform trades
through and its quote is the price an order would meet. The scanner's NIFTY is
a **cross-check**, not the source of record.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime

SCANNER = "https://scanner.tradingview.com/global/scan"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
)

ENERGY: tuple[tuple[str, str, str], ...] = (
    ("NYMEX:CL1!", "WTI CRUDE", "$/bbl"),
    ("ICEEUR:BRN1!", "BRENT", "$/bbl"),
    ("NYMEX:NG1!", "NAT GAS", "$/MMBtu"),
)
"""Front-month futures, not spot. `TVC:USOIL` and the broker CFD symbols do not
resolve on this endpoint; the exchange contracts do."""

METALS: tuple[tuple[str, str, str], ...] = (
    ("COMEX:GC1!", "GOLD", "$/oz"),
    ("TVC:SILVER", "SILVER", "$/oz"),
    ("COMEX:HG1!", "COPPER", "$/lb"),
)

RISK: tuple[tuple[str, str, str], ...] = (
    ("TVC:DXY", "DOLLAR INDEX", ""),
    ("CBOE:VIX", "VIX", ""),
)
"""Both **402 on FMP's free plan**, which is the reason this module exists."""

YIELDS: tuple[tuple[str, str, str], ...] = (
    ("TVC:US02Y", "US 2Y", "%"),
    ("TVC:US05Y", "US 5Y", "%"),
    ("TVC:US10Y", "US 10Y", "%"),
    ("TVC:US30Y", "US 30Y", "%"),
    ("TVC:IN10Y", "INDIA 10Y", "%"),
    ("TVC:DE10Y", "GERMANY 10Y", "%"),
    ("TVC:JP10Y", "JAPAN 10Y", "%"),
    ("TVC:GB10Y", "UK 10Y", "%"),
    ("TVC:CN10Y", "CHINA 10Y", "%"),
)
"""India's 10-year is the one no other free source here reaches, and it is the
one an Indian desk actually watches."""

GROUPS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "energy": ENERGY,
    "metals": METALS,
    "risk": RISK,
    "yields": YIELDS,
}


@dataclass(frozen=True)
class Reading:
    """One macro series."""

    symbol: str
    name: str
    unit: str
    last: float
    change_pct: float
    group: str
    description: str = ""


@dataclass
class Macro:
    readings: list[Reading] = field(default_factory=list)
    missing: tuple[str, ...] = ()
    error: str = ""
    at: str = ""

    def of(self, group: str) -> list[Reading]:
        return [r for r in self.readings if r.group == group]

    @property
    def us_curve_2s10s(self) -> float | None:
        """10-year minus 2-year, from the live yields rather than the dated
        Treasury file. Negative is inverted."""
        rates = {r.name: r.last for r in self.of("yields")}
        if "US 10Y" in rates and "US 2Y" in rates:
            return rates["US 10Y"] - rates["US 2Y"]
        return None


def fetch(*, timeout: int = 25) -> Macro:
    """Every group in **one** request. Missing symbols are reported, not fatal."""
    wanted = [
        (symbol, name, unit, group) for group, rows in GROUPS.items() for symbol, name, unit in rows
    ]
    payload = json.dumps(
        {
            "symbols": {"tickers": [w[0] for w in wanted], "query": {"types": []}},
            "columns": ["close", "change", "description"],
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        SCANNER,
        data=payload,
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return Macro(error=f"{type(exc).__name__}: {str(exc)[:100]}")

    rows = body.get("data") if isinstance(body, dict) else None
    got: dict[str, list[object]] = {}
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and isinstance(row.get("d"), list):
            got[str(row.get("s", ""))] = row["d"]

    stamp = datetime.now(UTC).isoformat()
    readings: list[Reading] = []
    missing: list[str] = []
    for symbol, name, unit, group in wanted:
        cells = got.get(symbol)
        if not cells or not isinstance(cells[0], (int, float)):
            missing.append(symbol)
            continue
        change = cells[1] if len(cells) > 1 and isinstance(cells[1], (int, float)) else 0.0
        description = str(cells[2]) if len(cells) > 2 else ""
        readings.append(
            Reading(
                symbol=symbol,
                name=name,
                unit=unit,
                last=float(cells[0]),
                change_pct=float(change),
                group=group,
                description=description,
            )
        )
    return Macro(readings=readings, missing=tuple(missing), at=stamp)
