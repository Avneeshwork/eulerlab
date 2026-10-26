"""One company's page, and the search that finds it.

The page is assembled in `features/company_page.py`. This adds the two things
that need the server's caches: prices from the panel and names for the search.
"""

from __future__ import annotations

import json
import re
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from eulerlab.bitemporal.store import BitemporalStore
from eulerlab.fair_value import valuation
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
    return _cached_names(_file_stamp(NAMES_PATH))


def _file_stamp(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


@lru_cache(maxsize=4)
def _cached_names(stamp: tuple[int, int] | None) -> dict[str, str]:
    if stamp is None:
        return {}
    names: dict[str, str] = json.loads(NAMES_PATH.read_text(encoding="utf-8"))
    return names


@lru_cache(maxsize=4)
def _cached_digest(stamp: tuple[int, int] | None) -> dict[str, digest.Company]:
    return digest.load_digest() if stamp is not None else {}


@lru_cache(maxsize=32)
def _cached_columns(relative: str, stamp: tuple[int, int] | None) -> dict[str, list[Any]]:
    # Cloud-only snapshots are immutable by date and are copied into the local
    # landing tree on first read. The first None key is bypassed on the next
    # request once that local copy exists.
    return company_page.read_columns(relative)


def _company_digest() -> dict[str, digest.Company]:
    return _cached_digest(_file_stamp(digest.DIGEST_PATH))


@lru_cache(maxsize=2)
def _cached_news_files(bucket: int) -> tuple[bytes, ...]:
    return tuple(company_page.news_files())


@lru_cache(maxsize=256)
def _cached_news(symbol: str, name: str, bucket: int) -> list[dict[str, str]]:
    return company_page.news(symbol, _cached_news_files(bucket), name)


def _news(symbol: str, name: str) -> list[dict[str, str]]:
    # News is ingested in batches. Five minutes matches the landing listing
    # cache and avoids decompressing the same archives on every page request.
    return _cached_news(symbol, name, int(time.time() // 300))


_PRICE_LOCKS: dict[str, threading.Lock] = {}
_PRICE_LOCKS_GUARD = threading.Lock()


def _price_lock(symbol: str) -> threading.Lock:
    with _PRICE_LOCKS_GUARD:
        return _PRICE_LOCKS.setdefault(symbol, threading.Lock())


@lru_cache(maxsize=4)
def _cached_factor_store(
    path: str,
    stamp: tuple[int, int] | None,
    manual_stamp: tuple[int, int] | None,
) -> BitemporalStore:
    from eulerlab.features.panel import load_price_factor_store

    # Factor files change only on an ingest/build. The store is shared as a
    # read-only lookup; the timestamp keys discard it naturally after rebuild.
    return load_price_factor_store(Path(path))


@lru_cache(maxsize=64)
def _cached_prices(
    symbol: str,
    panel_stamp: tuple[int, int] | None,
    factor_stamps: tuple[tuple[int, int] | None, ...],
) -> dict[str, Any]:
    from eulerlab.features.panel import PANEL_PATH, read_symbol_rows

    if panel_stamp is None:
        return {"series": []}
    try:
        from eulerlab.api.panels import PANEL

        held = PANEL.symbol_rows(symbol, PRICE_DAYS)
        mine = held if held is not None else read_symbol_rows(symbol, PRICE_DAYS, PANEL_PATH)
    except (FileNotFoundError, OSError):
        return {"series": []}
    if not mine:
        return {"series": []}
    # Adjust this company's rows alone. Asking the shared index for it adjusts
    # every symbol in the window first: 3.4 s on the first page opened.
    from eulerlab.backtest.vector import build_adjusted_index, build_total_return_index
    from eulerlab.corp_actions.build_factors import PRICE_FACTORS

    adjusted_factors = _cached_factor_store(str(PRICE_FACTORS), factor_stamps[0], factor_stamps[1])
    total_return_factors = _cached_factor_store(
        "data/derived/total_return_factors.jsonl", factor_stamps[2], None
    )
    adjusted = build_adjusted_index(mine, factor_store=adjusted_factors).get(symbol) or {}
    total_returns, total_return_factor_through = build_total_return_index(
        mine, factor_store=total_return_factors
    )
    total_return = total_returns.get(symbol) or {}
    series = [(r.day.isoformat(), adjusted.get(r.day, r.close)) for r in mine]
    total_return_series = [[r.day.isoformat(), total_return.get(r.day, r.close)] for r in mine]
    last = mine[-1]
    bar = {
        "close": last.close,
        "previous_close": mine[-2].close if len(mine) > 1 else None,
        "open": getattr(last, "open", None) or None,
        "volume": last.volume,
    }
    return {
        **company_page.price_block(series, bar),
        "total_return_series": total_return_series,
        "total_return_factor_through": total_return_factor_through,
    }


def _prices(symbol: str) -> dict[str, Any]:
    from eulerlab.corp_actions.build_factors import PRICE_FACTORS
    from eulerlab.features.panel import MANUAL_PRICE_FACTORS, PANEL_PATH

    factors = (
        PRICE_FACTORS,
        MANUAL_PRICE_FACTORS,
        Path("data/derived/total_return_factors.jsonl"),
    )
    # Avoid two simultaneous opens of the large panel for the same ticker.
    with _price_lock(symbol):
        return _cached_prices(
            symbol,
            _file_stamp(PANEL_PATH),
            tuple(_file_stamp(path) for path in factors),
        )


def _add_provisional(price: dict[str, Any], symbol: str) -> None:
    """A day the bhavcopy has not reached yet, from Kite minute bars (ADR-079).

    Shown beside the official close, never merged into the series: the panel's
    close is NSE's, and this one is the last traded minute.
    """
    from eulerlab.ingest import provisional_daily

    held = str(price.get("day", ""))
    bar = provisional_daily.bar_after(symbol, held) if held else None
    if bar:
        price["provisional"] = {
            key: bar[key] for key in ("d", "open", "high", "low", "close", "volume", "source")
        }


@router.get("/companies")
def companies(q: str = "", limit: int = 12) -> dict[str, Any]:
    """Companies whose symbol or name contains `q`, largest first."""
    needle = q.strip().upper()
    names, held = _names(), _company_digest()
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
        from eulerlab.ingest.landing_reader import LANDING_ROOT

        columns = _cached_columns(relative, _file_stamp(LANDING_ROOT / relative))
    except Exception as exc:  # one unreadable file is a message, not a 500
        return {"ok": False, "error": f"{relative} could not be read: {type(exc).__name__}"}
    page = company_page.build(
        wanted,
        columns,
        companies=_company_digest(),
        names=_names(),
        as_of=Path(relative).stem,
    )
    # A copy: `_prices` is cached, and the provisional bar must not stick to it.
    page["price"] = dict(_prices(wanted))
    _add_provisional(page["price"], wanted)
    try:
        page["news"] = _news(wanted, page["name"])
    except Exception:
        page["news"] = []
    try:
        fair_value = valuation.build(
            symbol=wanted,
            fundamentals_as_of=page["as_of"],
            fundamentals_path=relative,
            profile={**page["profile"], "consolidated": page["consolidated"]},
            metrics=page["metrics"],
            tables=page["tables"],
            peers=page["peers"],
            price=page["price"],
        )
        fair_value["run_id"] = valuation.save_snapshot(fair_value)
        page["fair_value"] = fair_value
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        # A missing factor release should leave the fundamental page useful;
        # the valuation panel explains the missing input instead of hiding it.
        page["fair_value"] = {
            "status": "unavailable",
            "confidence": "low",
            "reason": f"Fair-value inputs could not be loaded ({type(exc).__name__}).",
            "warnings": ["The company fundamentals and price page are still available."],
        }
    return {"ok": True, **page}
