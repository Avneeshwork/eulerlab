"""Six minute-level cash rules: laggards, pairs, ex-dates, VWAP (research 161).

Pre-registered as H-0077 to H-0082 before any run. Kite minute bars of F&O
stocks to 2024-11-29; a decision uses a completed minute's close and fills at
the next minute's open; 09:20 entries fill at the first open from 09:20; every
exit is 15:10. ₹1 lakh a position, 1x; cash-intraday charges plus 2 bps a side.

- **H-0077 industry laggards** (Hou 2007). At 11:15, score = industry mean
  09:20-11:15 return without the stock minus the stock's own. Top decile long,
  bottom decile short, 11:16 to 15:10.
- **H-0078 market-move laggards** (Chordia and Swaminathan 2000). Nifty moved
  0.5% from 09:20 to 10:30: among the thinner half of stocks by 20-session
  traded value, the ten that lagged most, in the Nifty's direction, 10:31 on.
- **H-0079 intraday pairs** (Bowen, Hutchinson and O'Sullivan 2010). Twenty
  closest distance pairs within industries, re-formed every 20 sessions on 40;
  open at a 2-sigma spread on 5-minute closes, close at zero or 15:10.
- **H-0080 bonus or split ex-date; H-0081 ex-dividend day (1%+ yield).** Buy at
  09:20, sell at 15:10, at most ten a day.
- **H-0082 VWAP stretch.** 10:00-14:30, the first close 1.5% from session VWAP:
  trade toward it; exit when a close crosses it, or 15:10.

Each stock-day is reduced to a `Snap` (5-minute closes and next-minute fills)
so the cross-stock rules need not hold minute files together.
`make minute-six` writes `data/derived/minute_six.json`.
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import pickle
import subprocess
import sys
from array import array
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from itertools import combinations
from pathlib import Path
from typing import Any

from eulerlab.intraday import cash_five_screen as five
from eulerlab.intraday import cross_section as cs
from eulerlab.intraday import india_papers as ip
from eulerlab.intraday import option_signal_screen as sig
from eulerlab.paths import data_path

OUT = data_path("derived/minute_six.json")
PARTS = data_path("derived/minute_six_parts")
BATCH = 40
DAY_START = 5
"""09:20, as minutes after 09:15."""
STEP = 5
CHECKPOINTS = tuple(range(DAY_START, cs.EXIT + 1, STEP))
"""09:20, 09:25, ... 15:10: the minutes whose closes a `Snap` keeps."""

INDUSTRY_MINUTE = 120  # 11:15
MIN_INDUSTRY = 4
MARKET_MINUTE = 75  # 10:30
MARKET_MOVE = 0.005
VALUE_DAYS = 20
LAGGARDS = 10
PAIR_FORM, PAIR_TRADE, PAIRS = 40, 20, 20
PAIR_SIGMAS = 2.0
PAIR_FIRST, PAIR_LAST = 10, 315  # 09:25, 14:30
DIVIDEND_YIELD = 0.01
VWAP_FIRST, VWAP_LAST = 45, 315  # 10:00, 14:30
VWAP_STRETCH = 0.015


@dataclass(frozen=True)
class Snap:
    """One stock-day, reduced to what the six rules read."""

    entry_minute: int
    entry: float
    exit_minute: int
    exit: float
    closes: array[float]
    """Close at each of `CHECKPOINTS`."""
    fills: array[float]
    """Open of the first traded minute after each checkpoint; NaN if none before the exit."""
    fill_minutes: array[int]
    last_close: float
    value: float
    """Traded value: sum of close x volume."""
    vwap: five.Fill | None
    """H-0082's trade this day, if any."""


def _k(minute: int) -> int:
    return (minute - DAY_START) // STEP


def vwap_trade(day: ip.Day) -> five.Fill | None:
    """H-0082: the first 1.5% stretch from session VWAP, 10:00 to 14:30."""
    volume = price_volume = 0.0
    direction = signal = 0
    entry: tuple[int, float] | None = None
    for m in range(ip.FIRST_TRADABLE, cs.EXIT):
        high, low = day.high[m], day.low[m]
        if high is not None and low is not None and day.volume[m] > 0:
            price_volume += (high + low + day.close[m]) / 3.0 * day.volume[m]
            volume += day.volume[m]
        if volume <= 0:
            continue
        vwap, close = price_volume / volume, day.close[m]
        if entry is None:
            if not VWAP_FIRST <= m <= VWAP_LAST or close < cs.MIN_PRICE:
                continue
            if abs(close / vwap - 1.0) >= VWAP_STRETCH:
                direction = 1 if close < vwap else -1
                entry = day.fill_at(m + 1)
                if entry is None or entry[0] >= cs.EXIT:
                    return None
                signal = m
        elif m >= entry[0] and (close - vwap) * direction >= 0:
            leave = day.fill_at(m + 1)
            if leave is not None and leave[0] < cs.EXIT:
                return five.Fill(signal, direction, *entry, *leave, "vwap")
            break
    if entry is None:
        return None
    leave = day.fill_at(cs.EXIT)
    if leave is None or leave[0] <= entry[0]:
        return None
    return five.Fill(signal, direction, *entry, *leave)


def snap(day: ip.Day) -> Snap | None:
    entry, leave = day.fill_at(DAY_START), day.fill_at(cs.EXIT)
    if entry is None or leave is None or entry[0] >= leave[0]:
        return None
    closes, fills, minutes = array("d"), array("d"), array("h")
    for m in CHECKPOINTS:
        closes.append(day.close[m])
        found = day.fill_at(m + 1)
        ok = found is not None and found[0] < leave[0]
        fills.append(found[1] if found is not None and ok else math.nan)
        minutes.append(found[0] if found is not None and ok else -1)
    value = sum(c * v for c, v in zip(day.close, day.volume, strict=True))
    return Snap(
        entry[0],
        entry[1],
        leave[0],
        leave[1],
        closes,
        fills,
        minutes,
        day.close[day.last],
        value,
        vwap_trade(day),
    )


def extract(_symbol: str, days: Sequence[ip.Day]) -> dict[date, Snap]:
    out = {}
    for day in days:
        found = snap(day)
        if found is not None:
            out[day.day] = found
    return out


Snaps = Mapping[str, Mapping[date, Snap]]
Ranked = dict[date, list[tuple[float, str, five.Fill]]]


def _from(s: Snap, minute: int, direction: int = 1) -> five.Fill | None:
    k = _k(minute)
    if s.fill_minutes[k] < 0:
        return None
    return five.Fill(minute, direction, s.fill_minutes[k], s.fills[k], s.exit_minute, s.exit)


# --- H-0077 industry laggards ----------------------------------------------------------


def industry_ranks(snaps: Snaps, industry: Mapping[str, str]) -> Ranked:
    k = _k(INDUSTRY_MINUTE)
    by_day: dict[date, dict[str, list[tuple[str, float, Snap]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for symbol, days in snaps.items():
        group = industry.get(symbol)
        if not group:
            continue
        for d, s in days.items():
            if s.entry >= cs.MIN_PRICE:
                by_day[d][group].append((symbol, s.closes[k] / s.entry - 1.0, s))
    out: Ranked = defaultdict(list)
    for d, groups in by_day.items():
        for members in groups.values():
            if len(members) < MIN_INDUSTRY:
                continue
            total = sum(r for _, r, _ in members)
            for symbol, r, s in members:
                fill = _from(s, INDUSTRY_MINUTE)
                if fill is not None:
                    out[d].append(((total - r) / (len(members) - 1) - r, symbol, fill))
    return out


# --- H-0078 market-move laggards -------------------------------------------------------


def nifty_moves(index: Sequence[ip.Day]) -> dict[date, float]:
    return {d.day: d.close[MARKET_MINUTE] / d.close[DAY_START] - 1.0 for d in index}


def market_laggards(snaps: Snaps, moves: Mapping[date, float]) -> list[tuple[date, str, five.Fill]]:
    k = _k(MARKET_MINUTE)
    mean_value: dict[date, list[tuple[float, str, Snap]]] = defaultdict(list)
    for symbol, days in snaps.items():
        ordered = sorted(days)
        for i in range(VALUE_DAYS, len(ordered)):
            d = ordered[i]
            if abs(moves.get(d, 0.0)) < MARKET_MOVE:
                continue
            past = sum(days[x].value for x in ordered[i - VALUE_DAYS : i]) / VALUE_DAYS
            mean_value[d].append((past, symbol, days[d]))
    out: list[tuple[date, str, five.Fill]] = []
    for d, names in mean_value.items():
        names.sort(key=lambda item: (item[0], item[1]))
        thin = names[: len(names) // 2]
        sign = 1 if moves[d] > 0 else -1
        lags = []
        for _, symbol, s in thin:
            if s.entry < cs.MIN_PRICE:
                continue
            fill = _from(s, MARKET_MINUTE, sign)
            if fill is not None:
                lag = sign * (s.closes[k] / s.entry - 1.0 - moves[d])
                lags.append((lag, symbol, fill))
        lags.sort(key=lambda item: (item[0], item[1]))
        out.extend((d, symbol, fill) for _, symbol, fill in lags[:LAGGARDS])
    return out


# --- H-0079 intraday pairs -------------------------------------------------------------


def _spread(a: Snap, b: Snap, k: int) -> float:
    return math.log(a.closes[k] / a.closes[0]) - math.log(b.closes[k] / b.closes[0])


def form_pairs(
    snaps: Snaps, industry: Mapping[str, str], window: Sequence[date]
) -> list[tuple[str, str, float]]:
    """The closest pairs within industries over `window`: (a, b, sigma)."""
    last = len(CHECKPOINTS) - 1
    groups: dict[str, list[str]] = defaultdict(list)
    for symbol in sorted(snaps):
        days = snaps[symbol]
        if industry.get(symbol) and all(d in days for d in window):
            groups[industry[symbol]].append(symbol)
    scored = []
    for members in groups.values():
        normal = {
            s: [snaps[s][d].closes[last] / snaps[s][window[0]].closes[last] for d in window]
            for s in members
        }
        for a, b in combinations(members, 2):
            ssd = sum((x - y) ** 2 for x, y in zip(normal[a], normal[b], strict=True))
            scored.append((ssd, a, b))
    scored.sort()
    out: list[tuple[str, str, float]] = []
    for _, a, b in scored[:PAIRS]:
        changes = [_spread(snaps[a][d], snaps[b][d], last) for d in window]
        mean = sum(changes) / len(changes)
        sigma = math.sqrt(sum((c - mean) ** 2 for c in changes) / (len(changes) - 1))
        if sigma > 0:
            out.append((a, b, sigma))
    return out


def pair_trade(a: Snap, b: Snap, sigma: float) -> tuple[five.Fill, five.Fill] | None:
    """(leg a, leg b) for one pair-day, if the spread reached 2 sigma."""
    for k in range(_k(PAIR_FIRST), _k(PAIR_LAST) + 1):
        s = _spread(a, b, k)
        if abs(s) < PAIR_SIGMAS * sigma:
            continue
        if a.fill_minutes[k] < 0 or b.fill_minutes[k] < 0:
            return None
        sign = 1 if s > 0 else -1  # a is ahead: short a, buy b
        exits = [(a.exit_minute, a.exit, b.exit_minute, b.exit, "time_exit")]
        for j in range(k + 1, len(CHECKPOINTS) - 1):
            if _spread(a, b, j) * sign <= 0 and a.fill_minutes[j] >= 0 and b.fill_minutes[j] >= 0:
                exits = [(a.fill_minutes[j], a.fills[j], b.fill_minutes[j], b.fills[j], "zero")]
                break
        am, ap, bm, bp, why = exits[0]
        minute = CHECKPOINTS[k]
        return (
            five.Fill(minute, -sign, a.fill_minutes[k], a.fills[k], am, ap, why),
            five.Fill(minute, sign, b.fill_minutes[k], b.fills[k], bm, bp, why),
        )
    return None


def pair_trades(
    snaps: Snaps, industry: Mapping[str, str], sessions: Sequence[date]
) -> list[tuple[date, str, five.Fill]]:
    out: list[tuple[date, str, five.Fill]] = []
    for start in range(PAIR_FORM, len(sessions), PAIR_TRADE):
        pairs = form_pairs(snaps, industry, sessions[start - PAIR_FORM : start])
        for d in sessions[start : start + PAIR_TRADE]:
            for a, b, sigma in pairs:
                if d in snaps[a] and d in snaps[b]:
                    legs = pair_trade(snaps[a][d], snaps[b][d], sigma)
                    if legs is not None:
                        out += [(d, a, legs[0]), (d, b, legs[1])]
    return out


# --- H-0080 and H-0081 ex-dates --------------------------------------------------------


def ex_dates(actions: Sequence[Any]) -> dict[str, dict[date, tuple[str, float | None]]]:
    """{symbol: {ex-date: ("split" or "dividend", dividend amount)}}."""
    from eulerlab.corp_actions.parse import Kind

    out: dict[str, dict[date, tuple[str, float | None]]] = defaultdict(dict)
    for action in actions:
        for part in action.components:
            if part.kind in (Kind.BONUS, Kind.SPLIT):
                out[action.symbol][action.ex_date] = ("split", None)
            elif part.kind is Kind.DIVIDEND and part.dividend_amount:
                kind, amount = out[action.symbol].get(action.ex_date, ("dividend", 0.0))
                if kind == "dividend":
                    total = (amount or 0.0) + part.dividend_amount
                    out[action.symbol][action.ex_date] = ("dividend", total)
    return out


def ex_date_trades(
    snaps: Snaps, events: Mapping[str, Mapping[date, tuple[str, float | None]]], kind: str
) -> list[tuple[date, str, five.Fill]]:
    by_day: dict[date, list[tuple[str, five.Fill]]] = defaultdict(list)
    for symbol, days in snaps.items():
        ordered = sorted(days)
        for i, d in enumerate(ordered):
            event = events.get(symbol, {}).get(d)
            if event is None or event[0] != kind or i == 0:
                continue
            s = days[d]
            if kind == "dividend":
                before = days[ordered[i - 1]].last_close
                if (d - ordered[i - 1]).days > 7 or (event[1] or 0.0) < DIVIDEND_YIELD * before:
                    continue
            if s.entry >= cs.MIN_PRICE:
                fill = five.Fill(DAY_START, 1, s.entry_minute, s.entry, s.exit_minute, s.exit)
                by_day[d].append((symbol, fill))
    out: list[tuple[date, str, five.Fill]] = []
    for d, found in by_day.items():
        out.extend((d, symbol, fill) for symbol, fill in sorted(found)[: five.MAX_OPEN])
    return out


# --- H-0082 VWAP stretch ---------------------------------------------------------------


def vwap_trades(snaps: Snaps) -> list[tuple[date, str, five.Fill]]:
    by_day: dict[date, list[tuple[int, str, five.Fill]]] = defaultdict(list)
    for symbol, days in snaps.items():
        for d, s in days.items():
            if s.vwap is not None:
                by_day[d].append((s.vwap.minute, symbol, s.vwap))
    out: list[tuple[date, str, five.Fill]] = []
    for d, found in by_day.items():
        found.sort(key=lambda item: (item[0], item[1]))
        out.extend((d, symbol, fill) for _, symbol, fill in found[: five.MAX_OPEN])
    return out


# --- evaluation and running ------------------------------------------------------------


def evaluate(
    run_id: str,
    fills: Sequence[tuple[date, str, five.Fill]],
    sessions: Sequence[date],
    capital: float,
) -> dict[str, Any]:
    trades = []
    for d, symbol, fill in fills:
        trade = five._trade(symbol, d, fill, fill.direction, five.TRADE)
        if trade:
            trades.append(trade)
    run = cs.report(
        run_id,
        trades,
        sessions,
        params={"slippage_bps_per_side": cs.SLIPPAGE_BPS},
        capital=capital,
    )
    return five._halves(run)


def extract_batch(symbols: list[str], part: Path) -> None:
    found, sessions = cs.scan(symbols, {"snaps": extract})
    part.parent.mkdir(parents=True, exist_ok=True)
    tmp = part.with_suffix(".partial")
    tmp.write_bytes(pickle.dumps({"snaps": found["snaps"], "sessions": sessions}))
    tmp.replace(part)


def load_actions() -> list[Any]:
    from eulerlab.corp_actions.parse import parse_rows
    from eulerlab.ingest import landing_reader

    rows: list[dict[str, object]] = []
    manifest = data_path("landing/nse/manifest.jsonl")
    for line in manifest.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry.get("segment") == "corp_actions":
            rows.extend(json.loads(landing_reader.read(f"nse/{entry['path']}", cache=False)))
    actions, _ = parse_rows(rows)
    return actions


def run(output: Path = OUT) -> dict[str, Any]:
    from eulerlab.features import company

    symbols = cs.universe()
    batches = [symbols[i : i + BATCH] for i in range(0, len(symbols), BATCH)]
    for number, batch in enumerate(batches):
        part = PARTS / f"{number:03d}.pkl"
        if part.exists():
            continue
        command = [sys.executable, "-m", "eulerlab.intraday.minute_six_screen", "--part", str(part)]
        subprocess.run([*command, "--batch", *batch], check=True)
        print(f"  batch {number + 1}/{len(batches)} done", file=sys.stderr, flush=True)
    snaps: dict[str, dict[date, Snap]] = {}
    sessions: set[date] = set()
    for number in range(len(batches)):
        loaded = pickle.loads((PARTS / f"{number:03d}.pkl").read_bytes())
        sessions.update(loaded["sessions"])
        snaps.update(loaded["snaps"])
    window = sorted(d for d in sessions if d <= cs.DATA_END)
    industry = {s: c.industry for s, c in company.load_digest().items() if c.industry}
    events = ex_dates(load_actions())
    moves = nifty_moves(five.load_index())
    pair_fills = pair_trades(snaps, industry, window)
    runs = [
        {
            "hypothesis": "H-0077",
            **sig._deciles(
                "nse_industry_laggards", industry_ranks(snaps, industry), window, top_direction=1
            ),
        },
        {
            "hypothesis": "H-0078",
            **evaluate(
                "nse_market_move_laggards",
                market_laggards(snaps, moves),
                window,
                five.TRADE * LAGGARDS,
            ),
        },
        {
            "hypothesis": "H-0079",
            **evaluate("nse_intraday_pairs", pair_fills, window, five.TRADE * 2 * PAIRS),
        },
        {
            "hypothesis": "H-0080",
            **evaluate(
                "nse_bonus_split_ex_date",
                ex_date_trades(snaps, events, "split"),
                window,
                five.TRADE * five.MAX_OPEN,
            ),
        },
        {
            "hypothesis": "H-0081",
            **evaluate(
                "nse_ex_dividend_day",
                ex_date_trades(snaps, events, "dividend"),
                window,
                five.TRADE * five.MAX_OPEN,
            ),
        },
        {
            "hypothesis": "H-0082",
            **evaluate("nse_vwap_stretch", vwap_trades(snaps), window, five.TRADE * five.MAX_OPEN),
        },
    ]
    result = {
        "research": "docs/RESEARCH/161-six-minute-rules.md",
        "universe": len(snaps),
        "with_industry": sum(1 for s in snaps if s in industry),
        "market_move_days": sum(1 for d in window if abs(moves.get(d, 0.0)) >= MARKET_MOVE),
        "spent_trials": 0,
        "runs": runs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="minute-six")
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--batch", nargs="+", help=argparse.SUPPRESS)
    parser.add_argument("--part", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.batch:
        # Through the module, not `__main__`, so the pickled classes can be read by others.
        importlib.import_module("eulerlab.intraday.minute_six_screen").extract_batch(
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
