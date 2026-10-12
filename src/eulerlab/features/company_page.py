"""Everything held about one company, shaped for its page.

Operator, 2026-10-12: "build pages for each stocks about their details from
data we have from fundamental data", with a screenshot of a US broker's stock
page as the model.

### What the page is built from

One screener.in file per company (`data/landing/fundamentals/<SYMBOL>/`): the
header ratios, the sector hierarchy, index membership, and six tables —
quarterly results, profit and loss, balance sheet, cash flow, ratios and
shareholding. Prices come from the panel and headlines from the news archive.

### What the screenshot shows that is not held

Analyst ratings, price targets, forward estimates, a discounted cash flow, the
company description, the chief executive, the headcount and the listing date.
None is in any landed file. `NOT_HELD` lists them and the page prints the
list, because a panel quietly left out reads as "nothing to report" and a
panel filled with a guess is worse. `CLAUDE.md`: never invent a data source.

### Units

Statement figures are in ₹ crore as screener prints them; per-share figures
and prices are in ₹; `market_cap` is in ₹ (the digest converts it).

### What is computed here, not read

`debt_to_equity`, `net_margin`, `eps_ttm`, the growth rates and the industry
median P/E. Each is plain arithmetic on rows the page also shows, and `None`
when an input is missing: a ratio of nothing is not zero.
"""

from __future__ import annotations

import gzip
import io
import json
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict
from typing import Any

from eulerlab.features import company as digest

TABLES = ("quarters", "profit-loss", "balance-sheet", "cash-flow", "ratios", "shareholding")
SKIP_ROWS = frozenset({"Raw PDF"})
"""A link column on the source page, not a number."""

NOT_HELD = (
    "Analyst ratings and price targets",
    "Forward estimates (revenue, EBITDA, EPS)",
    "Discounted cash flow valuation",
    "Company description, chief executive, employees, listing date",
)
MAX_PEERS = 8
MAX_NEWS = 8
MIN_PEERS_FOR_MEDIAN = 3
"""Below this an "industry median" is one or two companies' P/E under a
grander name, so it is not reported."""


def latest_file(symbol: str) -> str | None:
    """The newest landed fundamentals file for `symbol`, landing-relative."""
    from eulerlab.ingest import landing_reader

    # The disk first. Listing the bucket is a network call of half a second,
    # and it is only needed for a company whose files were pruned from here.
    pattern = f"{symbol}/*.parquet"
    paths = landing_reader.available(digest.TREE, pattern, allow_cloud=False)
    if not paths:
        paths = landing_reader.available(digest.TREE, pattern)
    return max(paths) if paths else None


def read_columns(relative: str) -> dict[str, list[Any]]:
    import pyarrow.parquet as pq

    from eulerlab.ingest import landing_reader

    table = pq.read_table(io.BytesIO(landing_reader.read(relative)))
    return {name: table.column(name).to_pylist() for name in table.column_names}


def tables(columns: Mapping[str, Sequence[Any]]) -> dict[str, dict[str, Any]]:
    """Each statement as periods (oldest first) and rows in the source's order."""
    cells: dict[str, dict[str, dict[str, float | None]]] = {name: {} for name in TABLES}
    for index, section in enumerate(columns.get("section", [])):
        label = str(columns["row_label"][index])
        period = str(columns["period"][index] or "")
        if section not in cells or label in SKIP_ROWS or not period:
            continue
        value = columns["value"][index]
        cells[section].setdefault(label, {})[period] = None if value is None else float(value)
    out: dict[str, dict[str, Any]] = {}
    for name, rows in cells.items():
        periods = sorted({p for values in rows.values() for p in values})
        out[name] = {
            "periods": periods,
            "rows": [
                {"label": label, "values": [values.get(p) for p in periods]}
                for label, values in rows.items()
            ],
        }
    return out


def _row(table: Mapping[str, Any], label: str) -> list[float | None]:
    for row in table.get("rows", []):
        if row["label"] == label:
            return list(row["values"])
    return []


def _last(values: Sequence[float | None], back: int = 0) -> float | None:
    """The value `back` periods before the newest, or None."""
    return values[-1 - back] if len(values) > back else None


def _ratio(top: float | None, bottom: float | None) -> float | None:
    if top is None or bottom is None or bottom == 0:
        return None
    return top / bottom


def _growth(now: float | None, before: float | None) -> float | None:
    # A change from a loss to a profit has no meaningful percentage.
    if now is None or before is None or before <= 0:
        return None
    return now / before - 1


def metrics(statements: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """The handful of figures computed from the statements. See the module docstring."""
    annual, quarters, sheet = (
        statements["profit-loss"],
        statements["quarters"],
        statements["balance-sheet"],
    )
    sales, profit = _row(annual, "Sales"), _row(annual, "Net Profit")
    net_worth_parts = (_last(_row(sheet, "Equity Capital")), _last(_row(sheet, "Reserves")))
    net_worth = (
        None if None in net_worth_parts else sum(p for p in net_worth_parts if p is not None)
    )
    quarter_eps = [v for v in _row(quarters, "EPS in Rs")[-4:] if v is not None]
    q_sales, q_profit = _row(quarters, "Sales"), _row(quarters, "Net Profit")
    return {
        "annual_period": _last(annual.get("periods", [])),
        "quarter_period": _last(quarters.get("periods", [])),
        "debt_to_equity": _ratio(_last(_row(sheet, "Borrowings")), net_worth),
        "net_margin": _ratio(_last(profit), _last(sales)),
        "operating_margin": _ratio(_last(_row(annual, "Operating Profit")), _last(sales)),
        "eps": _last(_row(annual, "EPS in Rs")),
        "eps_ttm": sum(quarter_eps) if len(quarter_eps) == 4 else None,
        "sales_growth": _growth(_last(sales), _last(sales, 1)),
        "profit_growth": _growth(_last(profit), _last(profit, 1)),
        # Same quarter a year earlier, so a seasonal business is compared like with like.
        "quarter_sales_growth": _growth(_last(q_sales), _last(q_sales, 4)),
        "quarter_profit_growth": _growth(_last(q_profit), _last(q_profit, 4)),
        "free_cash_flow": _last(_row(statements["cash-flow"], "Free Cash Flow")),
        "promoter_holding": _last(_row(statements["shareholding"], "Promoters")),
    }


def peers(
    symbol: str, companies: Mapping[str, digest.Company], names: Mapping[str, str]
) -> dict[str, Any]:
    """Companies in the same industry, largest first, and the industry's median P/E."""
    me = companies.get(symbol)
    if me is None or not me.industry:
        return {"industry": "", "count": 0, "median_pe": None, "rows": []}
    same = [c for c in companies.values() if c.industry == me.industry]
    earning = [c.pe for c in same if c.pe is not None and c.pe > 0]
    same.sort(key=lambda c: -(c.market_cap or 0))
    rows = [c for c in same if c.symbol != symbol][:MAX_PEERS]
    return {
        "industry": me.industry,
        "count": len(same),
        "median_pe": statistics.median(earning) if len(earning) >= MIN_PEERS_FOR_MEDIAN else None,
        "pe_count": len(earning),
        "rows": [
            {
                "symbol": c.symbol,
                "name": names.get(c.symbol, ""),
                "market_cap": c.market_cap,
                "pe": c.pe,
                "roce": c.roce,
                "roe": c.roe,
            }
            for c in rows
        ],
    }


def news(symbol: str, files: Iterable[bytes], name: str = "") -> list[dict[str, str]]:
    """The newest headlines that name this company, from gzipped JSON-lines archives.

    The tag alone is not enough. The archive tags every result of a search for
    a symbol with that symbol, so headlines about Tatva Chintan and InfoBeans
    carried the RELIANCE tag (seen 2026-10-12). `ingest.news.strong_match` is
    the project's test for "this headline names this company": the ticker, or
    the first two distinctive words of the registered name. A headline that
    fails it is left out; an empty list says nothing, a wrong headline says
    something untrue.
    """
    from eulerlab.ingest.news import strong_match

    found: dict[str, dict[str, str]] = {}
    for blob in files:
        for line in gzip.decompress(blob).decode("utf-8", errors="replace").splitlines():
            if f'"{symbol}"' not in line:
                continue
            row = json.loads(line)
            title = str(row.get("title") or "")
            if symbol in (row.get("symbols") or []) and strong_match(title, symbol, name):
                found[str(row.get("guid") or row.get("link"))] = {
                    "title": str(row.get("title") or ""),
                    "link": str(row.get("link") or ""),
                    "publisher": str(row.get("publisher") or ""),
                    "time": str(row.get("event_time") or ""),
                }
    return sorted(found.values(), key=lambda r: r["time"], reverse=True)[:MAX_NEWS]


def news_files(months: int = 3) -> list[bytes]:
    from eulerlab.ingest import landing_reader

    paths = sorted(landing_reader.available("news", "equity/*.jsonl.gz"))[-months:]
    return [landing_reader.read(path) for path in paths]


def price_block(series: Sequence[tuple[str, float]], last_bar: Mapping[str, Any]) -> dict[str, Any]:
    """Price facts from an adjusted close series (oldest first) and the last raw bar."""
    if not series:
        return {"series": []}
    closes = [close for _, close in series]
    year = closes[-252:]
    return {
        "series": [[day, round(close, 2)] for day, close in series],
        "day": series[-1][0],
        "close": last_bar.get("close", closes[-1]),
        "previous_close": last_bar.get("previous_close"),
        "open": last_bar.get("open"),
        "volume": last_bar.get("volume"),
        # Adjusted, so a split inside the year does not show as a 52-week high.
        "high_52w": max(year),
        "low_52w": min(year),
    }


def build(
    symbol: str,
    columns: Mapping[str, Sequence[Any]],
    *,
    companies: Mapping[str, digest.Company],
    names: Mapping[str, str],
    as_of: str = "",
) -> dict[str, Any]:
    """The page for one company, from its fundamentals columns."""
    profile = digest.from_table(symbol, {k: list(v) for k, v in columns.items()})
    levels = [
        str(columns["raw"][i] or "")
        for i, section in enumerate(columns.get("section", []))
        if section == "sector"
    ]
    statements = tables(columns)
    consolidated = next(iter(columns.get("consolidated", [])), None)
    return {
        "symbol": symbol,
        "name": names.get(symbol, ""),
        "as_of": as_of,
        "consolidated": consolidated,
        "profile": {**asdict(profile), "sector_levels": [level for level in levels if level]},
        "metrics": metrics(statements),
        "tables": statements,
        "peers": peers(symbol, companies, names),
        "not_held": list(NOT_HELD),
    }
