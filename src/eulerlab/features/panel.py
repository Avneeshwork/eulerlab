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
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
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

    def key(self) -> tuple[date, str]:
        return (self.day, self.symbol)


def load_price_factor_store(path: Path = PRICE_FACTORS) -> BitemporalStore:
    """Rebuild the bitemporal factor store from the persisted JSONL.

    Read back through `BitemporalStore` rather than applied as a flat lookup,
    so the panel build inherits Sprint 4's firewall: a factor cannot be
    applied to a date before it was knowable.
    """
    store = BitemporalStore()
    if not path.exists():
        return store
    for line in path.read_text(encoding="utf-8").splitlines():
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
    """
    already = cached_days(path)
    wanted = [(d, p) for d, p in _cash_files(manifest, start=start, end=end) if d not in already]
    if not wanted:
        return 0, ""

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
            )
