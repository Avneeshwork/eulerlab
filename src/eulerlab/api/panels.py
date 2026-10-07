"""Panels: which rows an asset class has, and how they are cached.

Lifted out of `api/server`, where it was 145 lines of data access inside an HTTP
module — the same file that also held cost routing, report building and job
management. A request handler that owns its own storage layer is a file nobody
can read the top of.

The dispatch here is the one that decides *what data a backtest sees*, so it
sits beside the router that decides what that data costs rather than inside the
transport that happens to ask for it.
"""

from __future__ import annotations

import threading
from bisect import bisect_left
from collections.abc import Callable
from datetime import date
from operator import attrgetter
from typing import TypeVar, cast

from eulerlab.backtest.vector import build_adjusted_index
from eulerlab.features.panel import PANEL_PATH, PanelRow, by_symbol, read_panel, trading_days
from eulerlab.strategies import AssetClass

T = TypeVar("T")
_DAY = attrgetter("day")


class _Panel:
    """One copy of the panel and its adjusted index, shared by every request.

    Guarded by a lock because two requests arriving together would otherwise
    both start a 540 MB read. The index is keyed by the day-window so the
    common case — the same last-N-days repeatedly — is computed once.

    So is everything else a request reads off the whole panel: its trading
    days, its symbol count, its coverage, its per-symbol histories. Each was a
    fresh pass over 5.4M rows on every request; now each is one pass per load
    (`derived`), dropped with the rows when the file changes.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: list[PanelRow] = []
        self._days: list[date] = []
        self._stamp: int | None = None
        self._loaded = False
        self._indices: dict[tuple[int, str], dict[str, dict[date, float]]] = {}
        self._derived: dict[str, object] = {}

    def _current(self) -> list[PanelRow]:
        """The rows as of the file on disk now. Called with the lock held."""
        # Re-read when `make daily` has rebuilt the file. Held forever, a
        # server started before the rebuild kept trading days that were
        # already stale: a deployment made on 2026-10-07 started on the
        # 1 Oct close and showed nothing to trade (T-4025).
        stamp = PANEL_PATH.stat().st_mtime_ns if PANEL_PATH.exists() else None
        if not self._loaded or stamp != self._stamp:
            self._rows = read_panel()
            self._days = trading_days(self._rows)
            self._stamp = stamp
            self._loaded = True
            self._indices.clear()
            self._derived.clear()
        return self._rows

    def _derive(self, name: str, build: Callable[[list[PanelRow]], T]) -> T:
        """`build(rows)`, once per load. Called with the lock held."""
        rows = self._current()  # first: a reload drops every derived value
        if name not in self._derived:
            self._derived[name] = build(rows)
        return cast(T, self._derived[name])

    def _window_start(self, days: int) -> date | None:
        """The first day of the last `days` trading days; None for all of them."""
        if not days or days >= len(self._days):
            return None
        return self._days[-days]

    def rows(self, days: int = 0) -> list[PanelRow]:
        with self._lock:
            rows = self._current()
            cutoff = self._window_start(days)
        if cutoff is None:
            return rows
        # A suffix, because `read_panel` returns the rows sorted by day: found
        # by bisection rather than by testing all 5.4M rows, which with
        # re-sorting every day in the panel was most of a windowed request.
        return rows[bisect_left(rows, cutoff, key=_DAY) :]

    def history(self, symbol: str, days: int = 0) -> list[PanelRow]:
        """One symbol's rows in the last `days` trading days, oldest first.

        The same rows as filtering `rows(days)` by symbol, from a per-symbol
        index built on the first call after each load: a chart asked for one
        name and paid for a scan of every row in the window.
        """
        with self._lock:
            series = self._derive("by_symbol", by_symbol).get(symbol, [])
            cutoff = self._window_start(days)
        if cutoff is None:
            return list(series)
        return series[bisect_left(series, cutoff, key=_DAY) :]

    def derived(self, name: str, build: Callable[[list[PanelRow]], T]) -> T:
        """`build(rows)` over the whole panel, computed once per load.

        For figures read off the entire panel, such as how many symbols it
        holds. The value is shared between requests: treat it as read-only.
        """
        with self._lock:
            return self._derive(name, build)

    def index(
        self, days: int, rows: list[PanelRow], universe: str = "all"
    ) -> dict[str, dict[date, float]]:
        """Back-adjusted prices for this row set.

        Keyed by the window AND the universe. Keying by window alone was safe
        only while every run saw the whole panel: once rows are filtered, a
        nifty50 run at 800 days would hand its index to the next 800-day run
        over every symbol, which then has no adjusted prices for the symbols
        nifty50 never contained.
        """
        with self._lock:
            key = (days, universe)
            if key not in self._indices:
                self._indices[key] = build_adjusted_index(rows)
            return self._indices[key]

    def loaded(self) -> bool:
        return self._loaded


PANEL = _Panel()


class _AltPanel:
    """Crypto and mutual fund daily bars, loaded once and kept.

    Separate from `_Panel` because these are *derived*: crypto is resampled
    from 52.5M minute candles and funds from 14,280 NAV series, so a rebuild
    per request would make the first backtest on either take minutes. Held by
    asset class, and the lock is the same reason `_Panel` has one — two
    requests arriving together would otherwise both start the resample.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[str, list[PanelRow]] = {}
        self._days: dict[str, list[date]] = {}

    def rows(self, asset_class: str, days: int = 0) -> list[PanelRow]:
        with self._lock:
            if asset_class not in self._rows:
                loaded = _load_alt(asset_class)
                self._days[asset_class] = trading_days(loaded)
                self._rows[asset_class] = loaded
            rows = self._rows[asset_class]
            all_days = self._days[asset_class]
        if not days:
            return rows
        # Trailing N *trading* days, matching `_Panel.rows`. Crypto trades every
        # day and funds only on business days, so neither is forced onto the NSE
        # calendar; "trading days" is whatever days the data actually has. Held
        # from the load rather than re-derived from every row per request.
        if days >= len(all_days):
            return rows
        cutoff = all_days[-days]
        return [r for r in rows if r.day >= cutoff]

    def loaded(self, asset_class: str) -> bool:
        return asset_class in self._rows


def _load_alt(asset_class: str) -> list[PanelRow]:
    from eulerlab.features import alt_panel

    if asset_class == AssetClass.CRYPTO.value:
        return alt_panel.crypto_daily()
    if asset_class == AssetClass.MUTUAL_FUND.value:
        return alt_panel.fund_daily()
    if asset_class == AssetClass.FX.value:
        return alt_panel.fx_daily()
    if asset_class == AssetClass.US.value:
        return alt_panel.us_daily()
    msg = f"no panel for asset class {asset_class!r}"
    raise ValueError(msg)


ALT = _AltPanel()

COSTED_CLASSES = frozenset({AssetClass.EQUITY.value, AssetClass.FX.value, AssetClass.US.value})
"""Asset classes the cost model actually covers.

`costs/schedule.py` has segments for equity delivery, equity intraday, futures
and options — all Indian exchange-traded. Running a Binance spot trade or a
mutual fund redemption through EQUITY_DELIVERY would apply STT, stamp duty and
NSE charges to something none of them touch, and produce a confidently wrong
number rather than an obviously missing one.

So crypto and fund runs are executed gross of costs and labelled as such. That
is a real limitation, recorded in docs/STUBS.md, not a rounding decision: a
crypto strategy rebalancing every 21 days pays real Binance taker fees, and a
result that ignores them is an upper bound.

**FX is the exception, and for a reason worth stating.** It also pays none of
the Indian charges — but its cost is the bid-ask spread, which is *measured* in
the landed data and carried on every `PanelRow`. Charging what was observed is
not the same kind of act as inventing a fee schedule, so FX runs costed.

**US is costed too, from its own published schedule** — `costs/us_equity.py`,
the SEC Section 31 rate and the FINRA TAF, both verified against the regulator.
It must never fall through to the Indian segments: a QQQ trade charged STT and
stamp duty is the same error as the crypto one above, and it has already
happened once in the intraday engine.
"""


def _rows_for(asset_class: str, days: int) -> list[PanelRow]:
    """The daily bars for one asset class, trimmed to the window."""
    if asset_class == AssetClass.EQUITY.value:
        return PANEL.rows(days)
    return ALT.rows(asset_class, days)


def _no_panel_message(asset_class: str) -> str:
    if asset_class == AssetClass.CRYPTO.value:
        return "no crypto landed. Run `make crypto` first."
    if asset_class == AssetClass.FX.value:
        return "no FX landed. Run `make fx-bulk` first."
    if asset_class == AssetClass.US.value:
        return "no US bars landed. Run `make us-bars` first."
    if asset_class == AssetClass.MUTUAL_FUND.value:
        return "no mutual fund NAV history landed. Run `make mf` first."
    return "no panel on disk. Run `make build-panel` first."


def cost_mode_for(asset_class: str) -> str:
    """`realistic` where the cost model applies, `replication` where it does not."""
    return "realistic" if asset_class in COSTED_CLASSES else "replication"
