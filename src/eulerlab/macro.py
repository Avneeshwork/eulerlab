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
from pathlib import Path

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


HISTORY = Path("data/landing/macro")
"""Where each sweep's readings are appended.

The scanner returns a level and no history, and TradingView's mini-chart widget
— the obvious way to draw one — **refuses most of these series**: the four US
tenors and Germany's and the UK's answer "No data here yet", while India's and
Japan's answer "This symbol is only available on TradingView". The symbols are
valid; the scanner serves every one of them. The widget is a different product
with different licensing, and assuming the two agreed was the mistake.

So the history is accumulated here instead. Every sweep appends one row per
series, and after a fortnight of daily runs there is a fortnight of curve — the
same shape the ForexFactory calendar uses, for the same reason: the source
publishes a present, not a past.

It starts empty, and a chart drawn from two points says so rather than
pretending to a trend.
"""


def history_path(day: str = "", *, root: Path = HISTORY) -> Path:
    stamp = day or datetime.now(UTC).date().isoformat()
    return root / f"{stamp}.jsonl"


def append(macro: Macro, *, root: Path = HISTORY) -> int:
    """Append this sweep's readings. Returns rows written.

    One file per day, one line per reading, append-only. A sweep that returned
    nothing writes nothing — an empty line would read as a zero reading, and a
    zero yield is a very different claim from a missing one.
    """
    if not macro.readings:
        return 0
    root.mkdir(parents=True, exist_ok=True)
    path = history_path(root=root)
    stamp = macro.at or datetime.now(UTC).isoformat()
    with path.open("a", encoding="utf-8") as handle:
        for reading in macro.readings:
            handle.write(
                json.dumps(
                    {
                        "at": stamp,
                        "symbol": reading.symbol,
                        "name": reading.name,
                        "group": reading.group,
                        "unit": reading.unit,
                        "last": reading.last,
                        "change_pct": reading.change_pct,
                    }
                )
                + "\n"
            )
    return len(macro.readings)


def series(name: str, *, days: int = 90, root: Path = HISTORY) -> list[tuple[str, float]]:
    """(timestamp, level) for one series, oldest first.

    One point per sweep rather than per day: a sweep run twice leaves two
    points, which is honest about how often it was actually measured.
    """
    from datetime import timedelta

    cutoff = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()
    out: list[tuple[str, float]] = []
    for stem, text in _days(root):
        if stem < cutoff:
            continue
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("name") == name and isinstance(row.get("last"), (int, float)):
                if _is_test_row(row):
                    continue
                out.append((str(row.get("at", "")), float(row["last"])))
    out.sort(key=lambda pair: pair[0])
    return out


def _days(root: Path) -> list[tuple[str, str]]:
    """(day, text) for every day file, local and in the bucket.

    `make daily` uploads the landing zone and `prune-local` then deletes what
    the bucket holds, so reading only the local folder found nothing: on the
    operator's Mac every macro chart was blank on 2026-11-01 because the folder
    was empty (HISTORY #52). The real folder is read through the landing
    reader, which fetches a pruned day from B2; any other root (a test) is
    read from disk alone.
    """
    out: list[tuple[str, str]] = []
    if root != HISTORY:
        for path in sorted(root.glob("????-??-??.jsonl")) if root.exists() else []:
            try:
                out.append((path.stem, path.read_text(encoding="utf-8")))
            except OSError:
                continue
        return out

    from eulerlab.ingest import landing_reader

    try:
        names = landing_reader.available("macro", "????-??-??.jsonl", stale_ok=True)
    except Exception:  # an unreachable bucket leaves what is on disk
        names = []
    if not names and root.exists():
        names = [f"macro/{p.name}" for p in sorted(root.glob("????-??-??.jsonl"))]
    for relative in names:
        try:
            text = landing_reader.read(relative).decode("utf-8", "replace")
        except Exception:
            continue
        out.append((Path(relative).stem, text))
    return out


def _is_test_row(row: dict[str, object]) -> bool:
    """The reading a test wrote into the real history until 2026-11-01.

    `test_indices` appended this exact Dollar Index row to the day's file on
    every `make verify` (HISTORY #50). Landing files are immutable, so the rows
    stay on disk and in the bucket and are skipped here. A real sweep matching
    all three fields to the last digit is not expected.
    """
    return (
        row.get("symbol") == "TVC:DXY" and row.get("last") == 98.9 and row.get("change_pct") == 0.15
    )


def all_series(*, days: int = 180, root: Path = HISTORY) -> dict[str, list[tuple[str, float]]]:
    """Every series' (timestamp, level) points, oldest first, from one pass.

    What the Charts page draws: the readings this platform recorded, not a
    vendor's chart widget, which refuses most of these symbols (HISTORY #52).
    """
    from datetime import timedelta

    cutoff = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()
    out: dict[str, list[tuple[str, float]]] = {}
    for stem, text in _days(root):
        if stem < cutoff:
            continue
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            name, last = row.get("name"), row.get("last")
            if not isinstance(name, str) or not isinstance(last, (int, float)):
                continue
            if _is_test_row(row):
                continue
            out.setdefault(name, []).append((str(row.get("at", "")), float(last)))
    for points in out.values():
        points.sort(key=lambda pair: pair[0])
    return out
