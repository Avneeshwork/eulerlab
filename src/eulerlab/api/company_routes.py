"""One company's page, and the search that finds it.

The page is assembled in `features/company_page.py`. This adds the two things
that need the server's caches: prices from the panel and names for the search.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from eulerlab.features import company as digest
from eulerlab.features import company_page

router = APIRouter(prefix="/api")

NAMES_PATH = Path("data/derived/nse_names.json")
PRICE_DAYS = 1260
"""About five years of sessions: the longest range the page's chart offers."""

SYMBOL = re.compile(r"[A-Z0-9&\-]{1,20}")
"""What an NSE symbol can look like. It becomes part of a file path, so
anything else is refused before it is used."""


def _names() -> dict[str, str]:
    if not NAMES_PATH.exists():
        return {}
    loaded: dict[str, str] = json.loads(NAMES_PATH.read_text(encoding="utf-8"))
    return loaded


def _prices(symbol: str) -> dict[str, Any]:
    from eulerlab.api.panels import PANEL

    try:
        rows = PANEL.rows(PRICE_DAYS)
    except (FileNotFoundError, OSError):
        return {"series": []}
    mine = sorted((r for r in rows if r.symbol == symbol), key=lambda r: r.day)
    if not mine:
        return {"series": []}
    # Adjust this company's rows alone. Asking the shared index for it adjusts
    # every symbol in the window first: 3.4 s on the first page opened.
    from eulerlab.backtest.vector import build_adjusted_index

    adjusted = build_adjusted_index(mine).get(symbol) or {}
    series = [(r.day.isoformat(), adjusted.get(r.day, r.close)) for r in mine]
    last = mine[-1]
    bar = {
        "close": last.close,
        "previous_close": mine[-2].close if len(mine) > 1 else None,
        "open": getattr(last, "open", None) or None,
        "volume": last.volume,
    }
    return company_page.price_block(series, bar)


@router.get("/companies")
def companies(q: str = "", limit: int = 12) -> dict[str, Any]:
    """Companies whose symbol or name contains `q`, largest first."""
    needle = q.strip().upper()
    names, held = _names(), digest.load_digest()
    found = [
        c
        for c in held.values()
        if not needle or needle in c.symbol or needle in names.get(c.symbol, "").upper()
    ]
    # A symbol that starts with the text beats one that merely contains it.
    found.sort(key=lambda c: (not c.symbol.startswith(needle), -(c.market_cap or 0)))
    return {
        "total": len(held),
        "rows": [
            {
                "symbol": c.symbol,
                "name": names.get(c.symbol, ""),
                "industry": c.industry,
                "market_cap": c.market_cap,
            }
            for c in found[: max(1, min(limit, 50))]
        ],
    }


@router.get("/company/{symbol}")
def company(symbol: str) -> dict[str, Any]:
    wanted = symbol.strip().upper()
    if not SYMBOL.fullmatch(wanted):
        return {"ok": False, "error": f"'{symbol}' is not a symbol."}
    relative = company_page.latest_file(wanted)
    if relative is None:
        return {
            "ok": False,
            "error": f"No fundamentals are held for {wanted}. "
            "Tools → Instruments → Fundamentals shows what is.",
        }
    try:
        columns = company_page.read_columns(relative)
    except Exception as exc:  # one unreadable file is a message, not a 500
        return {"ok": False, "error": f"{relative} could not be read: {type(exc).__name__}"}
    page = company_page.build(
        wanted,
        columns,
        companies=digest.load_digest(),
        names=_names(),
        as_of=Path(relative).stem,
    )
    page["price"] = _prices(wanted)
    try:
        page["news"] = company_page.news(wanted, company_page.news_files())
    except Exception:
        page["news"] = []
    return {"ok": True, **page}
