"""Sector, market capitalisation and headline ratios, per company.

The screener scrape landed more than quarterly statements. Each symbol's
Parquet carries a `sector` section holding a **four-level hierarchy**, a
`top_ratios` section with market cap, P/E, ROCE, ROE and book value, and an
`index_membership` section. None of it was being read.

That gap had a visible cost: the market map shipped ungrouped and sized by
turnover, with a note explaining that no sector or market-cap source was
connected. Both were sitting in a tree the code already downloaded.

### The numbers arrive as strings

`value` is null for these rows and `raw` holds the display text — `₹ 696 Cr.`,
`10.2`, `17.3 %`. So they are parsed here rather than trusted, and a value that
does not parse becomes None rather than zero: a company with no P/E and a
company priced at zero earnings are different facts, and only one of them is a
number.

### Why a digest

2,353 Parquet files is a few seconds to open and far too slow for a screen that
should feel instant. `build_digest` reduces them to one small JSON — symbol,
sector, market cap, a handful of ratios — which every reader then loads in
milliseconds. The digest is derived, so it is rebuilt rather than corrected.
"""

from __future__ import annotations

import io
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DIGEST_PATH = Path("data/derived/company_digest.json")
TREE = "fundamentals"

CRORE = 1e7
LAKH = 1e5

_NUMBER = re.compile(r"-?[\d,]+\.?\d*")


def parse_money(raw: str | None) -> float | None:
    """`₹ 696 Cr.` to 6_960_000_000. None when it is not a number.

    Crore and lakh are handled explicitly because a scale word dropped is a
    factor of ten million, which is not a rounding error — it is the difference
    between a microcap and a large cap, and the map would size it accordingly.
    """
    if not raw:
        return None
    match = _NUMBER.search(raw)
    if not match:
        return None
    try:
        amount = float(match.group().replace(",", ""))
    except ValueError:
        return None
    lowered = raw.lower()
    if "cr" in lowered:
        return amount * CRORE
    if "lakh" in lowered or "lac" in lowered:
        return amount * LAKH
    return amount


def parse_number(raw: str | None) -> float | None:
    """A bare or percentage figure. None when absent, never zero."""
    if not raw:
        return None
    match = _NUMBER.search(raw)
    if not match:
        return None
    try:
        return float(match.group().replace(",", ""))
    except ValueError:
        return None


@dataclass(frozen=True)
class Company:
    """What the map and the screener need about one listed company."""

    symbol: str
    sector: str = ""
    """Top level of the hierarchy — `Commodities`, `Financials`. Coarse on
    purpose: the map groups by it, and forty groups is not a map."""

    industry: str = ""
    """Second level, for a screener column where the detail is wanted."""

    market_cap: float | None = None
    price: float | None = None
    pe: float | None = None
    roce: float | None = None
    roe: float | None = None
    book_value: float | None = None
    dividend_yield: float | None = None
    indices: tuple[str, ...] = ()


def from_table(symbol: str, columns: dict[str, list[Any]]) -> Company:
    """One symbol's Parquet columns into a `Company`."""
    sector_levels: dict[str, str] = {}
    ratios: dict[str, str] = {}
    indices: list[str] = []

    for index in range(len(columns.get("section", []))):
        section = columns["section"][index]
        label = columns["row_label"][index]
        raw = columns["raw"][index]
        if section == "sector":
            sector_levels[str(label)] = str(raw or "")
        elif section == "top_ratios":
            ratios[str(label)] = str(raw or "")
        elif section == "index_membership":
            indices.append(str(label))

    return Company(
        symbol=symbol,
        sector=sector_levels.get("level_1", ""),
        industry=sector_levels.get("level_2", ""),
        market_cap=parse_money(ratios.get("Market Cap")),
        price=parse_money(ratios.get("Current Price")),
        pe=parse_number(ratios.get("Stock P/E")),
        roce=parse_number(ratios.get("ROCE")),
        roe=parse_number(ratios.get("ROE")),
        book_value=parse_money(ratios.get("Book Value")),
        dividend_yield=parse_number(ratios.get("Dividend Yield")),
        indices=tuple(sorted(indices)),
    )


def build_digest(*, limit: int = 0) -> dict[str, Company]:
    """Read every landed fundamentals file and reduce it to one record each.

    Reads through `landing_reader`, so a pruned tree is fetched from B2 rather
    than reported as absent.
    """
    import pyarrow.parquet as pq

    from eulerlab.ingest import landing_reader

    out: dict[str, Company] = {}
    paths = landing_reader.available(TREE, "*/*.parquet")
    for relative in paths:
        symbol = relative.split("/")[1]
        # Newest file per symbol wins; the listing is sorted, so a later date
        # overwrites an earlier one.
        try:
            table = pq.read_table(io.BytesIO(landing_reader.read(relative)))
            columns = {name: table.column(name).to_pylist() for name in table.column_names}
        except Exception:
            # One unreadable file must not end a 2,353-file build. It is absent
            # from the digest, which is visible in the count.
            continue
        out[symbol] = from_table(symbol, columns)
        if limit and len(out) >= limit:
            break
    return out


def save_digest(companies: dict[str, Company], path: Path = DIGEST_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {symbol: asdict(company) for symbol, company in sorted(companies.items())}
    tmp = path.with_suffix(".partial")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(path)
    return path


def load_digest(path: Path = DIGEST_PATH) -> dict[str, Company]:
    """The digest, or empty when it has not been built.

    Empty rather than raising: a map with no sectors is a worse map, not a
    broken screen, and it already knows how to say so.
    """
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    out: dict[str, Company] = {}
    for symbol, row in raw.items():
        row["indices"] = tuple(row.get("indices") or ())
        out[symbol] = Company(**row)
    return out
