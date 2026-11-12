"""A derived US price panel, built from the landed Alpaca bars.

### Why a derived file rather than reading the landing zone

The bars live as one gzipped file per symbol per month — 36,446 of them — and
`prune-local` has moved every one to B2. Reading them per request would be
thousands of network round trips to render one screen, which is the mistake
this platform has already made twice: once when `capabilities()` listed the
bucket to build a description string, and once when the snapshot fetched news
at render time and hung for 576 seconds.

So the landing zone is read **once**, by an ingest, into a compact local file —
exactly the shape `price_panel.jsonl` takes for India. The read path opens one
file.

### Scoped by window, deliberately

`build(years=2)` is the default rather than the full decade. The snapshot needs
breadth, a map and movers, all of which come from the last two sessions; two
years is enough for a 252-day return and leaves the file small enough to load
in a second. The decade is still in B2 for anything that wants it.
"""

from __future__ import annotations

import gc
import gzip
import json
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, fields
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from eulerlab.paths import data_path

PANEL_PATH = data_path("derived/us_panel.jsonl")


@dataclass(frozen=True, slots=True)
class UsRow:
    """One symbol on one day."""

    day: date
    symbol: str
    close: float
    volume: float
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0

    @property
    def turnover(self) -> float:
        """Close x volume. Alpaca publishes no notional, so this is derived the
        same way the crypto panel derives it — one definition across asset
        classes rather than two that nearly agree."""
        return self.close * self.volume


def _months_wanted(years: float) -> set[str]:
    """Which monthly files can hold anything in the window."""
    now = datetime.now(UTC).date()
    first = now - timedelta(days=int(365 * years) + 5)
    out: set[str] = set()
    cursor = date(first.year, first.month, 1)
    while cursor <= now:
        out.add(cursor.strftime("%Y-%m"))
        cursor = date(cursor.year + (cursor.month == 12), (cursor.month % 12) + 1, 1)
    return out


def _recent_months(today: date | None = None) -> set[str]:
    """The current and previous month: the only files a daily ingest changes."""
    today = today or datetime.now(UTC).date()
    previous = today.replace(day=1) - timedelta(days=1)
    return {today.strftime("%Y-%m"), previous.strftime("%Y-%m")}


def build(*, years: float = 2.0, path: Path = PANEL_PATH, full: bool = False) -> tuple[int, int]:
    """Read the landed bars into one file. Returns (rows, symbols).

    By default only the current and previous months are re-read; every older
    row is kept from the existing file. A full rebuild re-read 24 months of
    ~500 symbols, about 12,000 files, most of them pruned to B2 — on every
    `make daily`, against a 2,500-download daily cap (T-4032). `full=True`, or
    no existing file, reads the whole window as before.

    Rewritten through a temporary file and an atomic rename, under the
    `us_panel` lock, so a reader never sees half a file and two builders never
    interleave.
    """
    from eulerlab.ingest.filelock import exclusive

    with exclusive("us_panel", directory=path.parent / ".locks"):
        return _build(years=years, path=path, full=full)


def _build(*, years: float, path: Path, full: bool) -> tuple[int, int]:
    from eulerlab.ingest import landing_reader

    wanted = _months_wanted(years)
    reread = wanted if full or not path.exists() else wanted & _recent_months()
    listed = landing_reader.available("us", "bars/*/*.jsonl.gz")
    relevant = [r for r in listed if r.rsplit("/", 1)[-1][:7] in reread]

    rows: list[UsRow] = [
        r
        for r in (read(path) if reread != wanted else [])
        if r.day.strftime("%Y-%m") in wanted - reread
    ]
    symbols: set[str] = {r.symbol for r in rows}
    missed: list[str] = []
    for relative in sorted(relevant):
        try:
            payload = gzip.decompress(landing_reader.read(relative))
        except Exception:
            # Broad on purpose. The narrow version caught OSError, ValueError
            # and FileNotFoundError, and botocore raises
            # `EndpointConnectionError`, which is none of them — so a single
            # transient network blip killed an hour-long build at symbol 280 of
            # 502 and lost every file it had already fetched.
            #
            # A month that cannot be read is absent from the panel, which shows
            # up in the row count. One unreadable file must not cost the other
            # twelve thousand.
            missed.append(relative)
            continue
        for line in payload.decode("utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                when = date.fromisoformat(str(row["event_time"])[:10])
                close = float(row["close"])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
            if close <= 0:
                continue
            symbol = str(row.get("symbol", ""))
            symbols.add(symbol)
            rows.append(
                UsRow(
                    day=when,
                    symbol=symbol,
                    close=close,
                    volume=float(row.get("volume", 0.0)),
                    open=float(row.get("open", 0.0)),
                    high=float(row.get("high", 0.0)),
                    low=float(row.get("low", 0.0)),
                )
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".partial")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in sorted(rows, key=lambda r: (r.day, r.symbol)):
            handle.write(
                json.dumps(
                    {
                        "d": row.day.isoformat(),
                        "s": row.symbol,
                        "c": round(row.close, 4),
                        "v": row.volume,
                        "o": round(row.open, 4),
                        "h": round(row.high, 4),
                        "l": round(row.low, 4),
                    }
                )
                + "\n"
            )
    tmp.replace(path)
    if missed:
        # Reported, not swallowed. A build that skipped four hundred files is
        # a different thing from one that skipped none, and the row count
        # alone does not distinguish them.
        print(f"  {len(missed)} file(s) unreadable, e.g. {missed[:2]}")
    return len(rows), len(symbols)


_SETTERS: tuple[Callable[[UsRow, object], None], ...] = tuple(
    getattr(UsRow, f.name).__set__ for f in fields(UsRow)
)
"""Each slot's own setter, in field order. A frozen dataclass's `__init__`
goes through `object.__setattr__` once per field, which was most of the read."""


def read(path: Path = PANEL_PATH) -> list[UsRow]:
    """Every row in the derived panel. One file, one pass.

    Parsed with orjson, with one shared date and one shared string per
    distinct day and symbol, and rows filled through their slot setters with
    the collector paused: 259,000 rows 1.2 s -> about 0.5 s (2026-10-27).
    """
    if not path.exists():
        return []
    with path.open("rb") as handle:
        return _parse(handle)


TAIL_BLOCK = 1 << 18
"""Bytes read per step from the end of the file. One session is about 50 KB."""


def last_sessions(count: int = 2, path: Path = PANEL_PATH) -> list[UsRow]:
    """The rows of the last `count` sessions, read from the end of the file.

    `build` writes rows sorted by (day, symbol), so the newest sessions are
    the file's last lines. The snapshot needs only two of 519 sessions and
    read all 259,000 rows for them. The end is read in blocks until it holds
    more than `count` days, so the earliest day kept is complete; a day cut
    off by the block edge is the one dropped.
    """
    if count <= 0 or not path.exists():
        return []
    size = path.stat().st_size
    with path.open("rb") as handle:
        offset = size
        rows: list[UsRow] = []
        while True:
            offset = max(0, offset - TAIL_BLOCK * max(1, count))
            handle.seek(offset)
            data = handle.read(size - offset)
            if offset > 0:
                data = data[data.find(b"\n") + 1 :]
            rows = _parse(data.splitlines())
            days = sorted({row.day for row in rows})
            if offset == 0 or len(days) > count:
                break
    kept = set(days[-count:])
    return [row for row in rows if row.day in kept]


def _parse(lines: Iterable[bytes]) -> list[UsRow]:
    """Rows from JSON lines; unreadable lines are skipped."""
    import orjson

    out: list[UsRow] = []
    days: dict[str, date] = {}
    names: dict[str, str] = {}
    append, new_row = out.append, object.__new__
    set_day, set_symbol, set_close, set_volume, set_open, set_high, set_low = _SETTERS
    collecting = gc.isenabled()
    gc.disable()
    try:
        for line in lines:
            if not line.strip():
                continue
            try:
                row = orjson.loads(line)
                stamp = row["d"]
                day = days.get(stamp)
                if day is None:
                    day = days[stamp] = date.fromisoformat(stamp)
                raw = str(row["s"])
                symbol = names.get(raw)
                if symbol is None:
                    symbol = names[raw] = sys.intern(raw)
                close = float(row["c"])
                volume = float(row.get("v", 0.0))
                opened = float(row.get("o", 0.0))
                high = float(row.get("h", 0.0))
                low = float(row.get("l", 0.0))
            except (orjson.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
            item = new_row(UsRow)
            set_day(item, day)
            set_symbol(item, symbol)
            set_close(item, close)
            set_volume(item, volume)
            set_open(item, opened)
            set_high(item, high)
            set_low(item, low)
            append(item)
    finally:
        if collecting:
            gc.enable()
    return out


def sectors(*, root: Path | None = None) -> dict[str, str]:
    """Symbol → GICS sector, from the landed constituent snapshot.

    Used for grouping the map only. The snapshot is today's membership, so a
    symbol that left the index has no sector here and groups under the
    unclassified heading rather than being dropped — a missing label is a gap
    in the data, not a reason to hide the company.
    """
    root = root if root is not None else data_path("landing/us")
    from eulerlab.ingest import landing_reader

    files = sorted((root / "sp500").glob("????-??-??.jsonl.gz"))
    payloads: list[bytes] = []
    if files:
        payloads.append(files[-1].read_bytes())
    else:
        remote = sorted(landing_reader.available("us", "sp500/*.jsonl.gz"))
        if remote:
            try:
                payloads.append(landing_reader.read(remote[-1]))
            except (OSError, ValueError):
                return {}

    out: dict[str, str] = {}
    for payload in payloads:
        for line in gzip.decompress(payload).decode("utf-8").splitlines():
            if line.strip():
                try:
                    row = json.loads(line)
                    out[str(row["symbol"])] = str(row.get("sector", ""))
                except (json.JSONDecodeError, KeyError):
                    continue
    return out


def _main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="build-us-panel")
    parser.add_argument("--full", action="store_true", help="re-read the whole window")
    args = parser.parse_args(argv)
    rows, symbols = build(full=args.full)
    print(f"us panel: {rows:,} rows across {symbols} symbols -> {PANEL_PATH}")


if __name__ == "__main__":
    _main()
