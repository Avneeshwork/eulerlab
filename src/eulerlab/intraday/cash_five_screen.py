"""Five minute-level cash rules for NSE stocks and the Nifty, at 1x (research 155).

Pre-registered as H-0045 to H-0049 before any run. All read Kite one-minute
bars, never past 2024-11-29, and trade cash shares or NIFTYBEES only.

- **H-0045 in-play ORB.** Zarattini, Barbon and Aziz (2024): the 20 stocks
  whose 09:16-09:20 volume is highest against its own 14-session mean (above
  1) trade the breakout of that range in its direction from 09:21, with a
  1.4 x ATR(14) stop, out at 15:10.
- **H-0046 52-week-high break.** The first minute from 09:20 above the
  highest high of the previous 250 sessions, on a day that did not open above
  it: buy the next open, sell at 15:10.
- **H-0047 panic-day laggards.** Nifty 1% or more from the prior close at
  12:15: of the day's 50 most-traded stocks, buy the 10 that fell most (short
  the 10 that rose most on an up day) at 12:16, out at 15:10.
- **H-0048 panic reversal.** The same signal, NIFTYBEES against the move.
- **H-0049 NIFTYBEES premium.** Fair value is the Nifty minute price times the
  prior closes' NIFTYBEES/Nifty ratio; a premium of 16 bps or more from 09:30
  to 15:00 is traded back at the next open and closed when it changes sign.

Stock trades are ₹1 lakh, NIFTYBEES ₹10 lakh; charges are cash intraday plus
2 bps a side. `make cash-five` writes `data/derived/cash_five.json`.
"""

from __future__ import annotations

import argparse
import io
import json
import pickle
import subprocess
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from eulerlab.intraday import cross_section as cs
from eulerlab.intraday import india_papers as ip
from eulerlab.intraday import research_screen as rs
from eulerlab.intraday import screen_common as sc

OUT = Path("data/derived/cash_five.json")
PARTS = Path("data/derived/cash_five_parts")
BATCH = 40
ETF = "NIFTYBEES"
TRADE = 100_000.0
ETF_CAPITAL = 1_000_000.0
MIN_PRICE = 100.0

RANGE_FIRST, RANGE_LAST = 1, 5
"""09:16 to 09:20: the 09:15 print is not a price (research 075)."""
IN_PLAY_DAYS = 14
IN_PLAY_TOP = 20
ATR_DAYS = 14
ATR_STOP = 1.4

YEAR = 250
BREAK_FROM = 5

PANIC_MINUTE = 180
"""12:15."""
PANIC_MOVE = 0.01
PANIC_NAMES = 50
PANIC_PICK = 10

PREMIUM = 0.0016
PREMIUM_FROM = 15
"""09:30."""
PREMIUM_LAST = 345
"""15:00."""

MAX_OPEN = 10


@dataclass(frozen=True)
class Fill:
    minute: int
    direction: int
    entry_minute: int
    entry: float
    exit_minute: int
    exit: float
    reason: str = "time_exit"


@dataclass(frozen=True)
class InPlay:
    relative_volume: float
    fill: Fill | None


@dataclass(frozen=True)
class Panic:
    move: float
    turnover_before: float
    fill: Fill


def _span_high(day: ip.Day) -> float | None:
    highs = [h for h in day.high if h is not None]
    return max(highs) if highs else None


def _span_low(day: ip.Day) -> float | None:
    lows = [x for x in day.low if x is not None]
    return min(lows) if lows else None


def true_range(day: ip.Day, before: float) -> float | None:
    high, low = _span_high(day), _span_low(day)
    if high is None or low is None:
        return None
    return max(high, before) - min(low, before)


def opening_volume(day: ip.Day) -> float:
    return float(sum(day.volume[RANGE_FIRST : RANGE_LAST + 1]))


def orb(day: ip.Day, atr: float) -> Fill | None:
    """The in-play breakout and its stop, or None if the range never broke."""
    window = range(RANGE_FIRST, RANGE_LAST + 1)
    highs = [day.high[m] for m in window if day.high[m] is not None]
    lows = [day.low[m] for m in window if day.low[m] is not None]
    first = next((day.open_[m] for m in window if day.open_[m] is not None), None)
    if not highs or not lows or first is None:
        return None
    top, bottom = max(h for h in highs if h is not None), min(x for x in lows if x is not None)
    last = day.close[RANGE_LAST]
    if last == first:
        return None
    direction = 1 if last > first else -1
    entry_minute, entry = None, 0.0
    for m in range(RANGE_LAST + 1, min(day.last + 1, cs.EXIT)):
        opened, high, low = day.open_[m], day.high[m], day.low[m]
        if opened is None or high is None or low is None:
            continue
        if direction > 0 and high >= top:
            entry_minute, entry = m, max(top, opened)
            break
        if direction < 0 and low <= bottom:
            entry_minute, entry = m, min(bottom, opened)
            break
    if entry_minute is None:
        return None
    stop = entry - direction * ATR_STOP * atr
    for k in range(entry_minute + 1, min(day.last + 1, cs.EXIT)):
        opened, high, low = day.open_[k], day.high[k], day.low[k]
        if opened is None or high is None or low is None:
            continue
        if direction > 0 and low <= stop:
            return Fill(RANGE_LAST, 1, entry_minute, entry, k, min(stop, opened), "stop")
        if direction < 0 and high >= stop:
            return Fill(RANGE_LAST, -1, entry_minute, entry, k, max(stop, opened), "stop")
    leave = day.fill_at(cs.EXIT)
    if leave is None or leave[0] <= entry_minute:
        return None
    return Fill(RANGE_LAST, direction, entry_minute, entry, leave[0], leave[1])


def year_high_break(day: ip.Day, level: float) -> Fill | None:
    opened = next((o for o in day.open_ if o is not None), None)
    if opened is None or opened >= level:
        return None
    for m in range(BREAK_FROM, min(day.last, cs.EXIT)):
        high = day.high[m]
        if high is not None and high > level:
            entry = day.fill_at(m + 1)
            leave = day.fill_at(cs.EXIT)
            if entry is None or leave is None or entry[0] >= leave[0]:
                return None
            return Fill(m, 1, entry[0], entry[1], leave[0], leave[1])
    return None


def extract(_symbol: str, days: Sequence[ip.Day]) -> dict[str, dict[date, Any]]:
    """Every stock-day's in-play candidate, 52-week-high break and panic-day mark."""
    out: dict[str, dict[date, Any]] = {"in_play": {}, "high52": {}, "panic": {}}
    ranges: list[float | None] = []
    highs: list[float | None] = []
    for index, day in enumerate(days):
        before = cs.previous_close(days, index)
        ranges.append(true_range(day, before) if before is not None else None)
        highs.append(_span_high(day))
        if before is None or before < MIN_PRICE:
            continue
        if index >= IN_PLAY_DAYS:
            past = [opening_volume(d) for d in days[index - IN_PLAY_DAYS : index]]
            mean = sum(past) / IN_PLAY_DAYS
            atrs = ranges[index - ATR_DAYS : index]
            if mean > 0 and all(r is not None for r in atrs):
                atr = sum(r for r in atrs if r is not None) / ATR_DAYS
                out["in_play"][day.day] = InPlay(opening_volume(day) / mean, orb(day, atr))
        if index >= YEAR:
            year = [h for h in highs[index - YEAR : index] if h is not None]
            if len(year) == YEAR:
                found = year_high_break(day, max(year))
                if found is not None:
                    out["high52"][day.day] = found
        entry = day.fill_at(PANIC_MINUTE + 1)
        leave = day.fill_at(cs.EXIT)
        if entry is not None and leave is not None and entry[0] < leave[0]:
            prior = days[index - 1]
            turnover = sum(c * v for c, v in zip(prior.close, prior.volume, strict=True))
            out["panic"][day.day] = Panic(
                day.close[PANIC_MINUTE] / before - 1.0,
                turnover,
                Fill(PANIC_MINUTE, 0, entry[0], entry[1], leave[0], leave[1]),
            )
    return out


def index_moves(index: Sequence[ip.Day]) -> dict[date, float]:
    """The Nifty's move from the prior session's close to 12:15, by day."""
    out = {}
    for i in range(1, len(index)):
        before = index[i - 1].close[index[i - 1].last]
        out[index[i].day] = index[i].close[PANIC_MINUTE] / before - 1.0
    return out


def premium_trades(index: Sequence[ip.Day], etf: Sequence[ip.Day]) -> list[tuple[date, Fill]]:
    """H-0049: every NIFTYBEES premium trade, as (day, fill)."""
    by_day = {d.day: d for d in index}
    out: list[tuple[date, Fill]] = []
    for i in range(1, len(etf)):
        day, prior = etf[i], etf[i - 1]
        nifty, nifty_prior = by_day.get(day.day), by_day.get(prior.day)
        if nifty is None or nifty_prior is None:
            continue
        ratio = prior.close[prior.last] / nifty_prior.close[nifty_prior.last]
        position: tuple[int, int, float] | None = None
        m = PREMIUM_FROM
        while m <= min(day.last, cs.EXIT - 1):
            traded = day.open_[m] is not None and day.volume[m] > 0
            premium = day.close[m] / (nifty.close[m] * ratio) - 1.0 if traded else None
            if position is None:
                if premium is not None and m <= PREMIUM_LAST and abs(premium) >= PREMIUM:
                    entry = day.fill_at(m + 1)
                    if entry is not None and entry[0] < cs.EXIT:
                        position = (-1 if premium > 0 else 1, entry[0], entry[1])
                        m = entry[0]
                        continue
            elif premium is not None and m > position[1] and premium * position[0] >= 0:
                # The premium has changed sign: it was against the position's direction.
                leave = day.fill_at(m + 1)
                if leave is not None and leave[0] <= cs.EXIT:
                    out.append((day.day, Fill(m, position[0], position[1], position[2], *leave)))
                    position = None
                    m = leave[0]
                    continue
            m += 1
        if position is not None:
            leave = day.fill_at(cs.EXIT)
            if leave is not None and leave[0] > position[1]:
                out.append((day.day, Fill(cs.EXIT, position[0], position[1], position[2], *leave)))
    return out


# --- evaluation ----------------------------------------------------------------------


def _trade(symbol: str, day: date, fill: Fill, direction: int, notional: float) -> cs.Trade | None:
    quantity = cs.sized(notional, fill.entry)
    if not quantity:
        return None
    return cs.Trade(
        symbol,
        day,
        direction,
        quantity,
        fill.entry_minute,
        fill.entry,
        fill.exit_minute,
        fill.exit,
        fill.reason,
    )


def _halves(run: dict[str, Any]) -> dict[str, Any]:
    daily = [(date.fromisoformat(d), r) for d, r in run.pop("daily")]
    run["net_halves"] = {
        "before_2024": sc.daily_stats([r for d, r in daily if d.year < 2024]),
        "2024": sc.daily_stats([r for d, r in daily if d.year >= 2024]),
    }
    run["trade_log"] = run.get("trade_log", [])[:200]
    return run


def _params(**extra: Any) -> dict[str, Any]:
    return {"slippage_bps_per_side": cs.SLIPPAGE_BPS, **extra}


def evaluate_in_play(
    marks: Mapping[str, Mapping[date, InPlay]], sessions: Sequence[date]
) -> dict[str, Any]:
    by_day: dict[date, list[tuple[float, str, InPlay]]] = defaultdict(list)
    for symbol, days in marks.items():
        for day, found in days.items():
            if found.relative_volume > 1.0:
                by_day[day].append((found.relative_volume, symbol, found))
    trades = []
    for day, found_today in by_day.items():
        found_today.sort(key=lambda item: (-item[0], item[1]))
        for _, symbol, found in found_today[:IN_PLAY_TOP]:
            if found.fill is not None:
                trade = _trade(symbol, day, found.fill, found.fill.direction, TRADE)
                if trade:
                    trades.append(trade)
    run = cs.report(
        "nse_in_play_orb",
        trades,
        sessions,
        params=_params(selection=f"top {IN_PLAY_TOP} by relative opening volume > 1"),
        capital=TRADE * IN_PLAY_TOP,
    )
    run["stopped"] = sum(1 for t in trades if t.reason == "stop")
    return _halves(run)


def evaluate_year_high(
    marks: Mapping[str, Mapping[date, Fill]], sessions: Sequence[date]
) -> dict[str, Any]:
    by_day: dict[date, list[tuple[int, str, Fill]]] = defaultdict(list)
    for symbol, days in marks.items():
        for day, fill in days.items():
            by_day[day].append((fill.minute, symbol, fill))
    trades = []
    for day, found_today in by_day.items():
        found_today.sort(key=lambda item: (item[0], item[1]))
        for _, symbol, fill in found_today[:MAX_OPEN]:
            trade = _trade(symbol, day, fill, 1, TRADE)
            if trade:
                trades.append(trade)
    run = cs.report(
        "nse_52_week_high_break", trades, sessions, params=_params(), capital=TRADE * MAX_OPEN
    )
    return _halves(run)


def evaluate_panic_stocks(
    marks: Mapping[str, Mapping[date, Panic]], moves: Mapping[date, float], sessions: Sequence[date]
) -> dict[str, Any]:
    by_day: dict[date, list[tuple[str, Panic]]] = defaultdict(list)
    for symbol, days in marks.items():
        for day, found in days.items():
            if abs(moves.get(day, 0.0)) >= PANIC_MOVE:
                by_day[day].append((symbol, found))
    trades = []
    for day, found_today in by_day.items():
        largest = sorted(found_today, key=lambda item: (-item[1].turnover_before, item[0]))
        chosen = sorted(largest[:PANIC_NAMES], key=lambda item: (item[1].move, item[0]))
        down = moves[day] < 0
        picks = chosen[:PANIC_PICK] if down else chosen[-PANIC_PICK:]
        for symbol, found in picks:
            trade = _trade(symbol, day, found.fill, 1 if down else -1, TRADE)
            if trade:
                trades.append(trade)
    run = cs.report(
        "nse_panic_day_laggards",
        trades,
        sessions,
        params=_params(signal="Nifty |12:15 move| >= 1%"),
        capital=TRADE * PANIC_PICK,
    )
    run["signal_days"] = len(by_day)
    return _halves(run)


def evaluate_panic_index(
    moves: Mapping[date, float], etf: Sequence[ip.Day], sessions: Sequence[date]
) -> dict[str, Any]:
    trades = []
    for day in etf:
        move = moves.get(day.day)
        if move is None or abs(move) < PANIC_MOVE:
            continue
        entry, leave = day.fill_at(PANIC_MINUTE + 1), day.fill_at(cs.EXIT)
        if entry is None or leave is None or entry[0] >= leave[0]:
            continue
        fill = Fill(PANIC_MINUTE, -1 if move > 0 else 1, entry[0], entry[1], leave[0], leave[1])
        trade = _trade(ETF, day.day, fill, fill.direction, ETF_CAPITAL)
        if trade:
            trades.append(trade)
    run = cs.report(
        "nifty_panic_reversal_niftybees",
        trades,
        sessions,
        params=_params(signal="Nifty |12:15 move| >= 1%"),
        capital=ETF_CAPITAL,
    )
    return _halves(run)


def evaluate_premium(
    fills: Sequence[tuple[date, Fill]], sessions: Sequence[date]
) -> dict[str, Any]:
    trades = []
    for day, fill in fills:
        trade = _trade(ETF, day, fill, fill.direction, ETF_CAPITAL)
        if trade:
            trades.append(trade)
    run = cs.report(
        "niftybees_premium_reversion",
        trades,
        sessions,
        params=_params(threshold_bps=PREMIUM * 10_000),
        capital=ETF_CAPITAL,
    )
    return _halves(run)


# --- data ----------------------------------------------------------------------------


def load_index(cutoff: date = cs.DATA_END) -> list[ip.Day]:
    """Nifty 50 one-minute bars from `kite_index_minute`, through the cutoff."""
    import pyarrow.parquet as pq

    from eulerlab.ingest import landing_reader

    rows: dict[str, dict[int, tuple[float, float, float, float, float]]] = {}
    for name in sorted(landing_reader.available("kite_index_minute", "NIFTY50/*.parquet")):
        if rs._file_end(name) > cutoff:
            continue
        table = pq.read_table(
            io.BytesIO(landing_reader.read(name, cache=False)),
            columns=["ts", "open", "high", "low", "close"],
        )
        columns = [table.column(c).to_pylist() for c in table.column_names]
        for stamp, open_, high, low, close in zip(*columns, strict=True):
            if stamp is None or open_ is None or high is None or low is None or close is None:
                continue
            minute = (int(stamp[11:13]) - 9) * 60 + int(stamp[14:16]) - 15
            if 0 <= minute < ip.MINUTES:
                rows.setdefault(stamp[:10], {})[minute] = (
                    float(open_),
                    float(high),
                    float(low),
                    float(close),
                    0.0,
                )
    return ip.days_from_rows(rows)


def extract_batch(symbols: list[str], part: Path) -> None:
    found, sessions = cs.scan(symbols, {"marks": extract})
    part.parent.mkdir(parents=True, exist_ok=True)
    tmp = part.with_suffix(".partial")
    tmp.write_bytes(pickle.dumps({"marks": found["marks"], "sessions": sessions}))
    tmp.replace(part)


def run(output: Path = OUT) -> dict[str, Any]:
    symbols = cs.universe()
    batches = [symbols[i : i + BATCH] for i in range(0, len(symbols), BATCH)]
    for number, batch in enumerate(batches):
        part = PARTS / f"{number:03d}.pkl"
        if part.exists():
            continue
        command = [sys.executable, "-m", "eulerlab.intraday.cash_five_screen", "--part", str(part)]
        subprocess.run([*command, "--batch", *batch], check=True)
        print(f"  batch {number + 1}/{len(batches)} done", file=sys.stderr, flush=True)
    marks: dict[str, dict[str, Any]] = {"in_play": {}, "high52": {}, "panic": {}}
    sessions: set[date] = set()
    for number in range(len(batches)):
        loaded = pickle.loads((PARTS / f"{number:03d}.pkl").read_bytes())
        sessions.update(loaded["sessions"])
        for symbol, found in loaded["marks"].items():
            for name in marks:
                marks[name][symbol] = found[name]
    window = sorted(d for d in sessions if d <= cs.DATA_END)
    index = load_index()
    etf = rs.load_days(ETF, cache=False)
    moves = index_moves(index)
    index_window = sorted({d.day for d in index} & {d.day for d in etf})
    stock_index_window = [d for d in window if d >= index_window[0]] if index_window else []
    runs = [
        {"hypothesis": "H-0045", **evaluate_in_play(marks["in_play"], window)},
        {"hypothesis": "H-0046", **evaluate_year_high(marks["high52"], window)},
        {
            "hypothesis": "H-0047",
            **evaluate_panic_stocks(marks["panic"], moves, stock_index_window),
        },
        {"hypothesis": "H-0048", **evaluate_panic_index(moves, etf, index_window)},
        {"hypothesis": "H-0049", **evaluate_premium(premium_trades(index, etf), index_window)},
    ]
    result = {
        "research": "docs/RESEARCH/155-five-cash-intraday-rules.md",
        "universe": len(symbols),
        "spent_trials": 0,
        "runs": runs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="cash-five")
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--batch", nargs="+", help=argparse.SUPPRESS)
    parser.add_argument("--part", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.batch:
        # Through the module, not `__main__`, so the pickled classes can be read by others.
        import importlib

        importlib.import_module("eulerlab.intraday.cash_five_screen").extract_batch(
            args.batch, args.part
        )
        return 0
    result = run(args.output)
    for one in result["runs"]:
        print(
            f"{one['hypothesis']} {one['id']}: {one['trades']} trades; "
            f"{one['per_trade_bps']['gross_mean']} bps gross, "
            f"{one['per_trade_bps']['net_mean']} net a trade; net Sharpe {one['net']['sharpe']}"
        )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
