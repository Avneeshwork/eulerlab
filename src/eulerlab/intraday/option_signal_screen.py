"""Cash rules on option signals, half-hours and overnight winners (research 158).

Pre-registered as H-0061 to H-0065 before any run. Options are read, never
traded; trades are cash shares (₹1 lakh) or NIFTYBEES (₹10 lakh), 1x, with
cash-intraday charges plus 2 bps a side, on Kite minute bars to 2024-11-29.

- **H-0061 expiry pinning.** Golez and Jackwerth (2012): on weekly expiry day,
  the expiring series' strike with the most call-plus-put open interest at the
  prior close; if the Nifty at 13:00 is 0.3% or more away, NIFTYBEES toward
  it, 13:01 to 15:10.
- **H-0062 expiry gamma momentum.** Baltussen et al. (2021): on expiry day,
  NIFTYBEES with the Nifty's move from the prior close to 14:40, 14:41 to 15:10.
- **H-0063 put-call contrarian.** Nearest-expiry put/call open interest at the
  prior close in the top fifth of its last 250 sessions: NIFTYBEES long 09:20
  to 15:10; bottom fifth: short. "Nearest" is the nearest expiry after the
  prior session, so a series expiring that afternoon is not used.
- **H-0064 same half-hour.** Heston, Korajczyk and Sadka (2010): stocks ranked
  on yesterday's 14:40-15:10 return; top decile long, bottom short, 14:40 to
  15:10.
- **H-0065 overnight winners.** Lou, Polk and Skouras (2019): stocks ranked on
  their mean overnight move over 20 sessions; top decile short, bottom long,
  09:20 to 15:10. Read from the india-five cache, no minute file opened.

`make option-signals` writes `data/derived/option_signals.json`.
"""

from __future__ import annotations

import argparse
import importlib
import json
import pickle
import subprocess
import sys
from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from eulerlab.intraday import cash_five_screen as five
from eulerlab.intraday import cross_section as cs
from eulerlab.intraday import india_five_screen as india_five
from eulerlab.intraday import india_papers as ip
from eulerlab.intraday import research_screen as rs
from eulerlab.options import nifty_history

OUT = Path("data/derived/option_signals.json")
PARTS = Path("data/derived/option_signals_parts")
BATCH = 40
START = date(2021, 6, 1)
"""Option days read from here: a year of put-call history before the window."""

PIN_MINUTE = 225
"""13:00."""
PIN_GAP = 0.003
GAMMA_MINUTE = 325
"""14:40."""
PCR_HISTORY = 250
PCR_HIGH, PCR_LOW = 0.8, 0.2
HALF_HOUR = 325
"""14:40 to the 15:10 exit."""
LOOKBACK = 20
MIN_NAMES = 100
DAY_START = 5


@dataclass(frozen=True)
class OptionDay:
    day: date
    pin_for_next: dict[date, float]
    """{expiry: strike with the most call+put open interest} for every listed expiry."""
    pcr: float | None
    """Put/call open interest of the nearest expiry after this day."""


def option_days(
    path: Path = nifty_history.OUT, start: date = START, end: date = cs.DATA_END
) -> list[OptionDay]:
    out = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            day = date.fromisoformat(line[6:16])
            if day < start or day > end:
                continue
            row = json.loads(line)
            by_expiry: dict[str, dict[float, float]] = defaultdict(lambda: defaultdict(float))
            calls: dict[str, float] = defaultdict(float)
            puts: dict[str, float] = defaultdict(float)
            for expiry, strike, right, _close, _settle, _volume, oi, _lot in row["opt"]:
                by_expiry[expiry][strike] += oi or 0.0
                (calls if right == "CE" else puts)[expiry] += oi or 0.0
            pins = {
                date.fromisoformat(e): max(strikes, key=lambda k: (strikes[k], -k))
                for e, strikes in by_expiry.items()
                if any(strikes.values())
            }
            later = sorted(e for e in calls if e > row["d"])
            pcr = puts[later[0]] / calls[later[0]] if later and calls[later[0]] > 0 else None
            out.append(OptionDay(day, pins, pcr))
    return out


def _fill(day: ip.Day, start: int, direction: int) -> five.Fill | None:
    entry, leave = day.fill_at(start), day.fill_at(cs.EXIT)
    if entry is None or leave is None or entry[0] >= leave[0]:
        return None
    return five.Fill(start, direction, entry[0], entry[1], leave[0], leave[1])


def _pairs(
    index: Sequence[ip.Day], etf: Sequence[ip.Day]
) -> Iterator[tuple[ip.Day, ip.Day, float]]:
    """(index day, NIFTYBEES day, the Nifty's prior close) for each common session."""
    traded = {d.day: d for d in etf}
    for i in range(1, len(index)):
        day = traded.get(index[i].day)
        if day is not None:
            yield index[i], day, index[i - 1].close[index[i - 1].last]


def pin_trades(
    index: Sequence[ip.Day], etf: Sequence[ip.Day], options: Sequence[OptionDay]
) -> list[tuple[date, five.Fill]]:
    prior = {options[i].day: options[i - 1] for i in range(1, len(options))}
    out = []
    for nifty, traded, _ in _pairs(index, etf):
        before = prior.get(nifty.day)
        pin = before.pin_for_next.get(nifty.day) if before else None
        if pin is None:
            continue
        level = nifty.close[PIN_MINUTE]
        if level >= pin * (1 + PIN_GAP):
            direction = -1
        elif level <= pin * (1 - PIN_GAP):
            direction = 1
        else:
            continue
        fill = _fill(traded, PIN_MINUTE + 1, direction)
        if fill is not None:
            out.append((nifty.day, fill))
    return out


def gamma_trades(
    index: Sequence[ip.Day], etf: Sequence[ip.Day], expiries: set[date]
) -> list[tuple[date, five.Fill]]:
    out = []
    for nifty, traded, before in _pairs(index, etf):
        if nifty.day not in expiries:
            continue
        move = nifty.close[GAMMA_MINUTE] / before - 1.0
        if move == 0:
            continue
        fill = _fill(traded, GAMMA_MINUTE + 1, 1 if move > 0 else -1)
        if fill is not None:
            out.append((nifty.day, fill))
    return out


def pcr_signals(options: Sequence[OptionDay]) -> dict[date, int]:
    """{session: +1 long, -1 short} from the prior close's put-call ratio percentile."""
    out: dict[date, int] = {}
    history: list[float] = []
    for i in range(1, len(options)):
        before = options[i - 1]
        if before.pcr is not None and len(history) >= PCR_HISTORY:
            past = history[-PCR_HISTORY:]
            rank = sum(1 for x in past if x < before.pcr) / PCR_HISTORY
            if rank >= PCR_HIGH:
                out[options[i].day] = 1
            elif rank <= PCR_LOW:
                out[options[i].day] = -1
        if before.pcr is not None:
            history.append(before.pcr)
    return out


def pcr_trades(etf: Sequence[ip.Day], signals: Mapping[date, int]) -> list[tuple[date, five.Fill]]:
    out = []
    for day in etf:
        direction = signals.get(day.day)
        if direction:
            fill = _fill(day, DAY_START, direction)
            if fill is not None:
                out.append((day.day, fill))
    return out


def half_hours(
    _symbol: str, days: Sequence[ip.Day]
) -> dict[date, tuple[float | None, five.Fill | None]]:
    """{session: (the previous session's 14:40-15:10 return, today's 14:40-15:10 fill)}."""
    out: dict[date, tuple[float | None, five.Fill | None]] = {}
    previous: float | None = None
    for index, day in enumerate(days):
        before = cs.previous_close(days, index)
        today = _fill(day, HALF_HOUR, 1)
        if before is not None and before >= five.MIN_PRICE:
            gap_ok = index > 0 and (day.day - days[index - 1].day).days <= 7
            out[day.day] = (previous if gap_ok else None, today)
        previous = today.exit / today.entry - 1.0 if today else None
    return out


def _deciles(
    run_id: str,
    ranked_by_day: Mapping[date, list[tuple[float, str, five.Fill]]],
    sessions: Sequence[date],
    *,
    top_direction: int,
) -> dict[str, Any]:
    trades, widest = [], 1
    for day, ranked in ranked_by_day.items():
        if len(ranked) < MIN_NAMES:
            continue
        ranked.sort(key=lambda item: (item[0], item[1]))
        decile = len(ranked) // 10
        widest = max(widest, decile)
        for direction, chosen in (
            (top_direction, ranked[-decile:]),
            (-top_direction, ranked[:decile]),
        ):
            for _, symbol, fill in chosen:
                trade = five._trade(symbol, day, fill, direction, five.TRADE)
                if trade:
                    trades.append(trade)
    run = cs.report(
        run_id,
        trades,
        sessions,
        params={"slippage_bps_per_side": cs.SLIPPAGE_BPS},
        capital=five.TRADE * 2 * widest,
    )
    return five._halves(run)


def evaluate_half_hours(
    marks: Mapping[str, Mapping[date, tuple[float | None, five.Fill | None]]],
    sessions: Sequence[date],
) -> dict[str, Any]:
    by_day: dict[date, list[tuple[float, str, five.Fill]]] = defaultdict(list)
    for symbol, days in marks.items():
        for day, (signal, fill) in days.items():
            if signal is not None and fill is not None:
                by_day[day].append((signal, symbol, fill))
    return _deciles("nse_same_half_hour_close", by_day, sessions, top_direction=1)


def overnight_ranks(
    cache: Mapping[str, Mapping[date, Any]],
) -> dict[date, list[tuple[float, str, five.Fill]]]:
    by_day: dict[date, list[tuple[float, str, five.Fill]]] = defaultdict(list)
    for symbol, marks in cache.items():
        days = sorted(marks)
        for i in range(LOOKBACK, len(days)):
            mean = sum(marks[d].overnight for d in days[i - LOOKBACK : i]) / LOOKBACK
            mark = marks[days[i]]
            fill = five.Fill(
                DAY_START, 1, mark.entry_minute, mark.entry, mark.exit_minute, mark.exit
            )
            by_day[days[i]].append((mean, symbol, fill))
    return by_day


def _etf_run(
    run_id: str, fills: Sequence[tuple[date, five.Fill]], sessions: Sequence[date]
) -> dict[str, Any]:
    trades = []
    for day, fill in fills:
        trade = five._trade(five.ETF, day, fill, fill.direction, five.ETF_CAPITAL)
        if trade:
            trades.append(trade)
    run = cs.report(
        run_id,
        trades,
        sessions,
        params={"slippage_bps_per_side": cs.SLIPPAGE_BPS},
        capital=five.ETF_CAPITAL,
    )
    return five._halves(run)


# --- running -------------------------------------------------------------------------


def extract_batch(symbols: list[str], part: Path) -> None:
    found, sessions = cs.scan(symbols, {"marks": half_hours})
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
        command = [
            sys.executable,
            "-m",
            "eulerlab.intraday.option_signal_screen",
            "--part",
            str(part),
        ]
        subprocess.run([*command, "--batch", *batch], check=True)
        print(f"  batch {number + 1}/{len(batches)} done", file=sys.stderr, flush=True)
    halves: dict[str, Any] = {}
    sessions: set[date] = set()
    for number in range(len(batches)):
        loaded = pickle.loads((PARTS / f"{number:03d}.pkl").read_bytes())
        sessions.update(loaded["sessions"])
        halves.update(loaded["marks"])
    window = sorted(d for d in sessions if d <= cs.DATA_END)
    cache = {}
    for symbol in symbols:
        cached = india_five._cached(symbol)
        if cached.exists():
            cache[symbol] = pickle.loads(cached.read_bytes())["marks"]["overnight"]
    index = five.load_index()
    etf = rs.load_days(five.ETF, cache=False)
    index_window = sorted({d.day for d in index} & {d.day for d in etf})
    options = option_days()
    expiries = {d.day for d in options if d.day in d.pin_for_next}
    runs = [
        {
            "hypothesis": "H-0061",
            **_etf_run("nifty_expiry_pin_niftybees", pin_trades(index, etf, options), index_window),
        },
        {
            "hypothesis": "H-0062",
            **_etf_run(
                "nifty_expiry_gamma_momentum_niftybees",
                gamma_trades(index, etf, expiries),
                index_window,
            ),
        },
        {
            "hypothesis": "H-0063",
            **_etf_run(
                "nifty_pcr_contrarian_niftybees",
                pcr_trades(etf, pcr_signals(options)),
                index_window,
            ),
        },
        {"hypothesis": "H-0064", **evaluate_half_hours(halves, window)},
        {
            "hypothesis": "H-0065",
            **_deciles(
                "nse_overnight_winners_daytime_reversal",
                overnight_ranks(cache),
                window,
                top_direction=-1,
            ),
        },
    ]
    result = {
        "research": "docs/RESEARCH/158-option-signals-and-half-hours.md",
        "universe": len(symbols),
        "expiry_days": len(
            [d for d in expiries if index_window and index_window[0] <= d <= index_window[-1]]
        ),
        "spent_trials": 0,
        "runs": runs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="option-signals")
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--batch", nargs="+", help=argparse.SUPPRESS)
    parser.add_argument("--part", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.batch:
        # Through the module, not `__main__`, so the pickled classes can be read by others.
        importlib.import_module("eulerlab.intraday.option_signal_screen").extract_batch(
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
