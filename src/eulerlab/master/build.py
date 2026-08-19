"""Build the registry by walking bhavcopy files forward in time.

Streams from B2 rather than restoring to disk: the landing zone is pruned after
upload (ADR-010), and 5 GB of bhavcopy will not fit on a machine with a few GB
free. Each file is read in memory and discarded, so peak usage is one file.

The two archive eras carry different column names for the same facts, so both
are normalised here rather than at every call site.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

from eulerlab.master.identity import InstrumentId, NotAnIsin
from eulerlab.master.registry import Registry

# UDiFF (2024+) and legacy (pre-2024) name the same fields differently.
SYMBOL_FIELDS = ("TckrSymb", "SYMBOL")
ISIN_FIELDS = ("ISIN",)
SERIES_FIELDS = ("SctySrs", "SERIES")
LOT_FIELDS = ("NewBrdLotQty",)

TRADED_SERIES = frozenset({"EQ", "BE"})


@dataclass(frozen=True)
class Row:
    ticker: str
    isin: str
    series: str
    lot_size: int | None


def _first(row: dict[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        value = row.get(name)
        if value:
            return value.strip()
    return ""


def parse_cash_rows(payload: bytes) -> Iterator[Row]:
    """Yield equity rows from one day's cash bhavcopy, either era."""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if not names:
            return
        with archive.open(names[0]) as handle:
            text = io.TextIOWrapper(handle, encoding="utf-8", errors="replace")
            for raw in csv.DictReader(text):
                row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
                series = _first(row, SERIES_FIELDS)
                if series not in TRADED_SERIES:
                    continue
                ticker = _first(row, SYMBOL_FIELDS)
                isin = _first(row, ISIN_FIELDS)
                if not ticker or not isin:
                    continue
                lot_raw = _first(row, LOT_FIELDS)
                yield Row(
                    ticker=ticker,
                    isin=isin,
                    series=series,
                    lot_size=int(lot_raw) if lot_raw.isdigit() else None,
                )


@dataclass
class BuildStats:
    files_read: int = 0
    rows_seen: int = 0
    rows_skipped_bad_isin: int = 0

    def summary(self) -> str:
        return (
            f"{self.files_read} files, {self.rows_seen:,} rows, "
            f"{self.rows_skipped_bad_isin:,} skipped for a malformed ISIN"
        )


def observe_day(registry: Registry, trade_date: date, payload: bytes, stats: BuildStats) -> None:
    """Fold one day's cash bhavcopy into the registry."""
    for row in parse_cash_rows(payload):
        try:
            instrument_id = InstrumentId.from_isin(row.isin)
        except NotAnIsin:
            # Recorded, not silently dropped: a rising count here means the
            # source changed shape and the master is quietly losing coverage.
            stats.rows_skipped_bad_isin += 1
            continue
        registry.observe(
            trade_date,
            instrument_id=instrument_id,
            ticker=row.ticker,
            isin=row.isin,
            series=row.series,
            lot_size=row.lot_size,
        )
        stats.rows_seen += 1
    stats.files_read += 1
