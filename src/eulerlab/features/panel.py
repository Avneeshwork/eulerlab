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
import mmap
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


def canonical_symbols(rows: list[PanelRow]) -> list[PanelRow]:
    """Every row under the latest symbol its ISIN traded as, so a renamed stock
    is one history, not two.

    The engine keys positions by symbol, and until 2026-10-18 a stock renamed
    while held (TATAGLOBAL -> TATACONSUM) became a position that could never be
    sold or re-priced again, while the strategy bought around it with cash it
    did not have (HISTORY #28). CLAUDE.md: instrument joins use internal IDs,
    never a ticker. The ISIN is the internal ID the panel carries.

    Rows sharing a symbol are never split (an ISIN that changes on a
    face-value split keeps its symbol). On a day both names have a row, the row
    already under the current name is kept. `rows` must be in day order; only
    the days that changed are re-sorted.
    """
    latest: dict[str, tuple[date, str]] = {}
    for row in rows:
        if row.isin and (row.isin not in latest or row.day >= latest[row.isin][0]):
            latest[row.isin] = (row.day, row.symbol)
    out: list[PanelRow] = []
    renamed: list[bool] = []
    changed_days: set[date] = set()
    for row in rows:
        target = latest.get(row.isin, (row.day, row.symbol))[1] if row.isin else row.symbol
        if target != row.symbol:
            moved = object.__new__(PanelRow)
            object.__setattr__(moved, "__dict__", {**row.__dict__, "symbol": target})
            out.append(moved)
            renamed.append(True)
            changed_days.add(row.day)
        else:
            out.append(row)
            renamed.append(False)
    if not changed_days:
        return out
    result: list[PanelRow] = []
    begin = 0
    for end in range(1, len(out) + 1):
        if end == len(out) or out[end].day != out[begin].day:
            if out[begin].day in changed_days:
                kept: dict[str, tuple[bool, PanelRow]] = {}
                for k in range(begin, end):
                    row, was_renamed = out[k], renamed[k]
                    # A row already under the current name beats a renamed one.
                    if row.symbol not in kept or (kept[row.symbol][0] and not was_renamed):
                        kept[row.symbol] = (was_renamed, row)
                result.extend(r for _, r in sorted(kept.values(), key=lambda x: x[1].symbol))
            else:
                result.extend(out[begin:end])
            begin = end
    return result


def read_panel(path: Path = PANEL_PATH, *, canonical: bool = True) -> list[PanelRow]:
    """Load the cached panel, oldest first, under each ISIN's current symbol
    (`canonical_symbols`; `canonical=False` for the names as stored).

    This is the server's cold start: 5.4 million lines, 746 MB. It took 51
    seconds (measured 2026-10-12) and now takes about a quarter of that, from
    five changes, none of them a cache:

    - the file is read a line at a time, not into one 746 MB string and then a
      5.4-million-item list of lines;
    - `orjson` parses each line (the standard parser was a third slower);
    - a day is parsed once, not once per row: 2,900 dates, not 5.4 million;
    - only the days whose symbols are out of order are sorted, and the whole
      file only if its days are.
    """
    if not path.exists():
        return []
    import orjson

    out: list[PanelRow] = []
    append, new_row, set_fields = out.append, object.__new__, object.__setattr__
    days: dict[str, date] = {}
    # Whether the days come in order, and which days' symbols do not. The
    # appender writes days in order but not always their symbols, and sorting
    # 5.4 million rows by a Python key for that is 5.4 million key calls;
    # sorting the few days that need it is a few thousand.
    days_ordered, last_stamp, last_symbol = True, "", ""
    starts: list[int] = []
    unsorted_days: list[int] = []
    with path.open("rb") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = orjson.loads(line)
            stamp = row["d"]
            day = days.get(stamp)
            if day is None:
                day = days[stamp] = date.fromisoformat(stamp)
            symbol = row["s"]
            if stamp != last_stamp:
                # ISO dates sort as text exactly as they sort as dates.
                if stamp < last_stamp:
                    days_ordered = False
                starts.append(len(out))
                last_stamp = stamp
            elif symbol < last_symbol and (
                not unsorted_days or unsorted_days[-1] != len(starts) - 1
            ):
                unsorted_days.append(len(starts) - 1)
            last_symbol = symbol
            # Built without `PanelRow.__init__`. A frozen dataclass sets each
            # of its ten fields through `object.__setattr__`, and for 5.4
            # million rows that was a third of the whole read. Handing the row
            # its fields in one step gives the same object: equal, same hash,
            # same repr. `tests/test_dashboard_speed.py` holds this to
            # `PanelRow(...)` and to the dataclass's field list, so a field
            # added to `PanelRow` and not here fails a test, not a backtest.
            built = new_row(PanelRow)
            set_fields(
                built,
                "__dict__",
                {
                    "day": day,
                    "symbol": symbol,
                    "close": row["c"],
                    "volume": row["v"],
                    "turnover": row["t"],
                    "isin": row.get("i", row.get("isin", "")),
                    "spread": 0.0,
                    "open": row.get("o", 0.0),
                    "high": row.get("h", 0.0),
                    "low": row.get("l", 0.0),
                },
            )
            append(built)
    if not days_ordered:
        out.sort(key=lambda r: (r.day, r.symbol))
        return canonical_symbols(out) if canonical else out
    starts.append(len(out))
    for index in unsorted_days:
        begin, end = starts[index], starts[index + 1]
        out[begin:end] = sorted(out[begin:end], key=lambda r: r.symbol)
    return canonical_symbols(out) if canonical else out


def read_symbol_rows(symbol: str, days: int, path: Path = PANEL_PATH) -> list[PanelRow]:
    """Read the recent history for one symbol, canonicalizing ticker changes.

    The panel is ordered by date, so scanning backwards finds recent bars
    first. It parses only rows for the requested symbol and ISINs discovered
    under its current name, preserving the same rename handling as
    `canonical_symbols` while avoiding a full-panel object build.
    """
    if not path.exists() or days <= 0 or path.stat().st_size == 0:
        return []

    import orjson

    marker = f'"s": "{symbol}"'.encode("ascii")
    by_day: dict[date, tuple[bool, PanelRow]] = {}
    instruments: set[str] = set()

    def reverse_offsets(data: mmap.mmap, token: bytes) -> Iterator[int]:
        end = len(data)
        chunk_size = 16 * 1024 * 1024
        while end > 0:
            start = max(0, end - chunk_size)
            search_end = min(len(data), end + len(token) - 1)
            while (found := data.rfind(token, start, search_end)) >= 0:
                if found < end:
                    yield found
                search_end = found
            end = start

    def add_line(data: mmap.mmap, position: int, *, direct: bool) -> None:
        start = data.rfind(b"\n", 0, position) + 1
        end = data.find(b"\n", position)
        row = orjson.loads(data[start : len(data) if end < 0 else end])
        isin = row.get("i", row.get("isin", ""))
        if direct and isin:
            instruments.add(isin)
        day = date.fromisoformat(row["d"])
        panel_row = PanelRow(
            day=day,
            symbol=symbol,
            close=row["c"],
            volume=row["v"],
            turnover=row["t"],
            isin=isin,
            open=row.get("o", 0.0),
            high=row.get("h", 0.0),
            low=row.get("l", 0.0),
        )
        previous = by_day.get(day)
        if previous is None or (direct and not previous[0]):
            by_day[day] = (direct, panel_row)

    with path.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as data:
        # Newest rows are at the end. Read only enough direct bars for the
        # common case; aliases are needed only if that history is shorter.
        for position in reverse_offsets(data, marker):
            add_line(data, position, direct=True)
            if len(by_day) >= days:
                break

        if len(by_day) < days and instruments:
            # A recently renamed ticker may have fewer than five years under
            # its current name. Pull older rows for each discovered ISIN.
            for isin in instruments:
                for field in (b'"isin": "', b'"i": "'):
                    token = field + isin.encode("ascii") + b'"'
                    for position in reverse_offsets(data, token):
                        start = data.rfind(b"\n", 0, position) + 1
                        end = data.find(b"\n", position)
                        row = orjson.loads(data[start : len(data) if end < 0 else end])
                        if row["s"] != symbol:
                            add_line(data, position, direct=False)

    return [by_day[day][1] for day in sorted(by_day)]


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
    # A panel is read oldest first, so each history arrives already in order.
    # Only one that did not is sorted: sorting all of them cost four million
    # key calls on the full panel to change nothing.
    unordered: set[str] = set()
    for row in rows:
        history = out.get(row.symbol)
        if history is None:
            out[row.symbol] = [row]
            continue
        if row.day < history[-1].day:
            unordered.add(row.symbol)
        history.append(row)
    for symbol in unordered:
        out[symbol].sort(key=lambda r: r.day)
    return out


def trading_days(rows: Sequence[PanelRow]) -> list[date]:
    # A panel's rows come in runs of one day. A row whose day is the previous
    # row's is skipped without hashing it, which is nearly every row.
    found: set[date] = set()
    previous: date | None = None
    for row in rows:
        day = row.day
        if day is not previous and day != previous:
            found.add(day)
            previous = day
    return sorted(found)


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
