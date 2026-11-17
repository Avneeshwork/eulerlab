"""Five cash rules: beta, lottery stocks, the last half-hour, pinning, OI build-up (research 162).

Pre-registered as H-0083 to H-0087 before any run. No minute file is opened:
the rules read research 161's stock-day snapshots (`minute_six_parts`, made by
`make minute-six`) and one compact file of stock F&O open interest built here
from the NSE F&O bhavcopies. ₹1 lakh a position, 1x; cash-intraday charges
plus 2 bps a side; to 2024-11-29.

- **H-0083 beta by day** (Hendershott, Livdan and Rösch 2020): buy the
  lowest decile of 60-session beta, short the highest, 09:20 to 15:10.
- **H-0084 lottery stocks by day** (Bali, Cakici and Whitelaw 2011): short the
  top decile of the largest daily return in 20 sessions, buy the bottom.
- **H-0085 illiquid stocks, last half-hour** (Bogousslavsky 2021): buy the
  lowest decile of 20-session traded value, short the highest, 14:41 to 15:10.
- **H-0086 stock option pinning** (Ni, Pearson and Poteshman 2005): on monthly
  expiry, a stock 1% to 3% from its largest open-interest strike at 13:00 is
  traded toward it to 15:10; at most ten, closest first.
- **H-0087 futures OI build-up** (trader practice): yesterday ±2% with futures
  open interest up 10%: follow it today, 09:20 to 15:10; at most ten.

Daily returns are close to close from the snapshots; a return beyond ±20% is
dropped as a likely split (the minute closes are not adjusted).
`make stock-fo` writes `data/derived/stock_fo.json`.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import pickle
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import Any

from eulerlab.intraday import cross_section as cs
from eulerlab.paths import data_path
from eulerlab.strategies.studies import cash_five as five
from eulerlab.strategies.studies import minute_six as six
from eulerlab.strategies.studies import option_signal as sig

OUT = data_path("derived/stock_fo.json")
FO_DAILY = data_path("derived/stock_fo_daily.jsonl")
FO_FROM = "2021-07-01"
MAX_RETURN = 0.20
BETA_DAYS, BETA_MIN = 60, 50
MAX_DAYS, MAX_MIN = 20, 15
VALUE_DAYS = 20
LATE_MINUTE = 325  # 14:40
PIN_MINUTE = 225  # 13:00
PIN_NEAR, PIN_FAR = 0.01, 0.03
BUILD_RETURN, BUILD_OI = 0.02, 0.10

Ranked = dict[date, list[tuple[float, str, five.Fill]]]
Fills = list[tuple[date, str, five.Fill]]
FoDay = dict[str, Any]
"""{"d": day, "oi": {symbol: futures OI}, "pin": {symbol: [expiry, strike, OI]}}."""


# --- daily series from the snapshots -------------------------------------------------


def daily_returns(days: Mapping[date, six.Snap]) -> dict[date, float]:
    """Close-to-close returns; a gap of over a week or a move beyond ±20% is dropped."""
    out = {}
    ordered = sorted(days)
    for before, today in pairwise(ordered):
        if (today - before).days > 7:
            continue
        r = days[today].last_close / days[before].last_close - 1.0
        if abs(r) <= MAX_RETURN:
            out[today] = r
    return out


def nifty_returns(index: Sequence[Any]) -> dict[date, float]:
    out = {}
    for before, today in pairwise(index):
        out[today.day] = today.close[today.last] / before.close[before.last] - 1.0
    return out


def _day_fill(s: six.Snap) -> five.Fill:
    return five.Fill(six.DAY_START, 1, s.entry_minute, s.entry, s.exit_minute, s.exit)


def beta_and_max(snaps: six.Snaps, market: Mapping[date, float]) -> tuple[Ranked, Ranked]:
    """(H-0083 beta, H-0084 MAX) rankings, by session, from earlier sessions only."""
    betas: Ranked = defaultdict(list)
    maxes: Ranked = defaultdict(list)
    for symbol, days in snaps.items():
        returns = daily_returns(days)
        ordered = sorted(days)
        for i, d in enumerate(ordered):
            s = days[d]
            if s.entry < cs.MIN_PRICE:
                continue
            fill = _day_fill(s)
            month = [returns[x] for x in ordered[max(0, i - MAX_DAYS) : i] if x in returns]
            if len(month) >= MAX_MIN:
                maxes[d].append((max(month), symbol, fill))
            pairs = [
                (returns[x], market[x])
                for x in ordered[max(0, i - BETA_DAYS) : i]
                if x in returns and x in market
            ]
            if len(pairs) >= BETA_MIN:
                mean_s = sum(p[0] for p in pairs) / len(pairs)
                mean_m = sum(p[1] for p in pairs) / len(pairs)
                cov = sum((a - mean_s) * (b - mean_m) for a, b in pairs)
                var = sum((b - mean_m) ** 2 for _, b in pairs)
                if var > 0:
                    betas[d].append((cov / var, symbol, fill))
    return betas, maxes


def illiquid_ranks(snaps: six.Snaps) -> Ranked:
    """H-0085: 20-session mean traded value, with the 14:41 fill."""
    out: Ranked = defaultdict(list)
    for symbol, days in snaps.items():
        ordered = sorted(days)
        for i in range(VALUE_DAYS, len(ordered)):
            s = days[ordered[i]]
            fill = six._from(s, LATE_MINUTE)
            if fill is None or s.closes[six._k(LATE_MINUTE)] < cs.MIN_PRICE:
                continue
            value = sum(days[x].value for x in ordered[i - VALUE_DAYS : i]) / VALUE_DAYS
            out[ordered[i]].append((value, symbol, fill))
    return out


# --- the F&O bhavcopy, reduced ---------------------------------------------------------


def reduce_bhavcopy(payload: bytes, day: str) -> FoDay:
    """Each stock's total futures OI and its nearest option expiry's largest-OI strike."""
    from eulerlab.master.derivatives import ContractType, parse_legacy_row, parse_udiff_row
    from eulerlab.options.chain import OI_FIELDS, _number
    from eulerlab.options.nifty_history import _rows

    futures: dict[str, float] = defaultdict(float)
    strikes: dict[str, dict[date, dict[float, float]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(float))
    )
    today = date.fromisoformat(day)
    for row in _rows(payload):
        contract = parse_udiff_row(row) or parse_legacy_row(row)
        if contract is None or contract.expiry < today:
            continue
        oi = _number(row, OI_FIELDS) or 0.0
        if contract.contract_type is ContractType.FUTURE:
            futures[contract.underlying] += oi
        elif contract.contract_type is ContractType.OPTION and contract.strike is not None:
            strikes[contract.underlying][contract.expiry][float(contract.strike)] += oi
    pins = {}
    for symbol, by_expiry in strikes.items():
        nearest = min(by_expiry)
        strike, oi = max(by_expiry[nearest].items(), key=lambda item: (item[1], -item[0]))
        if oi > 0:
            pins[symbol] = [nearest.isoformat(), strike, oi]
    return {"d": day, "oi": dict(futures), "pin": pins}


def build_fo_daily(path: Path = FO_DAILY, *, workers: int = 4) -> None:
    """Resumable: a day already in the file is not read again."""
    from eulerlab.ingest import landing_reader

    have = {json.loads(line)["d"] for line in path.open()} if path.exists() else set()
    entries = {}
    for line in data_path("landing/nse/manifest.jsonl").read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry.get("segment") != "fo":
            continue
        day = entry["path"].rsplit("/", 1)[-1].split("_")[0]
        if FO_FROM <= day <= cs.DATA_END.isoformat() and day not in have:
            entries[day] = f"nse/{entry['path']}"

    def fetch(day: str) -> FoDay:
        return reduce_bhavcopy(landing_reader.read(entries[day], cache=False), day)

    path.parent.mkdir(parents=True, exist_ok=True)
    with cf.ThreadPoolExecutor(workers) as pool, path.open("a", encoding="utf-8") as out:
        for done, reduced in enumerate(pool.map(fetch, sorted(entries)), start=1):
            out.write(json.dumps(reduced, separators=(",", ":")) + "\n")
            out.flush()
            if done % 100 == 0:
                print(f"  F&O {done}/{len(entries)}", flush=True)


def load_fo_daily(path: Path = FO_DAILY) -> dict[date, FoDay]:
    out = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            out[date.fromisoformat(row["d"])] = row
    return out


# --- H-0086 pinning and H-0087 build-up ------------------------------------------------


def pin_trades(snaps: six.Snaps, fo: Mapping[date, FoDay]) -> Fills:
    sessions = sorted(fo)
    previous = dict(zip(sessions[1:], sessions, strict=False))
    k = six._k(PIN_MINUTE)
    by_day: dict[date, list[tuple[float, str, five.Fill]]] = defaultdict(list)
    for symbol, days in snaps.items():
        for d, s in days.items():
            before = previous.get(d)
            pin = fo[before]["pin"].get(symbol) if before is not None else None
            if pin is None or date.fromisoformat(pin[0]) != d:
                continue
            close = s.closes[k]
            gap = pin[1] / close - 1.0
            if close < cs.MIN_PRICE or not PIN_NEAR <= abs(gap) <= PIN_FAR:
                continue
            fill = six._from(s, PIN_MINUTE, 1 if gap > 0 else -1)
            if fill is not None:
                by_day[d].append((abs(gap), symbol, fill))
    out: Fills = []
    for d, found in by_day.items():
        found.sort(key=lambda item: (item[0], item[1]))
        out.extend((d, symbol, fill) for _, symbol, fill in found[: five.MAX_OPEN])
    return out


def build_up_trades(snaps: six.Snaps, fo: Mapping[date, FoDay]) -> Fills:
    sessions = sorted(fo)
    previous = dict(zip(sessions[1:], sessions, strict=False))
    by_day: dict[date, list[tuple[float, str, five.Fill]]] = defaultdict(list)
    for symbol, days in snaps.items():
        ordered = sorted(days)
        for i in range(2, len(ordered)):
            d, yesterday, before = ordered[i], ordered[i - 1], ordered[i - 2]
            if previous.get(yesterday) != before or (d - yesterday).days > 7:
                continue
            oi_then = fo[before]["oi"].get(symbol, 0.0)
            oi_now = fo[yesterday]["oi"].get(symbol, 0.0)
            if oi_then <= 0 or oi_now / oi_then - 1.0 < BUILD_OI:
                continue
            move = days[yesterday].last_close / days[before].last_close - 1.0
            if abs(move) < BUILD_RETURN or abs(move) > MAX_RETURN:
                continue
            s = days[d]
            if s.entry < cs.MIN_PRICE:
                continue
            direction = 1 if move > 0 else -1
            fill = five.Fill(
                six.DAY_START, direction, s.entry_minute, s.entry, s.exit_minute, s.exit
            )
            by_day[d].append((-(oi_now / oi_then), symbol, fill))
    out: Fills = []
    for d, found in by_day.items():
        found.sort(key=lambda item: (item[0], item[1]))
        out.extend((d, symbol, fill) for _, symbol, fill in found[: five.MAX_OPEN])
    return out


# --- running ---------------------------------------------------------------------------


def load_snaps() -> tuple[dict[str, dict[date, six.Snap]], list[date]]:
    parts = sorted(six.PARTS.glob("*.pkl"))
    if not parts:
        raise SystemExit("no minute_six_parts: run `make minute-six` first")
    snaps: dict[str, dict[date, six.Snap]] = {}
    sessions: set[date] = set()
    for part in parts:
        loaded = pickle.loads(part.read_bytes())
        snaps.update(loaded["snaps"])
        sessions.update(loaded["sessions"])
    return snaps, sorted(d for d in sessions if d <= cs.DATA_END)


def run(output: Path = OUT) -> dict[str, Any]:
    build_fo_daily()
    snaps, window = load_snaps()
    fo = load_fo_daily()
    betas, maxes = beta_and_max(snaps, nifty_returns(five.load_index()))
    capital = five.TRADE * five.MAX_OPEN
    runs = [
        {
            "hypothesis": "H-0083",
            **sig._deciles("nse_beta_daytime", betas, window, top_direction=-1),
        },
        {
            "hypothesis": "H-0084",
            **sig._deciles("nse_max_daytime", maxes, window, top_direction=-1),
        },
        {
            "hypothesis": "H-0085",
            **sig._deciles(
                "nse_illiquid_last_half_hour", illiquid_ranks(snaps), window, top_direction=-1
            ),
        },
        {
            "hypothesis": "H-0086",
            **six.evaluate("nse_stock_option_pinning", pin_trades(snaps, fo), window, capital),
        },
        {
            "hypothesis": "H-0087",
            **six.evaluate("nse_futures_oi_build_up", build_up_trades(snaps, fo), window, capital),
        },
    ]
    result = {
        "research": "docs/RESEARCH/162-beta-max-illiquidity-pinning-oi.md",
        "universe": len(snaps),
        "fo_days": len(fo),
        "spent_trials": 0,
        "runs": runs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="stock-fo")
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
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
