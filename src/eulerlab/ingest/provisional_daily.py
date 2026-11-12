"""Daily bars built from Kite minute bars, for a session whose bhavcopy is not out yet.

The operator's rule (2026-10-26): from 15:31 IST the Indian data should update
by itself, show a day as missing while it is missing, and use minute data in
place of the daily file until that file arrives (ADR-079).

NSE's bhavcopy is the official daily record and comes out some time in the
evening. Kite's minute bars for the ~450 largest stocks are complete within
minutes of the close. So, for the latest session only:

- **Bhavcopy not in, minute bars in** → one provisional daily bar per symbol
  (open of the first minute, high and low over the session, close of the last
  minute, summed volume), appended here with `source="kite_minute"`.
- **Bhavcopy in** → a `superseded_by="bhavcopy"` line is appended. Nothing is
  deleted: the provisional values stay on record and `read(as_of)` still
  returns them for any `as_of` before the bhavcopy landed.

**These bars never enter the price panel.** The panel, the backtests and the
paper books read only the bhavcopy. A minute-built close is not NSE's closing
price (that is a 15:00-15:30 weighted average), and the bars cover ~450 of
~2,300 stocks, so a book trading on them would see most of its universe vanish
for a day. They exist to be looked at: the company page and the Data coverage
table.

**A symbol counts only when its session is complete** — its last minute bar is
15:29, or 15:14 for an F&O stock from 2026-08-03, when continuous trading in
those ends at 15:15 for the closing auction (A-053, HISTORY #29). A partial day
would print a close from the middle of the afternoon. For an F&O stock the
official close is the auction price, which no minute bar shows.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from eulerlab.paths import data_path

PROVISIONAL_PATH = data_path("derived/provisional_daily.jsonl")
MINUTE_ROOT = data_path("landing/kite_minute")
NSE_MANIFEST = data_path("landing/nse/manifest.jsonl")
PANEL_PATH = data_path("derived/price_panel.jsonl")

SESSION_OPEN = "09:15"
SESSION_LAST_MINUTE = "15:29"
"""The NSE cash session's final one-minute candle (15:29-15:30)."""

AUCTION_LAST_MINUTE = "15:14"
AUCTION_FROM = date(2026, 8, 3)
"""F&O stocks stop continuous trading at 15:15 for the closing auction session.
On 2026-10-26 all 210 Kite symbols ending at 15:14 were F&O stocks and none of
the 203 ending at 15:29 were (HISTORY #29)."""


def session_ends(day: date) -> tuple[str, ...]:
    """The last one-minute candle of a complete session on `day`."""
    # ASSUMPTION: A-053 — the closing auction for F&O stocks starts 2026-08-03.
    if day >= AUCTION_FROM:
        return (AUCTION_LAST_MINUTE, SESSION_LAST_MINUTE)
    return (SESSION_LAST_MINUTE,)


SOURCE = "kite_minute"


@dataclass(frozen=True)
class Bar:
    """One provisional daily bar."""

    d: str
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    minutes: int
    isin: str = ""
    """The panel's internal instrument key for the symbol, when the panel has one."""


def _ranges(name: str) -> tuple[date, date] | None:
    """`2026-10-20_2026-10-26.parquet` → its two dates."""
    try:
        first, last = name.removesuffix(".parquet").split("_")
        return date.fromisoformat(first), date.fromisoformat(last)
    except ValueError:
        return None


def session_bar(symbol: str, day: date, rows: list[dict[str, Any]]) -> Bar | None:
    """One day's bar from that day's minute candles, or None if the day is incomplete."""
    stamp = day.isoformat()
    mine = sorted(
        (
            r
            for r in rows
            if str(r["ts"]).startswith(stamp)
            and SESSION_OPEN <= str(r["ts"])[11:16] <= SESSION_LAST_MINUTE
        ),
        key=lambda r: str(r["ts"]),
    )
    if not mine or str(mine[-1]["ts"])[11:16] not in session_ends(day):
        return None
    return Bar(
        d=stamp,
        symbol=symbol,
        open=float(mine[0]["open"]),
        high=max(float(r["high"]) for r in mine),
        low=min(float(r["low"]) for r in mine),
        close=float(mine[-1]["close"]),
        volume=float(sum(float(r["volume"]) for r in mine)),
        minutes=len(mine),
    )


@dataclass(frozen=True)
class DayBars:
    bars: list[Bar]
    incomplete: list[str]
    """Symbols with some minute bars that day, but not to the session's end."""


def bars_for(day: date, root: Path = MINUTE_ROOT) -> DayBars:
    """Every symbol's complete session bar on `day` from the landed minute files."""
    bars: list[Bar] = []
    incomplete: list[str] = []
    if not root.exists():
        return DayBars(bars, incomplete)
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        rows: list[dict[str, Any]] = []
        for path in sorted(folder.glob("*.parquet")):
            span = _ranges(path.name)
            if span is None or not span[0] <= day <= span[1]:
                continue
            rows.extend(pq.read_table(path).to_pylist())
        if not rows:
            continue
        bar = session_bar(folder.name, day, rows)
        if bar is not None:
            bars.append(bar)
        elif any(str(r["ts"]).startswith(day.isoformat()) for r in rows):
            incomplete.append(folder.name)
    return DayBars(bars, incomplete)


def bhavcopy_days(manifest: Path = NSE_MANIFEST) -> set[str]:
    """Cash bhavcopy days landed, from the NSE manifest."""
    out: set[str] = set()
    if not manifest.exists():
        return out
    with manifest.open(encoding="utf-8") as handle:
        for line in handle:
            if '"cm"' not in line:
                continue
            row = json.loads(line)
            if row.get("segment") == "cm" and row.get("trade_date"):
                out.add(str(row["trade_date"]))
    return out


def panel_isins(path: Path = PANEL_PATH, tail: int = 2 << 20) -> dict[str, str]:
    """Symbol → internal key from the panel's last ~2 MB (its latest days)."""
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - tail))
        lines = handle.read().decode("utf-8", "replace").splitlines()[1:]
    out: dict[str, str] = {}
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("s") and row.get("isin"):
            out[str(row["s"])] = str(row["isin"])
    return out


def _lines(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def read(path: Path = PROVISIONAL_PATH, *, as_of: str | None = None) -> dict[str, dict[str, Any]]:
    """Provisional bars still standing at `as_of`, keyed `day/symbol`.

    Bitemporal: a line counts only once its `knowledge_time` is at or before
    `as_of` (default: now). A day's latest version wins; a day superseded by
    the bhavcopy at or before `as_of` returns nothing.
    """
    cutoff = as_of or datetime.now(UTC).isoformat()
    latest: dict[str, tuple[str, dict[str, dict[str, Any]]]] = {}
    superseded: set[str] = set()
    for row in _lines(path):
        known = str(row.get("knowledge_time", ""))
        if known > cutoff:
            continue
        day = str(row.get("d", ""))
        if row.get("superseded_by"):
            superseded.add(day)
            continue
        held = latest.get(day)
        if held is None or known > held[0]:
            latest[day] = (known, {})
            held = latest[day]
        if known == held[0]:
            held[1][str(row["symbol"])] = row
    return {
        f"{day}/{symbol}": row
        for day, (_, rows) in latest.items()
        if day not in superseded
        for symbol, row in rows.items()
    }


@lru_cache(maxsize=4)
def _standing(path: str, stamp: tuple[int, int]) -> dict[str, dict[str, Any]]:
    """`read(path)` as of now, kept until the file changes (it only grows)."""
    return read(Path(path))


def standing(path: Path = PROVISIONAL_PATH) -> dict[str, dict[str, Any]]:
    """The bars standing now. Every line's knowledge_time is in the past, so the
    answer moves only when a line is appended."""
    try:
        info = path.stat()
    except FileNotFoundError:
        return {}
    return _standing(str(path), (info.st_mtime_ns, info.st_size))


def standing_days(path: Path = PROVISIONAL_PATH) -> dict[str, int]:
    """Days with provisional bars still standing now, and how many symbols each."""
    out: dict[str, int] = {}
    for key in standing(path):
        day = key.split("/", 1)[0]
        out[day] = out.get(day, 0) + 1
    return out


def bar_after(symbol: str, after: str, path: Path = PROVISIONAL_PATH) -> dict[str, Any] | None:
    """The newest standing provisional bar for `symbol` dated after `after`."""
    found = [
        row
        for key, row in standing(path).items()
        if key.endswith(f"/{symbol}") and str(row["d"]) > after
    ]
    return max(found, key=lambda r: str(r["d"])) if found else None


@dataclass(frozen=True)
class Outcome:
    day: str
    state: str
    """official · provisional · missing"""
    symbols: int = 0
    incomplete: int = 0

    def render(self) -> str:
        if self.state == "official":
            return f"{self.day}: bhavcopy in; provisional bars retired"
        if self.state == "provisional":
            extra = f", {self.incomplete} not complete" if self.incomplete else ""
            return f"{self.day}: bhavcopy missing; {self.symbols} provisional bars from minute data{extra}"
        return f"{self.day}: bhavcopy missing and no complete minute bars"


def record(
    day: date,
    *,
    path: Path = PROVISIONAL_PATH,
    root: Path = MINUTE_ROOT,
    manifest: Path = NSE_MANIFEST,
    now: datetime | None = None,
) -> Outcome:
    """Bring `day`'s provisional bars in line with what has landed. Idempotent.

    Appends only when something changed: a new or larger set of complete
    symbols, or the bhavcopy arriving for a day that had provisional bars.
    """
    stamp = day.isoformat()
    known = (now or datetime.now(UTC)).isoformat()
    standing = {k.split("/", 1)[1] for k in read(path, as_of=known) if k.startswith(f"{stamp}/")}

    if stamp in bhavcopy_days(manifest):
        if standing:
            _append(path, [{"d": stamp, "superseded_by": "bhavcopy", "knowledge_time": known}])
        return Outcome(stamp, "official")

    found = bars_for(day, root)
    if not found.bars:
        return Outcome(stamp, "missing", incomplete=len(found.incomplete))
    if {b.symbol for b in found.bars} != standing:
        isins = panel_isins()
        _append(
            path,
            [
                {
                    **asdict(bar),
                    "isin": isins.get(bar.symbol, ""),
                    "source": SOURCE,
                    "event_time": f"{stamp}T15:30:00+05:30",
                    "knowledge_time": known,
                }
                for bar in found.bars
            ],
        )
    return Outcome(stamp, "provisional", len(found.bars), len(found.incomplete))


def _append(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def latest_session(now: datetime | None = None) -> date:
    """The session the coverage table expects by now (15:31 IST cut-off)."""
    from eulerlab.ingest.coverage import expected_nse, nse_closures, nse_weekend_sessions

    return expected_nse(now or datetime.now(UTC), nse_closures(), nse_weekend_sessions())


def main() -> int:
    """`python -m eulerlab.ingest.provisional_daily`: one check, printed."""
    print(record(latest_session()).render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
