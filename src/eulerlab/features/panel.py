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
import contextlib
import gc
import hashlib
import json
import mmap
import os
from bisect import bisect_left
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, fields, replace
from datetime import date, datetime, timedelta
from operator import attrgetter
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from eulerlab.bitemporal.store import BitemporalStore, Record
from eulerlab.corp_actions.build_factors import PRICE_FACTORS, cached_dates
from eulerlab.corp_actions.prices import instrument_key
from eulerlab.filecache import FileMemo
from eulerlab.quality.sources import bars_from_bhavcopy

IST = ZoneInfo("Asia/Kolkata")
PANEL_PATH = Path("data/derived/price_panel.jsonl")
NSE_MANIFEST = Path("data/landing/nse/manifest.jsonl")


@dataclass(frozen=True, slots=True)
class PanelRow:
    """One symbol on one date, adjusted.

    Slotted: 5.4 million of these are held in the API's memory. With a
    `__dict__` each the loaded panel took 2.8 GB on an 8.6 GB machine that was
    already swapping; slotted, with shared symbol strings, 1.7 GB (2026-10-27)."""

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

        Volume is multiplied by the same divisor, so it is counted in today's
        shares. Left raw, a 1:10 split made every pre-split day trade a tenth
        of its true volume, and a volume-ratio feature read the split as a
        tenfold spike (2026-11-01 audit). Turnover is rupees and does not
        change with a split, so it is left alone.
        """
        if divisor == 1.0:
            return self
        return replace(
            self,
            close=self.close / divisor,
            open=self.open / divisor,
            high=self.high / divisor,
            low=self.low / divisor,
            volume=self.volume * divisor,
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


_FIELDS = tuple(f.name for f in fields(PanelRow))
_SETTERS: dict[str, Callable[[PanelRow, object], None]] = {
    name: getattr(PanelRow, name).__set__ for name in _FIELDS
}
"""Each slot's own setter, which a frozen dataclass's `__setattr__` does not block."""


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


PANEL_SOURCE = "Cash bhavcopy"
"""The register name (`config/data_sources.yaml`) of the files the panel is built from."""


def _cash_shas(manifest: Path) -> dict[str, str]:
    """Landed path -> the SHA-256 recorded when it landed, for cash bhavcopies."""
    if not manifest.exists():
        return {}
    out: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("segment") == "cm" and row.get("sha256"):
            out[str(row["path"])] = str(row["sha256"])
    return out


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
    # In day order the last row seen for an ISIN is on its latest day, so a
    # plain assignment leaves the latest symbol (on a tie, the later row, as
    # the `>=` comparison this replaced did).
    latest = {row.isin: row.symbol for row in rows if row.isin}
    moved_at = [i for i, row in enumerate(rows) if row.isin and latest[row.isin] != row.symbol]
    if not moved_at:
        return list(rows)
    # Each day is already sorted by symbol. Only its renamed rows move: they
    # are taken out and put back under the current name by binary search, so
    # no day is walked or re-sorted row by row. 444,603 rows on all 2,916 days
    # carry an older name; rebuilding every day in Python took 10-17 s, as
    # long as parsing the file (2026-10-27).
    by_symbol = attrgetter("symbol")
    result: list[PanelRow] = []
    cursor = 0
    position = 0
    while position < len(moved_at):
        first = moved_at[position]
        day = rows[first].day
        begin, end = first, first + 1
        while begin > 0 and rows[begin - 1].day == day:
            begin -= 1
        while end < len(rows) and rows[end].day == day:
            end += 1
        mine: list[int] = []
        while position < len(moved_at) and moved_at[position] < end:
            mine.append(moved_at[position])
            position += 1
        result.extend(rows[cursor:begin])
        today = rows[begin:end]
        for index in reversed(mine):
            del today[index - begin]
        for index in mine:
            row = rows[index]
            target = latest[row.isin]
            spot = bisect_left(today, target, key=by_symbol)
            # A row already under the current name, or an earlier renamed one,
            # keeps the place.
            if spot < len(today) and today[spot].symbol == target:
                continue
            today.insert(spot, _with_symbol(row, target))
        result.extend(today)
        cursor = end
    result.extend(rows[cursor:])
    return result


def _with_symbol(row: PanelRow, symbol: str) -> PanelRow:
    """`replace(row, symbol=...)` without `__init__`'s frozen check per field."""
    moved = object.__new__(PanelRow)
    for name, put in _SETTERS.items():
        put(moved, symbol if name == "symbol" else getattr(row, name))
    return moved


@contextlib.contextmanager
def _collector_paused() -> Iterator[None]:
    """No cyclic garbage collection while millions of rows are allocated.

    The collector's full passes rescan every tracked object, and while the
    panel grows that is all of it, again and again. Rows hold no cycles, so
    nothing is missed: reference counting still frees everything. Measured on
    the real panel: 19.2 s with the collector, 16.5 s without (2026-10-27).
    """
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        if was_enabled:
            gc.enable()


def read_panel(path: Path = PANEL_PATH, *, canonical: bool = True) -> list[PanelRow]:
    """Load the cached panel, oldest first, under each ISIN's current symbol
    (`canonical_symbols`; `canonical=False` for the names as stored).

    The renamed rows come from the columnar copy when it was made from this
    exact file (see `COLUMNS_DIR`); otherwise from the JSONL, which then writes
    that copy. Renaming depends only on the file, so the copy holds its result
    rather than redoing it on every read (6 s). The names as stored are always
    read from the JSONL.
    """
    if not path.exists():
        return []
    if not canonical:
        return _parse_jsonl(path)
    rows = _read_columns(path)
    if rows is None:
        raw = _parse_jsonl(path)
        renamed = renamed_names(raw)
        rows = canonical_symbols(raw)
        _write_columns(path, rows, renamed)
    return rows


def renamed_names(rows: Sequence[PanelRow]) -> frozenset[str]:
    """Every symbol a rename touches: a stored name whose rows `canonical_symbols`
    moves, and every name rows are moved to.

    For any other symbol, the loaded panel and `read_symbol_rows` give the same
    rows. For these they can differ: an ISIN that changed (GOLDSHARE's
    face-value split in 2021) or a DVR merged into its parent (GATECHDVR) puts
    rows under different tickers in the two readers (2026-10-27)."""
    latest = {row.isin: row.symbol for row in rows if row.isin}
    names: set[str] = set()
    for row in rows:
        if row.isin and latest[row.isin] != row.symbol:
            names.add(row.symbol)
            names.add(latest[row.isin])
    return frozenset(names)


def stored_renames(path: Path = PANEL_PATH) -> frozenset[str] | None:
    """`renamed_names` of the panel file, from its columnar copy; None when the
    copy is missing or was made from a different file. The copy's metadata is
    read once per version of the copy; the match to `path` is checked on every
    call, so a changed panel file is never answered for."""
    target = _columns_file(path)
    if target is None or not target.exists():
        return None
    metadata = _COPY_METADATA(target)
    if metadata is None or not all(metadata.get(k) == v for k, v in _source_stamp(path).items()):
        return None
    try:
        return frozenset(json.loads(metadata[b"renamed_symbols"]))
    except (KeyError, ValueError):
        return None


def _metadata_of(target: Path) -> dict[bytes, bytes] | None:
    import pyarrow.parquet as pq

    try:
        return dict(pq.read_schema(target).metadata or {})
    except (OSError, ValueError):
        return None


_COPY_METADATA = FileMemo(_metadata_of, size=2)


def _parse_jsonl(path: Path) -> list[PanelRow]:
    """Every line of the panel file, days in order and symbols sorted within a day.

    This was the server's cold start: 5.4 million lines, 746 MB. It took 51
    seconds (measured 2026-10-12) and then about a quarter of that, from five
    changes:

    - the file is read a line at a time, not into one 746 MB string and then a
      5.4-million-item list of lines;
    - `orjson` parses each line (the standard parser was a third slower);
    - a day is parsed once, not once per row: 2,900 dates, not 5.4 million;
    - only the days whose symbols are out of order are sorted, and the whole
      file only if its days are.
    """
    import orjson

    out: list[PanelRow] = []
    append, new_row = out.append, object.__new__
    # The slots' own setters: a frozen dataclass's `__setattr__` refuses, and
    # `PanelRow(...)` pays for the frozen check on each of ten fields.
    (
        set_day,
        set_symbol,
        set_close,
        set_volume,
        set_turnover,
        set_isin,
        set_spread,
        set_open,
        set_high,
        set_low,
    ) = (getattr(PanelRow, f.name).__set__ for f in fields(PanelRow))
    days: dict[str, date] = {}
    # One string per symbol and ISIN, not one per row: 10.8 million strings
    # were about 600 MB of the panel's memory.
    shared: dict[str, str] = {}
    # Whether the days come in order, and which days' symbols do not. The
    # appender writes days in order but not always their symbols, and sorting
    # 5.4 million rows by a Python key for that is 5.4 million key calls;
    # sorting the few days that need it is a few thousand.
    days_ordered, last_stamp, last_symbol = True, "", ""
    starts: list[int] = []
    unsorted_days: list[int] = []
    with path.open("rb") as handle, _collector_paused():
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
            # Built without `PanelRow.__init__`, through the slot setters:
            # the frozen check on ten fields was a third of the whole read.
            # `tests/test_dashboard_speed.py` holds this to `PanelRow(...)` and
            # to the dataclass's field list, so a field added to `PanelRow` and
            # not here fails a test, not a backtest.
            symbol = shared.setdefault(symbol, symbol)
            isin = row.get("i", row.get("isin", ""))
            built = new_row(PanelRow)
            set_day(built, day)
            set_symbol(built, symbol)
            set_close(built, row["c"])
            set_volume(built, row["v"])
            set_turnover(built, row["t"])
            set_isin(built, shared.setdefault(isin, isin))
            set_spread(built, 0.0)
            set_open(built, row.get("o", 0.0))
            set_high(built, row.get("h", 0.0))
            set_low(built, row.get("l", 0.0))
            append(built)
    if not days_ordered:
        out.sort(key=lambda r: (r.day, r.symbol))
        return out
    starts.append(len(out))
    for index in unsorted_days:
        begin, end = starts[index], starts[index + 1]
        out[begin:end] = sorted(out[begin:end], key=lambda r: r.symbol)
    return out


# --- the columnar copy ------------------------------------------------------------

COLUMNS_DIR = Path("data/cache")
"""Where the panel's columnar copy lives. Not `data/derived/`, which
`make sync-derived` uploads whole; this is a copy of a file already there.

Reading 5.4 million JSON lines took about 27 s of CPU; the same rows from
Parquet columns take about 8 s (2026-10-27). While the read runs it holds the
interpreter lock, and every request in that time waited for it: `/api/data`
took 0.29 s alone and 4 s during a read. The copy records the JSONL's size and
modification time and is used only while both still match, so it can never
answer for a different panel. It is made only from the default panel path."""

COLUMNS_VERSION = "3"
"""Bumped whenever what the copy holds changes; 2: the renamed rows; 3: the
renamed symbols in its metadata."""
_COLUMN_BATCH = 500_000


def _columns_file(path: Path) -> Path | None:
    if path.resolve() != PANEL_PATH.resolve():
        return None
    return COLUMNS_DIR / f"{path.stem}.columns.parquet"


def _source_stamp(path: Path) -> dict[bytes, bytes]:
    info = path.stat()
    return {
        b"eulerlab_version": COLUMNS_VERSION.encode(),
        b"source_size": str(info.st_size).encode(),
        b"source_mtime_ns": str(info.st_mtime_ns).encode(),
    }


def _write_columns(path: Path, rows: Sequence[PanelRow], renamed: frozenset[str]) -> None:
    """Write the copy, or nothing. A copy that could differ from the JSONL is
    worse than none: any value not already a float (an int `5` would come
    back as `5.0` and print differently) or a set spread means no copy."""
    target = _columns_file(path)
    if target is None or not rows:
        return
    import pyarrow as pa
    import pyarrow.parquet as pq

    numeric = ("close", "volume", "turnover", "open", "high", "low")
    columns = {name: [getattr(r, name) for r in rows] for name in numeric}
    if any(set(map(type, values)) != {float} for values in columns.values()):
        return
    if any(r.spread != 0.0 for r in rows):
        return
    table = pa.table(
        {
            "day": pa.array([r.day for r in rows], pa.date32()),
            "symbol": pa.array([r.symbol for r in rows]).dictionary_encode(),
            "isin": pa.array([r.isin for r in rows]).dictionary_encode(),
            **{name: pa.array(values, pa.float64()) for name, values in columns.items()},
        }
    ).replace_schema_metadata(
        {**_source_stamp(path), b"renamed_symbols": json.dumps(sorted(renamed)).encode()}
    )
    with contextlib.suppress(OSError):
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(f"{target.name}.{os.getpid()}.part")
        pq.write_table(table, part, compression="zstd", row_group_size=_COLUMN_BATCH)
        part.replace(target)


def _read_columns(path: Path) -> list[PanelRow] | None:
    """The rows from the copy, or None when there is no copy for this file."""
    target = _columns_file(path)
    if target is None or not target.exists():
        return None
    import pyarrow as pa
    import pyarrow.parquet as pq

    try:
        source = pq.ParquetFile(target)
        metadata = source.schema_arrow.metadata or {}
        if not all(metadata.get(k) == v for k, v in _source_stamp(path).items()):
            return None
        epoch = date(1970, 1, 1)
        days: dict[int, date] = {}
        shared: dict[str, str] = {}
        out: list[PanelRow] = []
        append, new_row = out.append, object.__new__
        put = list(_SETTERS.values())
        with _collector_paused():
            for batch in source.iter_batches(batch_size=_COLUMN_BATCH):
                cols: dict[str, Any] = dict(zip(batch.schema.names, batch.columns, strict=True))
                day_numbers = cols["day"].cast(pa.int32()).to_numpy().tolist()
                day_list = [
                    days.get(n) or days.setdefault(n, epoch + timedelta(days=n))
                    for n in day_numbers
                ]

                def coded(name: str, cols: dict[str, Any] = cols) -> list[str]:
                    column = cols[name]
                    names = [shared.setdefault(n, n) for n in column.dictionary.to_pylist()]
                    return [names[k] for k in column.indices.to_numpy().tolist()]

                def floats(name: str, cols: dict[str, Any] = cols) -> list[float]:
                    values: list[float] = cols[name].to_numpy().tolist()
                    return values

                for values in zip(
                    day_list,
                    coded("symbol"),
                    floats("close"),
                    floats("volume"),
                    floats("turnover"),
                    coded("isin"),
                    floats("open"),
                    floats("high"),
                    floats("low"),
                    strict=True,
                ):
                    built = new_row(PanelRow)
                    put[0](built, values[0])
                    put[1](built, values[1])
                    put[2](built, values[2])
                    put[3](built, values[3])
                    put[4](built, values[4])
                    put[5](built, values[5])
                    put[6](built, 0.0)
                    put[7](built, values[6])
                    put[8](built, values[7])
                    put[9](built, values[8])
                    append(built)
    except (OSError, ValueError, KeyError, pa.ArrowException):
        return None
    return out


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

    # Capped here: the older names' rows came uncapped, so a renamed stock
    # returned its whole history where every other returned `days` (2026-10-27).
    return [by_day[day][1] for day in sorted(by_day)][-days:]


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
    """Trade dates already in the panel cache (same file format as the close cache)."""
    return cached_dates(path)


def day_turnover(path: Path = PANEL_PATH) -> dict[date, float]:
    """Each day's total traded value across the panel (for `master/sessions`)."""
    totals: dict[date, float] = {}
    if not path.exists():
        return totals
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                day = date.fromisoformat(row["d"])
                totals[day] = totals.get(day, 0.0) + float(row.get("t") or 0.0)
    return totals


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
    # The data quality contract (ADR-086): a held file is left out, and a file
    # whose bytes no longer match the SHA-256 the manifest recorded at landing
    # is held and left out. Raw data is never edited, so leaving it out is the
    # only fix there is; the operator sees why on `make data-quality`.
    from eulerlab.quality import quarantine

    held = {p for (dataset, p) in quarantine.held() if dataset == PANEL_SOURCE}
    left_out = [d for d, p in wanted if p in held]
    wanted = [(d, p) for d, p in wanted if p not in held]
    shas = _cash_shas(manifest)
    if not wanted:
        return 0, (f"{len(left_out)} quarantined day(s) left out" if left_out else "")

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
    paths = dict(wanted)
    written = 0
    note = ""

    with path.open("a", encoding="utf-8") as handle:
        try:
            with cf.ThreadPoolExecutor(max_workers=max_workers) as pool:
                for trade_date, payload in pool.map(fetch, wanted):
                    day = date.fromisoformat(trade_date)
                    key = paths[trade_date]
                    expected = shas.get(key, "")
                    if expected and hashlib.sha256(payload).hexdigest() != expected:
                        quarantine.hold(
                            PANEL_SOURCE,
                            key,
                            "bytes do not match the SHA-256 recorded when the file landed",
                            by="panel build",
                        )
                        left_out.append(trade_date)
                        continue
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
    if left_out:
        extra = f"{len(left_out)} quarantined day(s) left out: {', '.join(sorted(left_out)[:5])}"
        note = f"{note}; {extra}" if note else extra
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
