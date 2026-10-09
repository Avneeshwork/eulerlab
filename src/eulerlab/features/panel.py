"""The adjusted price panel every feature reads from.

A feature is a function of many symbols over many dates, so the panel is the
one expensive thing in this sprint: roughly 2,100 cash bhavcopy files from B2
against a 2,500/day cap. It is therefore built **once and cached**, exactly
like the close index in `corp_actions/prices.py`, and every feature and every
IC run afterwards costs nothing.

**Prices here are RAW, and that is deliberate — but it was a bug first.**

The original version tried to bake adjustment in at write time, calling
`factor_as_of(as_of=<the row's own day>, price_date=<the same day>)`. Those two
conditions are mutually exclusive: a factor exists only for actions knowable by
`as_of`, and applies only to prices dated *before* the action. With both set to
the same day the divisor was **always 1.0**, so the panel was unadjusted while
this docstring claimed otherwise. Measured: TCS on 2018-01-15 got divisor 1.000
where the correct back-adjustment is 2.000 (1:1 bonus, ex 2018-05-31).

The deeper reason it could not work is that **a static panel cannot hold
point-in-time adjusted prices at all.** The right adjustment depends on the
date you are standing on: a strategy deciding on 2018-01-15 must not see prices
adjusted for a bonus that goes ex in May. So the panel stores what the exchange
printed, and adjustment happens where `as_of` is known — in
`MarketView` construction, per decision date. See `backtest/strategy.py`.

**The panel is stored long, not wide.** One row per symbol-date rather than a
matrix, because the universe changes: symbols list, delist, and get renamed,
so a wide matrix would be mostly holes and would silently encode a
survivorship decision in its column list. `at(as_of)` reconstructs the
cross-section that actually existed on a date.
"""

from __future__ import annotations

import concurrent.futures as cf
import json
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from eulerlab.bitemporal.store import BitemporalStore, Record
from eulerlab.corp_actions.build_factors import PRICE_FACTORS
from eulerlab.corp_actions.prices import instrument_key
from eulerlab.quality.sources import bars_from_bhavcopy

IST = ZoneInfo("Asia/Kolkata")
PANEL_PATH = Path("data/derived/price_panel.jsonl")
NSE_MANIFEST = Path("data/landing/nse/manifest.jsonl")


@dataclass(frozen=True)
class PanelRow:
    """One symbol on one date, adjusted."""

    day: date
    symbol: str
    close: float
    """RAW exchange close. Adjustment is applied per decision date when a
    `MarketView` is built, never here — see the module docstring."""
    volume: float
    turnover: float
    isin: str = ""
    """Internal instrument key, for joining to corporate-action factors."""

    spread: float = 0.0
    """Measured cost of crossing, in price units. Zero for equities.

    FX has no exchange, no STT and no stamp duty — its transaction cost *is*
    the bid-ask spread, and it varies by pair and by hour. Carrying the
    measured value per row means an FX backtest can charge what the data
    actually showed rather than a rate invented for it, which is the difference
    between a cost model and a guess (S-028).
    """

    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    """RAW exchange open/high/low, same convention as `close`.

    Optional, and zero means "not recorded". The panel stored only the close
    until candlestick strategies needed the shape of the bar; every day since
    2015 was re-read from NSE's archive on 2026-10-07 (`make rebuild-ohlc`),
    so the panel on disk now carries all four. They stay optional because a
    panel built before then, or a row from another source, may not: they
    default to zero and `ohlc()` falls back to the close.

    Use `ohlc()` rather than reading these directly; a strategy that reads
    `row.high` on an older row silently gets 0.0 and computes nonsense."""

    def adjusted(self, divisor: float) -> PanelRow:
        """This row back-adjusted for corporate actions: every price divided.

        Open, high and low with the close, not the close alone. Adjusting only
        the close left a pre-split bar whose high sat far above its close, so
        any range — ATR, a Donchian high, a candle body — read a corporate
        action as a price move. A zero (not recorded) stays zero.
        """
        if divisor == 1.0:
            return self
        return replace(
            self,
            close=self.close / divisor,
            open=self.open / divisor,
            high=self.high / divisor,
            low=self.low / divisor,
        )

    def ohlc(self) -> tuple[float, float, float, float]:
        """Open, high, low, close — falling back to a flat bar at the close.

        A flat bar is the honest degradation: it says "this day had no recorded
        range", which makes every candle-shape test fail rather than pass on a
        fabricated body. Silently inventing a range would turn missing data
        into signals."""
        if self.high <= 0.0 or self.low <= 0.0:
            return (self.close, self.close, self.close, self.close)
        return (self.open or self.close, self.high, self.low, self.close)

    def has_range(self) -> bool:
        """True when this row carries a real intraday range."""
        return self.high > 0.0 and self.low > 0.0 and self.high >= self.low

    def key(self) -> tuple[date, str]:
        return (self.day, self.symbol)


MANUAL_PRICE_FACTORS = Path("config/manual_price_factors.jsonl")


def load_price_factor_store(path: Path = PRICE_FACTORS) -> BitemporalStore:
    """Rebuild the bitemporal factor store from the persisted JSONL.

    Read back through `BitemporalStore` rather than applied as a flat lookup,
    so the panel build inherits Sprint 4's firewall: a factor cannot be
    applied to a date before it was knowable.
    """
    store = BitemporalStore()
    lines: list[str] = []
    if path.exists():
        lines += path.read_text(encoding="utf-8").splitlines()
    # Actions NSE's equity corporate-actions feed never carries — an ETF's
    # unit split — added by hand with their evidence (A-043). Read only beside
    # the real factor file, so a test pointing `path` elsewhere stays isolated.
    if path == PRICE_FACTORS and MANUAL_PRICE_FACTORS.exists():
        lines += MANUAL_PRICE_FACTORS.read_text(encoding="utf-8").splitlines()
    for line in lines:
        if not line.strip():
            continue
        row = json.loads(line)
        # Keyed by InstrumentId, not the raw ISIN the file stores. The feed and
        # the bhavcopy disagree about trailing ISIN serials for the same
        # company (ADR-012), and joining on the raw string lost 21.9% of
        # lookups in Sprint 5. The panel would have failed more quietly still:
        # a missed factor is silently 1.0, i.e. no adjustment at all.
        key = instrument_key(str(row["isin"]))
        if key is None:
            continue
        store.append(
            Record(
                datetime.fromisoformat(row["event_time"]),
                datetime.fromisoformat(row["knowledge_time"]),
                key,
                float(row["factor"]),
            )
        )
    return store


def _cash_files(manifest: Path, *, start: str, end: str) -> list[tuple[str, str]]:
    if not manifest.exists():
        return []
    seen: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("segment") == "cm" and start <= str(row["trade_date"]) <= end:
            seen[str(row["trade_date"])] = str(row["path"])
    return sorted(seen.items())


def read_panel(path: Path = PANEL_PATH) -> list[PanelRow]:
    """Load the cached panel, oldest first."""
    if not path.exists():
        return []
    out: list[PanelRow] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        out.append(
            PanelRow(
                day=date.fromisoformat(row["d"]),
                symbol=row["s"],
                close=row["c"],
                volume=row["v"],
                turnover=row["t"],
                isin=row.get("i", row.get("isin", "")),
                open=row.get("o", 0.0),
                high=row.get("h", 0.0),
                low=row.get("l", 0.0),
            )
        )
    out.sort(key=lambda r: (r.day, r.symbol))
    return out


class UnadjustablePanel(RuntimeError):
    """The panel predates the ISIN column, so it cannot be adjusted."""


def assert_adjustable(rows: Sequence[PanelRow], *, sample: int = 5000) -> None:
    """Fail loudly if the panel cannot be joined to corporate actions.

    Without an instrument key there is nothing to look a factor up by, so the
    adjustment silently does nothing — which is precisely the bug this whole
    change exists to remove. Returning quietly here would reintroduce it one
    layer up, so a panel written before the ISIN column raises instead.
    """
    checked = rows[:sample]
    if checked and not any(r.isin for r in checked):
        msg = (
            "this panel carries no instrument key, so corporate-action factors "
            "cannot be applied and every price is raw. It was written before the "
            "ISIN column existed. Rebuild it: `make build-panel FROM=2015-01-01`."
        )
        raise UnadjustablePanel(msg)


def cached_days(path: Path = PANEL_PATH) -> set[str]:
    if not path.exists():
        return set()
    return {
        json.loads(line)["d"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def build(
    *,
    start: str,
    end: str,
    manifest: Path = NSE_MANIFEST,
    path: Path = PANEL_PATH,
    max_workers: int = 8,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[int, str]:
    """Fetch, adjust and append. Returns (days written, note).

    Resumable and append-only: a run stopped by the daily cap keeps everything
    it wrote, and the next run skips those days. `note` explains an early stop
    rather than raising, because being capped is expected rather than broken.

    Held under the `panel` lock, and the cache is read inside it: two builders
    that each read "8 Oct missing" before either wrote would both append it.
    """
    from eulerlab.ingest.filelock import exclusive

    with exclusive("panel", directory=path.parent / ".locks"):
        return _build(
            start=start,
            end=end,
            manifest=manifest,
            path=path,
            max_workers=max_workers,
            progress=progress,
        )


def _build(
    *,
    start: str,
    end: str,
    manifest: Path,
    path: Path,
    max_workers: int,
    progress: Callable[[int, int], None] | None,
) -> tuple[int, str]:
    already = cached_days(path)
    wanted = [(d, p) for d, p in _cash_files(manifest, start=start, end=end) if d not in already]
    if not wanted:
        return 0, ""

    # A day still in the local landing zone (today's, before `prune-local`) is
    # read from disk, so the panel does not wait on the cloud sync. Only pruned
    # days go to B2 — on 2026-10-08 a failed sync left the paper books a day
    # behind (RUNBOOKS/paper-books-behind.md).
    root = manifest.parent
    client: Any = None
    if any(not (root / key).exists() for _, key in wanted):
        import boto3

        from eulerlab.env import require

        client = boto3.client(
            "s3",
            endpoint_url="https://s3.us-west-004.backblazeb2.com",
            aws_access_key_id=require("B2_KEY_ID"),
            aws_secret_access_key=require("B2_APP_KEY"),
        )

    def fetch(item: tuple[str, str]) -> tuple[str, bytes]:
        trade_date, key = item
        local = root / key
        if local.exists():
            return trade_date, local.read_bytes()
        return trade_date, client.get_object(Bucket="eulerdata", Key=f"nse/{key}")["Body"].read()

    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    note = ""

    with path.open("a", encoding="utf-8") as handle:
        try:
            with cf.ThreadPoolExecutor(max_workers=max_workers) as pool:
                for trade_date, payload in pool.map(fetch, wanted):
                    day = date.fromisoformat(trade_date)
                    for bar in bars_from_bhavcopy(payload, day):
                        handle.write(
                            json.dumps(
                                {
                                    "d": trade_date,
                                    "s": bar.symbol,
                                    "c": round(bar.close, 6),
                                    "o": round(bar.open, 6),
                                    "h": round(bar.high, 6),
                                    "l": round(bar.low, 6),
                                    "isin": instrument_key(bar.isin) or "",
                                    "v": bar.volume,
                                    "t": bar.turnover or 0.0,
                                },
                                sort_keys=True,
                            )
                            + "\n"
                        )
                    handle.flush()
                    written += 1
                    if progress is not None:
                        progress(written, len(wanted))
        except Exception as exc:
            if "cap exceeded" not in str(exc).lower():
                raise
            note = (
                f"stopped after {written} of {len(wanted)} days: B2 daily cap reached. "
                f"Re-run to resume; nothing already written is lost."
            )
    return written, note


def cross_section(rows: Sequence[PanelRow], day: date) -> dict[str, PanelRow]:
    """The symbols that actually existed on `day`."""
    return {r.symbol: r for r in rows if r.day == day}


def by_symbol(rows: Sequence[PanelRow]) -> dict[str, list[PanelRow]]:
    """Each symbol's history, oldest first."""
    out: dict[str, list[PanelRow]] = {}
    for row in rows:
        out.setdefault(row.symbol, []).append(row)
    for history in out.values():
        history.sort(key=lambda r: r.day)
    return out


def trading_days(rows: Sequence[PanelRow]) -> list[date]:
    return sorted({r.day for r in rows})


def iter_rows(path: Path = PANEL_PATH) -> Iterator[PanelRow]:
    """Stream the panel without holding it all in memory."""
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            yield PanelRow(
                day=date.fromisoformat(row["d"]),
                symbol=row["s"],
                close=row["c"],
                volume=row["v"],
                turnover=row["t"],
                open=row.get("o", 0.0),
                high=row.get("h", 0.0),
                low=row.get("l", 0.0),
            )
