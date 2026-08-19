"""Turning stored files into `Bar` rows the checks can read.

Kept separate from the checks themselves so the checks never know where their
data came from. That matters more than tidiness here: row-level checks need
price history from B2 at one transaction per file against a 2,500/day cap, so
they have to run identically against a fixture, a restored local file, or a
cached index — and a check that fetched its own data could not.

Two eras and two vendors are normalised here:

* **Legacy bhavcopy** (pre-2024) — `SYMBOL,SERIES,OPEN,...,PREVCLOSE,...`
* **UDiFF bhavcopy** (2024-) — `TckrSymb,OpnPric,...,PrvsClsgPric,...`
* **Kite minute bars** — parquet, one file per symbol-window, aggregated to a
  daily bar for the cross-source comparison.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Iterator
from datetime import date

from eulerlab.quality.row_checks import Bar

SYMBOL_FIELDS = ("TckrSymb", "SYMBOL")
ISIN_FIELDS = ("ISIN",)
SERIES_FIELDS = ("SctySrs", "SERIES")
OPEN_FIELDS = ("OpnPric", "OPEN")
HIGH_FIELDS = ("HghPric", "HIGH")
LOW_FIELDS = ("LwPric", "LOW")
CLOSE_FIELDS = ("ClsPric", "CLOSE")
PREV_CLOSE_FIELDS = ("PrvsClsgPric", "PREVCLOSE")
VOLUME_FIELDS = ("TtlTradgVol", "TOTTRDQTY")
TURNOVER_FIELDS = ("TtlTrfVal", "TOTTRDVAL")

TRADED_SERIES = frozenset({"EQ", "BE"})
"""Only genuinely traded equity series. Bonds and ETF NAV rows live in the
same file and would generate meaningless findings."""


def _first(row: dict[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        if value := row.get(name):
            return value.strip()
    return ""


def _number(row: dict[str, str], names: tuple[str, ...]) -> float | None:
    raw = _first(row, names)
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def bars_from_bhavcopy(payload: bytes, trade_date: date) -> Iterator[Bar]:
    """Every traded equity row of one cash bhavcopy, either era.

    A row missing any of the four prices is skipped rather than defaulted:
    a Bar with a zero high would fail the OHLC invariant and be reported as
    corrupt data when the truth is that the field was absent.
    """
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if not names:
            return
        with archive.open(names[0]) as handle:
            text = io.TextIOWrapper(handle, encoding="utf-8", errors="replace")
            for raw in csv.DictReader(text):
                row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
                if _first(row, SERIES_FIELDS) not in TRADED_SERIES:
                    continue
                symbol = _first(row, SYMBOL_FIELDS)
                prices = [
                    _number(row, fields)
                    for fields in (OPEN_FIELDS, HIGH_FIELDS, LOW_FIELDS, CLOSE_FIELDS)
                ]
                if not symbol or any(p is None for p in prices):
                    continue
                open_, high, low, close = (p for p in prices if p is not None)
                yield Bar(
                    isin=_first(row, ISIN_FIELDS),
                    symbol=symbol,
                    day=trade_date,
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    prev_close=_number(row, PREV_CLOSE_FIELDS),
                    volume=_number(row, VOLUME_FIELDS) or 0.0,
                    turnover=_number(row, TURNOVER_FIELDS),
                )


def daily_bar_from_minutes(
    symbol: str, day: date, minutes: list[tuple[float, float, float, float, float]]
) -> Bar | None:
    """Aggregate one day of 1-minute bars into a daily bar.

    `minutes` is (open, high, low, close, volume) in chronological order. The
    daily open is the first minute's open and the daily close is the last
    minute's close — not the min and max, which is the easy mistake and would
    make every reconciliation fail.
    """
    if not minutes:
        return None
    return Bar(
        symbol=symbol,
        day=day,
        open=minutes[0][0],
        high=max(m[1] for m in minutes),
        low=min(m[2] for m in minutes),
        close=minutes[-1][3],
        volume=sum(m[4] for m in minutes),
    )
