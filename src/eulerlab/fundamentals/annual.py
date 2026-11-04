"""Annual statements, point in time, for long-term stock models (ADR-136, research 150).

screener.in pages hold about twelve years of annual profit and loss, balance
sheet, cash flow and ratios, but not the date each year's results were
published. A year counts as known from `known_from(fy_end)`: 90 days after
the year end (A-107). SEBI's listing rules give 60 days for annual audited
results (secondary sources, research 150); 90 is the cautious margin over
late filers. For March 2020, SEBI extended the deadline to 31 July 2020, so
that year counts from 1 August 2020.

**Two biases this cannot remove, stated on every page that uses it:**

1. *Restatement.* Values come from the latest snapshot, which carries later
   restatements, and EPS restated for later splits and bonuses (measured:
   Tata Steel's FY2022 EPS is shown in units after its July 2022 split).
   Per-share values are therefore converted into the units of the decision
   date with the corporate-action factors (`units`), as the engine does for
   money; restated profits are not undone.
2. *Survivorship.* Fundamentals exist only for companies fetched since August
   2026, so a company that failed or was delisted before then has none. A
   model that needs fundamentals can only ever pick survivors.

Joined on ISIN, never ticker: each snapshot's ticker is resolved to the ISIN
the price panel shows for it (`build`).
"""

from __future__ import annotations

import io
import json
from bisect import bisect_right
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from functools import cache
from pathlib import Path
from typing import Any

OUT = Path("data/derived/fundamentals_annual.jsonl")
META = Path("data/derived/fundamentals_annual.meta.json")
MANIFEST = Path("data/landing/fundamentals/manifest.jsonl")
# ASSUMPTION: A-107. Annual results are public within 90 days of the year end.
LAG_DAYS = 90
OVERRIDES = {date(2020, 3, 31): date(2020, 8, 1)}

FIELDS: dict[tuple[str, str], str] = {
    ("profit-loss", "Sales"): "sales",
    ("profit-loss", "Operating Profit"): "op_profit",
    ("profit-loss", "Net Profit"): "net_profit",
    ("profit-loss", "EPS in Rs"): "eps",
    ("profit-loss", "Dividend Payout %"): "payout",
    ("balance-sheet", "Equity Capital"): "equity_capital",
    ("balance-sheet", "Reserves"): "reserves",
    ("balance-sheet", "Borrowings"): "borrowings",
    ("balance-sheet", "Total Assets"): "total_assets",
    ("cash-flow", "Cash from Operating Activity"): "cfo",
    ("ratios", "ROCE %"): "roce",
}


def known_from(fy_end: date) -> date:
    return OVERRIDES.get(fy_end, fy_end + timedelta(days=LAG_DAYS))


@dataclass(frozen=True)
class Year:
    isin: str
    symbol: str
    fy_end: date
    known_from: date
    fetch_date: str
    values: dict[str, float]

    def get(self, key: str) -> float | None:
        v = self.values.get(key)
        return float(v) if isinstance(v, int | float) else None


def years_from_snapshot(
    records: Sequence[Mapping[str, Any]], isin: str, fetch_date: str
) -> list[Year]:
    """One `Year` per dated annual period in a snapshot's statements."""
    by: dict[date, dict[str, float]] = {}
    symbol = ""
    for r in records:
        key = FIELDS.get((str(r.get("section")), str(r.get("row_label"))))
        value = r.get("value")
        if key is None or not isinstance(value, int | float):
            continue
        try:
            period = date.fromisoformat(str(r.get("period")))
        except ValueError:
            continue
        symbol = str(r.get("symbol") or symbol)
        by.setdefault(period, {})[key] = float(value)
    return [
        Year(isin, symbol, p, known_from(p), fetch_date, v)
        for p, v in sorted(by.items())
        if "net_profit" in v and "total_assets" in v
    ]


def latest_snapshots(manifest: Path | None = None) -> dict[str, dict[str, Any]]:
    """The newest snapshot per ticker, consolidated first when both exist that day."""
    p = manifest or MANIFEST
    best: dict[str, dict[str, Any]] = {}
    for line in p.read_text(encoding="utf-8").splitlines() if p.exists() else []:
        if not line.strip():
            continue
        row = json.loads(line)
        sym = str(row["symbol"])
        have = best.get(sym)
        rank = (str(row.get("fetch_date")), bool(row.get("consolidated")))
        if have is None or rank > (str(have.get("fetch_date")), bool(have.get("consolidated"))):
            best[sym] = row
    return best


def build(
    isin_of: Mapping[str, str],
    *,
    read: Callable[[str], bytes] | None = None,
    manifest: Path | None = None,
    out: Path | None = None,
    meta: Path | None = None,
) -> dict[str, int]:
    """Rebuild the table, reading only tickers whose newest snapshot is newer than last time."""
    import pyarrow.parquet as pq

    if read is None:
        from eulerlab.ingest import landing_reader

        def read(rel: str) -> bytes:
            return landing_reader.read(f"fundamentals/{rel}")

    out_p, meta_p = out or OUT, meta or META
    seen: dict[str, str] = json.loads(meta_p.read_text()) if meta_p.exists() else {}
    held: dict[str, list[dict[str, Any]]] = {}
    for row in load_rows(out_p):
        held.setdefault(str(row["isin"]), []).append(row)
    read_n = missing = failed = 0
    for sym, entry in sorted(latest_snapshots(manifest).items()):
        isin = isin_of.get(sym)
        if not isin:
            missing += 1
            continue
        if seen.get(sym) == entry["fetch_date"] and isin in held:
            continue
        try:
            records = pq.read_table(io.BytesIO(read(str(entry["path"])))).to_pylist()
        except (OSError, ValueError, KeyError):
            failed += 1
            continue
        read_n += 1
        held[isin] = [
            asdict(y) | {"fy_end": y.fy_end.isoformat(), "known_from": y.known_from.isoformat()}
            for y in years_from_snapshot(records, isin, str(entry["fetch_date"]))
        ]
        seen[sym] = str(entry["fetch_date"])
    out_p.parent.mkdir(parents=True, exist_ok=True)
    rows = [r for isin in sorted(held) for r in held[isin]]
    tmp = out_p.with_suffix(".partial")
    tmp.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(out_p)
    meta_p.write_text(json.dumps(seen, sort_keys=True), encoding="utf-8")
    load.cache_clear()
    return {
        "companies": len(held),
        "years": len(rows),
        "read": read_n,
        "no_isin": missing,
        "failed": failed,
    }


def load_rows(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or OUT
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


@cache
def load(path: Path | None = None) -> dict[str, list[Year]]:
    """By ISIN, oldest year first."""
    out: dict[str, list[Year]] = {}
    for r in load_rows(path):
        out.setdefault(str(r["isin"]), []).append(
            Year(
                str(r["isin"]),
                str(r["symbol"]),
                date.fromisoformat(str(r["fy_end"])),
                date.fromisoformat(str(r["known_from"])),
                str(r["fetch_date"]),
                {k: float(v) for k, v in dict(r["values"]).items()},
            )
        )
    for ys in out.values():
        ys.sort(key=lambda y: y.fy_end)
    return out


def known(years: Sequence[Year], day: date) -> list[Year]:
    """The years published by `day`, oldest first."""
    cut = bisect_right([y.known_from for y in years], day)
    return list(years[:cut])
