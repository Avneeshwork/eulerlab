"""What a trader reads before the open: indices, breadth, sectors, positioning.

Research 120 lists what StockEdge, Finviz and Sensibull put on their first
screen. Every figure here comes from data EulerLab already lands:

- the NSE index file (`index_history.jsonl`): levels, valuation, VIX;
- the price panel: breadth, new highs and lows;
- NSE's participant-wise open interest file: who is long index futures;
- the delivery file: stocks bought for delivery well above their habit.

None of these is a signal. Each is context, and each carries its definition.
Sensibull says of its own PCR, max pain and IV percentile that they "do not
have high predictive power" (research 120 [3]); nothing here has passed the
gate either.

All functions are pure over their inputs except the small loaders, which read
through `FileMemo` or keep a parsed cache, so a dashboard refresh re-reads
nothing that has not changed.
"""

from __future__ import annotations

import bisect
import csv
import io
import json
import threading
import warnings
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np
import numpy.typing as npt

from eulerlab.features.panel import PanelRow
from eulerlab.filecache import FileMemo, stamp

INDEX_HISTORY = Path("data/derived/index_history.jsonl")
DELIVERY = Path("data/derived/delivery.jsonl")
POSITIONS_CACHE = Path("data/cache/participant_positions.jsonl")

STRIP = (
    "Nifty 50",
    "Nifty Bank",
    "Nifty 500",
    "Nifty Midcap 150",
    "Nifty Smallcap 250",
    "India VIX",
    "Nifty 10 yr Benchmark G-Sec",
)
"""The top line. The G-Sec entry is NSE's price index of the 10-year benchmark
bond, not its yield: it rises when yields fall."""

VALUED = ("Nifty 50", "Nifty 500", "Nifty Midcap 150", "Nifty Smallcap 250")

SECTORS = (
    "Nifty Auto",
    "Nifty Bank",
    "Nifty Capital Markets",
    "Nifty Chemicals",
    "Nifty Consumer Durables",
    "Nifty CPSE",
    "Nifty Energy",
    "Nifty Financial Services",
    "Nifty FMCG",
    "Nifty Healthcare Index",
    "Nifty India Defence",
    "Nifty Infrastructure",
    "Nifty IT",
    "Nifty Media",
    "Nifty Metal",
    "Nifty Oil & Gas",
    "Nifty Pharma",
    "Nifty Private Bank",
    "Nifty PSU Bank",
    "Nifty Realty",
)
BENCHMARK = "Nifty 50"
WANTED = frozenset({*STRIP, *VALUED, *SECTORS})

HORIZONS = {"1d": 1, "1w": 5, "1m": 21, "3m": 63, "1y": 252}
"""Trading sessions per label."""

FUND_ISIN = "INF"
"""ISIN prefix of mutual fund units, ETFs included."""

# ASSUMPTION: A-062. NSE index PE has been on consolidated earnings since this date.
PE_CONSOLIDATED_FROM = date(2021, 4, 1)
"""NSE moved index PE to consolidated earnings from April 2021, and Nifty 50's
PE fell from about 40 to 33 overnight (research 120 [13], [14]). PE is ranked
only against readings from this date; PB and yield use the whole history."""

LIQUID_TURNOVER = 10e7
"""₹10 crore median daily turnover over 20 sessions: the floor for a name to
appear in a list. Below it, a new high is often one thin print."""


# --- index history ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IndexDay:
    day: date
    close: float
    pe: float | None
    pb: float | None
    dy: float | None


def _parse_indices(path: Path) -> dict[str, list[IndexDay]]:
    """The wanted indices' daily rows, oldest first. The other 120 are skipped."""
    import orjson

    out: dict[str, list[IndexDay]] = {name: [] for name in WANTED}
    if not path.exists():
        return out
    with path.open("rb") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                record = orjson.loads(line)
                day = date.fromisoformat(record["d"])
                indices = record["indices"]
            except (orjson.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
            for name in WANTED:
                cell = indices.get(name)
                if not cell or cell.get("c") is None:
                    continue
                out[name].append(
                    IndexDay(
                        day, float(cell["c"]), _num(cell, "pe"), _num(cell, "pb"), _num(cell, "dy")
                    )
                )
    for series in out.values():
        series.sort(key=lambda row: row.day)
    return out


def _num(cell: Mapping[str, Any], key: str) -> float | None:
    value = cell.get(key)
    return float(value) if isinstance(value, int | float) else None


_INDICES = FileMemo(_parse_indices, size=2)


def indices(path: Path = INDEX_HISTORY) -> dict[str, list[IndexDay]]:
    """Read once per change of the file (52 MB, rewritten each evening)."""
    return _INDICES(path)


def _change(series: Sequence[IndexDay], sessions: int) -> float | None:
    if len(series) <= sessions or series[-1 - sessions].close <= 0:
        return None
    return series[-1].close / series[-1 - sessions].close - 1.0


def percentile_of(value: float, history: Iterable[float]) -> float | None:
    """Share of `history` strictly below `value`, 0-100. None for no history."""
    values = sorted(history)
    if not values:
        return None
    return 100.0 * bisect.bisect_left(values, value) / len(values)


def index_strip(series: Mapping[str, Sequence[IndexDay]]) -> dict[str, Any]:
    """Each strip index's level and its moves over a day to a year."""
    rows = []
    for name in STRIP:
        held = series.get(name, ())
        if not held:
            continue
        rows.append(
            {
                "name": name,
                "as_of": held[-1].day.isoformat(),
                "close": round(held[-1].close, 2),
                "change": {label: _rounded(_change(held, n)) for label, n in HORIZONS.items()},
            }
        )
    vix = series.get("India VIX", ())
    year = [row.close for row in vix[-252:]]
    return {
        "available": bool(rows),
        "indices": rows,
        "vix": (
            {
                "level": round(vix[-1].close, 2),
                "percentile_1y": _rounded(percentile_of(vix[-1].close, year[:-1]), 1),
                "median_1y": round(median(year), 2),
                "note": "India VIX is NSE's 30-day implied volatility of Nifty options. "
                "The percentile ranks today's level against the previous year's closes.",
            }
            if vix
            else None
        ),
        "gsec_note": "The 10-year G-Sec line is NSE's price index of the benchmark bond, "
        "not its yield: it rises when yields fall.",
    }


def valuation(series: Mapping[str, Sequence[IndexDay]]) -> dict[str, Any]:
    """Each broad index's PE, PB and dividend yield against its own history."""
    out: list[dict[str, Any]] = []
    for name in VALUED:
        held = series.get(name, ())
        if not held:
            continue
        latest = held[-1]
        row: dict[str, Any] = {
            "name": name,
            "as_of": latest.day.isoformat(),
            "since": held[0].day.isoformat(),
        }
        for field in ("pe", "pb", "dy"):
            value = getattr(latest, field)
            start = PE_CONSOLIDATED_FROM if field == "pe" else held[0].day
            past = [v for r in held[:-1] if r.day >= start and (v := getattr(r, field)) is not None]
            row[field] = (
                {
                    "value": round(value, 2),
                    "percentile": _rounded(percentile_of(value, past), 1),
                    "median": round(median(past), 2) if past else None,
                    "since": start.isoformat(),
                }
                if value is not None
                else None
            )
        out.append(row)
    return {
        "available": bool(out),
        "indices": out,
        "note": "NSE's published PE, PB and dividend yield. The percentile is the share of "
        "trading days since the date shown with a lower value. PE is ranked only from April "
        "2021, when NSE moved it to consolidated earnings and Nifty 50's PE fell from about "
        "40 to 33 overnight; earlier readings are not like for like.",
    }


def _relative(
    held: Sequence[IndexDay], market: Mapping[date, float], n: int, *, end: int = 0
) -> float | None:
    """(1 + sector) / (1 + market) - 1 over `n` sessions ending `end` sessions ago."""
    if len(held) <= n + end:
        return None
    now, then = held[-1 - end], held[-1 - end - n]
    return (now.close / then.close) / (market[now.day] / market[then.day]) - 1.0


def sector_strength(series: Mapping[str, Sequence[IndexDay]]) -> dict[str, Any]:
    """Sector indices against Nifty 50 over 1 week, 1 month and 3 months.

    Relative return over N sessions: (1 + sector) / (1 + Nifty 50) - 1.
    Direction: the 1-month relative return now against its value 5 sessions
    ago. Phase: 3-month relative return above or below zero, crossed with that
    direction. This is our own stated rule; a Relative Rotation Graph's
    smoothing is proprietary (research 120 [11]) and is not reproduced.
    """
    bench = series.get(BENCHMARK, ())
    by_day = {row.day: row.close for row in bench}
    out: list[dict[str, Any]] = []
    for name in SECTORS:
        held = [row for row in series.get(name, ()) if row.day in by_day]
        if len(held) < 70:
            continue
        rs = {label: _relative(held, by_day, n) for label, n in (("1w", 5), ("1m", 21), ("3m", 63))}
        before = _relative(held, by_day, 21, end=5)
        # A tolerance, so a sector moving at a constant relative pace is not
        # called rising on floating-point noise.
        rising = rs["1m"] is not None and before is not None and rs["1m"] > before + 1e-9
        trend = rs["3m"]
        phase = (
            None
            if trend is None
            else ("leading" if rising else "weakening")
            if trend > 0
            else ("improving" if rising else "lagging")
        )
        out.append(
            {
                "name": name,
                "change_1d": _rounded(_change(held, 1)),
                "relative": {k: _rounded(v) for k, v in rs.items()},
                "rising": rising,
                "phase": phase,
            }
        )
    out.sort(key=lambda row: -(rs_3m if (rs_3m := row["relative"]["3m"]) is not None else -9.0))
    return {
        "available": bool(out),
        "benchmark": BENCHMARK,
        "sectors": out,
        "note": "Relative return = (1 + sector) / (1 + Nifty 50) - 1. Rising: the 1-month "
        "relative return is above where it was 5 sessions ago. Phase crosses the 3-month "
        "relative return with that direction: leading, weakening, lagging, improving.",
    }


# --- breadth ------------------------------------------------------------------


@dataclass(frozen=True)
class PriceGrid:
    """Adjusted closes and turnover, days by symbols. NaN where a symbol did not trade."""

    days: list[date]
    symbols: list[str]
    close: npt.NDArray[np.float64]
    turnover: npt.NDArray[np.float64]


def price_grid(
    rows: Sequence[PanelRow], actions: Mapping[str, Sequence[tuple[date, float]]]
) -> PriceGrid:
    """A dense grid from panel rows, split- and bonus-adjusted.

    `actions` maps an ISIN to its (ex-date, factor) events, the same factors
    `build_adjusted_index` divides by. A raw close falls by half on a 1:1
    bonus; unadjusted, every such stock would drop below its averages and
    print a false new low.

    Stocks only: a fund unit's ISIN starts with `INF`. Liquid funds and ETFs
    drift up almost daily, and they filled the new-high list.
    """
    rows = [row for row in rows if not row.isin.startswith(FUND_ISIN)]
    days = sorted({row.day for row in rows})
    day_at = {day: i for i, day in enumerate(days)}
    column: dict[str, int] = {}
    isin: dict[str, str] = {}
    for row in rows:
        if row.symbol not in column:
            column[row.symbol] = len(column)
        isin[row.symbol] = row.isin
    close = np.full((len(days), len(column)), np.nan)
    turnover = np.zeros((len(days), len(column)))
    for row in rows:
        i, j = day_at[row.day], column[row.symbol]
        close[i, j] = row.close
        turnover[i, j] = row.turnover
    if days:
        for symbol, j in column.items():
            for ex_date, factor in actions.get(isin[symbol], ()):
                if days[0] < ex_date <= days[-1] and factor > 0:
                    close[: bisect.bisect_left(days, ex_date), j] /= factor
    return PriceGrid(days, list(column), close, turnover)


def rolling_mean(values: npt.NDArray[np.float64], window: int) -> npt.NDArray[np.float64]:
    """Mean of the last `window` rows per column, ignoring gaps; NaN when fewer
    than 90% of the window has a value."""
    present = ~np.isnan(values)
    sums = np.vstack([np.zeros(values.shape[1]), np.cumsum(np.where(present, values, 0.0), axis=0)])
    counts = np.vstack([np.zeros(values.shape[1]), np.cumsum(present, axis=0)])
    out = np.full(values.shape, np.nan)
    if values.shape[0] < window:
        return out
    total = sums[window:] - sums[:-window]
    seen = counts[window:] - counts[:-window]
    out[window - 1 :] = np.where(seen >= 0.9 * window, total / np.maximum(seen, 1), np.nan)
    return out


def breadth(grid: PriceGrid, *, sessions: int = 252, year: int = 252) -> dict[str, Any]:
    """Share of stocks above their 20, 50 and 200-day averages, and new 52-week
    highs and lows, for each of the last `sessions` days.

    New high: today's close above every close of the previous `year` - 1
    sessions, with at least 90% of them present. Closes only; the panel has no
    intraday high, so this is a closing high (research 120 [7] counts the
    same way on its daily data).
    """
    close = grid.close
    n_days = close.shape[0]
    if n_days == 0:
        return {"available": False, "reason": "no rows"}
    tail = slice(max(0, n_days - sessions), n_days)
    present = ~np.isnan(close)
    series: dict[str, list[float | None]] = {}
    for window in (20, 50, 200):
        average = rolling_mean(close, window)
        valid = present & ~np.isnan(average)
        above = np.where(valid, close > np.where(valid, average, 0.0), False).sum(axis=1)
        counted = valid.sum(axis=1)
        share = np.where(counted > 0, 100.0 * above / np.maximum(counted, 1), np.nan)
        series[f"above_{window}"] = [_rounded_float(v, 1) for v in share[tail]]

    highs: list[int] = []
    lows: list[int] = []
    high_names: list[int] = []
    low_names: list[int] = []
    for i in range(tail.start, n_days):
        lo = i - (year - 1)
        if lo < 0:
            highs.append(0)
            lows.append(0)
            continue
        prior = close[lo:i]
        enough = (~np.isnan(prior)).sum(axis=0) >= 0.9 * (year - 1)
        today = close[i]
        with warnings.catch_warnings():
            # A column with no closes in the window warns; `enough` drops it.
            warnings.simplefilter("ignore", RuntimeWarning)
            top = np.nanmax(prior, axis=0)
            bottom = np.nanmin(prior, axis=0)
        new_high = enough & ~np.isnan(today) & (today > top)
        new_low = enough & ~np.isnan(today) & (today < bottom)
        highs.append(int(new_high.sum()))
        lows.append(int(new_low.sum()))
        if i == n_days - 1:
            high_names = list(np.flatnonzero(new_high))
            low_names = list(np.flatnonzero(new_low))

    record = [
        100.0 * h / (h + lo_) if h + lo_ else None for h, lo_ in zip(highs, lows, strict=True)
    ]
    hl_index = _sma(record, 10)
    liquid = median_turnover(grid.turnover, 20)

    def names(columns: list[int]) -> list[dict[str, Any]]:
        picked = [j for j in columns if liquid[j] >= LIQUID_TURNOVER]
        picked.sort(key=lambda j: -liquid[j])
        return [
            {
                "symbol": grid.symbols[j],
                "close": round(float(close[-1, j]), 2),
                "change_1d": _rounded(column_change(close, j)),
                "turnover_cr": round(float(liquid[j]) / 1e7, 1),
            }
            for j in picked[:15]
        ]

    days = [d.isoformat() for d in grid.days[tail]]
    latest = {key: values[-1] for key, values in series.items()}
    return {
        "available": True,
        "as_of": days[-1],
        "stocks": int(present[-1].sum()),
        "latest": {
            **latest,
            "new_highs": highs[-1],
            "new_lows": lows[-1],
            "record_high_percent": _rounded_float(record[-1], 1),
            "high_low_index": _rounded_float(hl_index[-1], 1),
        },
        "series": {
            "days": days,
            **series,
            "new_highs": highs,
            "new_lows": lows,
            "high_low_index": [_rounded_float(v, 1) for v in hl_index],
        },
        "new_high_names": names(high_names),
        "new_low_names": names(low_names),
        "note": "Share of NSE stocks above their 20, 50 and 200-day averages of split-adjusted "
        "closes; StockCharts reads above 70% as overbought and below 30% as oversold, with "
        "the 200-day's 50% line as the trend bias. New highs and lows are 52-week closing "
        "highs and lows. High-Low Index: 10-day average of highs / (highs + lows) x 100. "
        "Lists show names with a median daily turnover of ₹10 crore or more.",
    }


def median_turnover(turnover: npt.NDArray[np.float64], window: int) -> npt.NDArray[np.float64]:
    recent = turnover[-window:]
    return np.asarray(np.median(recent, axis=0), dtype=np.float64)


def column_change(close: npt.NDArray[np.float64], j: int) -> float | None:
    if close.shape[0] < 2:
        return None
    now, before = close[-1, j], close[-2, j]
    if np.isnan(now) or np.isnan(before) or before <= 0:
        return None
    return float(now / before - 1.0)


def _sma(values: Sequence[float | None], window: int) -> list[float | None]:
    out: list[float | None] = []
    for i in range(len(values)):
        part = [v for v in values[max(0, i - window + 1) : i + 1] if v is not None]
        out.append(sum(part) / len(part) if len(part) == min(window, i + 1) and part else None)
    return out


# --- participant positions ----------------------------------------------------


PARTICIPANTS = ("FII", "DII", "Pro", "Client")


def parse_positions(payload: bytes) -> dict[str, dict[str, int]] | None:
    """NSE's participant-wise OI file: contracts per participant and column.

    The file has a title line above the header and padded column names
    ("Future Stock Short       "), so both are cleaned. None when the file
    names none of the participants.
    """
    text = payload.decode("utf-8", errors="replace")
    lines = text.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.lstrip().startswith("Client Type")), None
    )
    if start is None:
        return None
    out: dict[str, dict[str, int]] = {}
    for row in csv.DictReader(io.StringIO("\n".join(lines[start:]))):
        name = (row.get("Client Type") or "").strip()
        if name not in PARTICIPANTS:
            continue
        cells: dict[str, int] = {}
        for key, value in row.items():
            if key is None or key.strip() == "Client Type":
                continue
            try:
                cells[key.strip()] = int(float((value or "0").strip() or 0))
            except ValueError:
                continue
        out[name] = cells
    return out or None


def positioning(days: Mapping[date, Mapping[str, Mapping[str, int]]]) -> dict[str, Any]:
    """Each participant's share of index futures held long, and how it moved.

    Long share = long / (long + short) of index futures contracts. Netting
    across futures and options would not describe direction (research 120
    [8]), so options are shown as raw net contracts beside it. A DII short
    future is often the hedge leg of an arbitrage fund, and "Client" is not
    retail alone.
    """
    ordered = sorted(days)
    if not ordered:
        return {"available": False, "reason": "no participant files read yet"}

    def share(day: date, who: str) -> float | None:
        cells = days[day].get(who, {})
        long_, short = cells.get("Future Index Long", 0), cells.get("Future Index Short", 0)
        return long_ / (long_ + short) if long_ + short else None

    latest = ordered[-1]
    rows = []
    for who in PARTICIPANTS:
        now = share(latest, who)
        history = [v for d in ordered[-250:-1] if (v := share(d, who)) is not None]
        cells = days[latest].get(who, {})
        rows.append(
            {
                "participant": who,
                "index_futures_long_share": _rounded(now),
                "change_1d": _diff(now, share(ordered[-2], who) if len(ordered) > 1 else None),
                "change_5d": _diff(now, share(ordered[-6], who) if len(ordered) > 5 else None),
                "percentile": _rounded(percentile_of(now, history), 1) if now is not None else None,
                "history_days": len(history),
                "index_calls_net": cells.get("Option Index Call Long", 0)
                - cells.get("Option Index Call Short", 0),
                "index_puts_net": cells.get("Option Index Put Long", 0)
                - cells.get("Option Index Put Short", 0),
            }
        )
    trail = ordered[-60:]
    return {
        "available": True,
        "as_of": latest.isoformat(),
        "participants": rows,
        "series": {
            "days": [d.isoformat() for d in trail],
            **{who: [_rounded(share(d, who)) for d in trail] for who in PARTICIPANTS},
        },
        "note": "Long share = index futures long / (long + short) contracts, from NSE's "
        "end-of-day participant-wise open interest. Options are net contracts (long - short). "
        "A DII short future is often an arbitrage hedge, and Client is every account that is "
        "not FII, DII or Pro, not retail alone.",
    }


class PositionHistory:
    """Parsed participant files, kept in `data/cache` so each is read once.

    The files are small but most have been moved to the bucket. The first
    request reads the local ones and starts one background thread for the rest;
    the dashboard says how many days it has until that finishes.
    """

    def __init__(self, cache: Path = POSITIONS_CACHE, *, wanted: int = 260) -> None:
        self.cache = cache
        self.wanted = wanted
        self._lock = threading.Lock()
        self._days: dict[date, dict[str, dict[str, int]]] | None = None
        self._filling = False

    def _load(self) -> dict[date, dict[str, dict[str, int]]]:
        if self._days is None:
            self._days = {}
            if self.cache.exists():
                for line in self.cache.read_text(encoding="utf-8").splitlines():
                    try:
                        record = json.loads(line)
                        self._days[date.fromisoformat(record["day"])] = record["positions"]
                    except (ValueError, KeyError, TypeError):
                        continue
        return self._days

    def _keep(self, day: date, positions: dict[str, dict[str, int]]) -> None:
        with self._lock:
            held = self._load()
            if day in held:
                return
            held[day] = positions
            self.cache.parent.mkdir(parents=True, exist_ok=True)
            with self.cache.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"day": day.isoformat(), "positions": positions}) + "\n")

    def days(
        self,
        listing: Callable[[], list[str]],
        read: Callable[[str], bytes],
        is_local: Callable[[str], bool],
        *,
        background: bool = True,
    ) -> dict[date, dict[str, dict[str, int]]]:
        """Every day held, after reading any local file not yet parsed."""
        files = {}
        for relative in listing():
            day = _file_day(relative)
            if day is not None:
                files[day] = relative
        recent = sorted(files)[-self.wanted :]
        with self._lock:
            held = set(self._load())
        missing = [d for d in recent if d not in held]
        for day in [d for d in missing if is_local(files[d])]:
            self._read_one(day, files[day], read)
        remote = [d for d in missing if not is_local(files[d])]
        if remote:
            if background:
                self._fill(remote, files, read)
            else:
                for day in remote:
                    self._read_one(day, files[day], read)
        with self._lock:
            return dict(self._load())

    def _read_one(self, day: date, relative: str, read: Callable[[str], bytes]) -> None:
        try:
            parsed = parse_positions(read(relative))
        except Exception:  # an unreadable file is skipped and tried next time
            return
        if parsed:
            self._keep(day, parsed)

    def _fill(
        self, remote: list[date], files: Mapping[date, str], read: Callable[[str], bytes]
    ) -> None:
        with self._lock:
            if self._filling:
                return
            self._filling = True

        def work() -> None:
            try:
                from concurrent.futures import ThreadPoolExecutor

                with ThreadPoolExecutor(max_workers=4, thread_name_prefix="positions") as pool:
                    list(pool.map(lambda d: self._read_one(d, files[d], read), remote))
            finally:
                with self._lock:
                    self._filling = False

        threading.Thread(target=work, daemon=True, name="positions-fill").start()

    @property
    def filling(self) -> bool:
        return self._filling


def _file_day(relative: str) -> date | None:
    name = relative.rsplit("/", 1)[-1]
    try:
        return date.fromisoformat(name[:10])
    except ValueError:
        return None


# --- delivery -----------------------------------------------------------------


def last_lines(path: Path, count: int, *, block: int = 1 << 20) -> list[bytes]:
    """The last `count` non-empty lines of a file, read from its end.

    The delivery file is 194 MB, one line per day; the dashboard needs 21.
    """
    if count <= 0 or not path.exists():
        return []
    size = path.stat().st_size
    with path.open("rb") as handle:
        offset = size
        lines: list[bytes] = []
        while True:
            offset = max(0, offset - block)
            handle.seek(offset)
            data = handle.read(size - offset)
            lines = [line for line in data.split(b"\n") if line.strip()]
            if offset > 0:
                lines = lines[1:]  # the first may be cut
            if offset == 0 or len(lines) >= count:
                return lines[-count:]
            block *= 2


def _parse_delivery(path: Path) -> list[tuple[date, dict[str, float]]]:
    """(day, symbol -> delivery %) for the last 21 sessions."""
    import orjson

    out: list[tuple[date, dict[str, float]]] = []
    for line in last_lines(path, 21):
        try:
            record = orjson.loads(line)
            stocks = record["stocks"]
            out.append(
                (
                    date.fromisoformat(record["d"]),
                    {
                        s: float(v[2])
                        for s, v in stocks.items()
                        if isinstance(v, list) and len(v) > 2
                    },
                )
            )
        except (orjson.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    return out


_DELIVERY = FileMemo(_parse_delivery, size=2)


def delivery_days(path: Path = DELIVERY) -> list[tuple[date, dict[str, float]]]:
    return _DELIVERY(path)


def delivery_watch(
    days: Sequence[tuple[date, Mapping[str, float]]],
    latest: Mapping[str, tuple[float, float | None]],
    *,
    ratio: float = 1.5,
    limit: int = 15,
) -> dict[str, Any]:
    """Stocks delivered far above their own 20-session habit today.

    `latest` maps a symbol to (median daily turnover in rupees, day change).
    Delivery % is the share of traded quantity settled by delivery rather
    than squared off intraday. A spike says more shares changed hands to be
    held; it does not say which side was buying.
    """
    if len(days) < 6:
        return {"available": False, "reason": "fewer than 6 sessions of delivery data"}
    today, now = days[-1]
    before = days[:-1]
    out: list[dict[str, Any]] = []
    for symbol, pct in now.items():
        held = latest.get(symbol)
        if held is None or held[0] < LIQUID_TURNOVER:
            continue
        past = [d[symbol] for _, d in before if symbol in d]
        if len(past) < 0.75 * len(before):
            continue
        usual = sum(past) / len(past)
        if usual <= 0 or pct < ratio * usual:
            continue
        out.append(
            {
                "symbol": symbol,
                "delivery_pct": round(pct, 1),
                "usual_pct": round(usual, 1),
                "ratio": round(pct / usual, 2),
                "change_1d": _rounded(held[1]),
                "turnover_cr": round(held[0] / 1e7, 1),
            }
        )
    out.sort(key=lambda row: -row["ratio"])
    return {
        "available": True,
        "as_of": today.isoformat(),
        "sessions": len(before),
        "stocks": out[:limit],
        "found": len(out),
        "note": f"Delivery % today at least {ratio}x its average over the previous "
        f"{len(before)} sessions, among names with a median turnover of ₹10 crore or more. "
        "Delivery says shares changed hands to be held; it does not say who bought.",
    }


# --- helpers ------------------------------------------------------------------


def _rounded(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def _rounded_float(value: float | None, digits: int) -> float | None:
    if value is None:
        return None
    number = float(value)
    return None if np.isnan(number) else round(number, digits)


def _diff(now: float | None, before: float | None) -> float | None:
    return None if now is None or before is None else round(now - before, 4)


def file_stamp(path: Path) -> tuple[int, int] | None:
    """For callers that cache a whole answer keyed by its inputs."""
    return stamp(path)
