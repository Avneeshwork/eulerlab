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
from datetime import date

from eulerlab.backtest.vector import build_adjusted_index
from eulerlab.features.panel import PANEL_PATH, PanelRow, read_panel
from eulerlab.strategies import AssetClass


class _Panel:
    """One copy of the panel and its adjusted index, shared by every request.

    Guarded by a lock because two requests arriving together would otherwise
    both start a 540 MB read. The index is keyed by the day-window so the
    common case — the same last-N-days repeatedly — is computed once.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: list[PanelRow] | None = None
        self._stamp: int | None = None
        self._per_symbol: dict[str, int] = {}
        self._days: list[date] = []
        self._starts: list[int] = []
        """The trading days, and where each one's rows begin. The rows are in
        day order, so "the last N days" is a slice. It used to be a pass over
        all 5.4 million rows to list the days and another to filter them:
        1.2 to 1.9 seconds on every request that asked (measured 2026-10-12)."""
        self._indices: dict[tuple[int, str], dict[str, dict[date, float]]] = {}

    def rows(self, days: int = 0) -> list[PanelRow]:
        with self._lock:
            # Re-read when `make daily` has rebuilt the file. Held forever, a
            # server started before the rebuild kept trading days that were
            # already stale: a deployment made on 2026-10-07 started on the
            # 1 Oct close and showed nothing to trade (T-4025).
            stamp = PANEL_PATH.stat().st_mtime_ns if PANEL_PATH.exists() else None
            if self._rows is None or stamp != self._stamp:
                self._rows = read_panel()
                self._stamp = stamp
                self._indices.clear()
                self._days, self._starts, self._per_symbol = [], [], {}
                counts = self._per_symbol
                for position, row in enumerate(self._rows):
                    if not self._days or row.day != self._days[-1]:
                        self._days.append(row.day)
                        self._starts.append(position)
                    counts[row.symbol] = counts.get(row.symbol, 0) + 1
            rows, starts = self._rows, self._starts
        if not days or days >= len(starts):
            return rows
        return rows[starts[-days] :]

    def days(self) -> list[date]:
        """Every trading day in the panel, oldest first."""
        self.rows()
        return self._days

    def coverage(self) -> dict[str, object]:
        """What the panel contains: the figures `alt_panel.coverage` gives.

        Counted in the pass that loads the panel. Two routes used to walk all
        5.4 million rows on each request to count symbols (0.5 s and 1.7 s).
        """
        rows = self.rows()
        if not rows:
            return {"rows": 0, "symbols": 0, "days": 0, "first": None, "last": None}
        return {
            "rows": len(rows),
            "symbols": len(self._per_symbol),
            "days": len(self._days),
            "first": self._days[0].isoformat(),
            "last": self._days[-1].isoformat(),
            "thinnest": min(self._per_symbol.values()),
            "fattest": max(self._per_symbol.values()),
        }

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
        return self._rows is not None


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
        self._stamp: int | None = None

    def rows(self, asset_class: str, days: int = 0) -> list[PanelRow]:
        with self._lock:
            # Dropped when the landing census changes. Every mirror rewrites
            # it — the Instruments button and `make daily` alike — so a feed
            # run reaches these panels without restarting the server. Held
            # forever, they showed whatever had landed when the API started
            # (T-4032), the same fault T-4025 fixed for the equity panel.
            stamp = _census_stamp()
            if stamp != self._stamp:
                self._rows.clear()
                self._stamp = stamp
            if asset_class not in self._rows:
                self._rows[asset_class] = _load_alt(asset_class)
        rows = self._rows[asset_class]
        if not days:
            return rows
        # Trailing N *trading* days, matching `_Panel.rows`. Crypto trades every
        # day and funds only on business days, so neither is forced onto the NSE
        # calendar; "trading days" is whatever days the data actually has.
        all_days = sorted({r.day for r in rows})
        if days >= len(all_days):
            return rows
        cutoff = all_days[-days]
        return [r for r in rows if r.day >= cutoff]

    def loaded(self, asset_class: str) -> bool:
        return asset_class in self._rows


def _census_stamp() -> int | None:
    from eulerlab.ingest import manifest

    return manifest.PATH.stat().st_mtime_ns if manifest.PATH.exists() else None


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
