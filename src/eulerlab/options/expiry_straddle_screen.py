"""Sell the at-the-money Nifty straddle at the open on expiry day (research 153, H-0041).

Same-day options price more movement than the index delivers on average
(FlashAlpha, 193 SPY sessions); the trade is the variance premium collected in
one session. Fixed rule: on each weekly Nifty expiry day from 2019-02-14 to
2024-11-28, take the strike nearest the Nifty 50 open (a multiple of 50), sell
its call and put at their opening prices less 1 index point each, and hold to
settlement. No stop, no hedge.

`nifty_options.jsonl` keeps no opening prices, so the expiring contracts'
OPEN is read once from each expiry day's F&O bhavcopy into
`data/derived/nifty_expiry_day_options.jsonl` (resumable, one line a day).
Settlement is the intrinsic value at the Nifty 50 close: index options settle
on the closing index value of expiry day (A-109).

P&L is per unit of Nifty and sized to ₹10 lakh of notional in continuous units
(S-039), so no lot size is needed. A short leg is assigned, not exercised, and
pays no exercise STT. `make expiry-straddle` writes
`data/derived/expiry_straddle.json`.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import math
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from eulerlab.costs.schedule import Segment, Side
from eulerlab.master.derivatives import ContractType, parse_legacy_row, parse_udiff_row
from eulerlab.options import nifty_history
from eulerlab.options.chain import CLOSE_FIELDS, OPEN_FIELDS, VOLUME_FIELDS, _number
from eulerlab.options.strategies import _cost
from eulerlab.paths import data_path

RUN_ID = "nifty_expiry_day_short_straddle"
DAYS = data_path("derived/nifty_expiry_day_options.jsonl")
OUT = data_path("derived/expiry_straddle.json")
INDEX = data_path("derived/index_history.jsonl")
START = date(2019, 2, 14)
"""The first weekly Nifty expiry."""
END = date(2024, 11, 30)
"""The minute research window's end; the same cut keeps the two screens comparable."""
STEP = 50
SLIPPAGE_POINTS = 1.0
NOTIONAL = 1_000_000.0
WEEKS_A_YEAR = 52


def expiry_days(path: Path = nifty_history.OUT) -> list[date]:
    """Days on which some Nifty option expired, from the daily options file."""
    out = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            day = date.fromisoformat(row["d"])
            if START <= day <= END and any(opt[0] == row["d"] for opt in row["opt"]):
                out.append(day)
    return sorted(out)


def extract(payload: bytes, day: str) -> dict[str, Any]:
    """The Nifty options expiring on `day`: [strike, right, open, close, volume]."""
    options: list[list[Any]] = []
    for row in nifty_history._rows(payload):
        contract = parse_udiff_row(row) or parse_legacy_row(row)
        if (
            contract is None
            or contract.underlying != nifty_history.UNDERLYING
            or contract.contract_type is not ContractType.OPTION
            or contract.strike is None
            or contract.expiry.isoformat() != day
        ):
            continue
        volume = _number(row, VOLUME_FIELDS) or 0.0
        opened = _number(row, OPEN_FIELDS) if volume > 0 else None
        closed = _number(row, CLOSE_FIELDS) if volume > 0 else None
        right = contract.right.value if contract.right else ""
        options.append([float(contract.strike), right, opened, closed, volume])
    options.sort()
    return {"d": day, "opt": options}


def index_days(path: Path = INDEX) -> dict[date, tuple[float, float]]:
    """{day: (Nifty 50 open, close)}."""
    out = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            nifty = row["indices"].get("Nifty 50") or {}
            if nifty.get("o") and nifty.get("c"):
                out[date.fromisoformat(row["d"])] = (float(nifty["o"]), float(nifty["c"]))
    return out


@dataclass(frozen=True)
class Trade:
    day: date
    strike: float
    call_open: float
    put_open: float
    settle: float
    units: float

    @property
    def premium(self) -> float:
        return self.call_open + self.put_open - 2 * SLIPPAGE_POINTS

    @property
    def payout(self) -> float:
        # ASSUMPTION A-109: index options settle on the Nifty 50 close of expiry day.
        return max(self.settle - self.strike, 0.0) + max(self.strike - self.settle, 0.0)

    @property
    def gross(self) -> float:
        """Rupees, before charges: premium received less what settlement pays out."""
        return (self.call_open + self.put_open - self.payout) * self.units

    @property
    def costs(self) -> float:
        slippage = 2 * SLIPPAGE_POINTS * self.units
        charges = sum(
            _cost(self.day, Segment.OPTIONS, Side.SELL, price, self.units)
            for price in (self.call_open, self.put_open)
        )
        return slippage + charges


def trades(
    days: Iterable[Mapping[str, Any]], index: Mapping[date, tuple[float, float]]
) -> tuple[list[Trade], list[str]]:
    """One trade per expiry day; the reasons for every day skipped."""
    out: list[Trade] = []
    skipped: list[str] = []
    for row in days:
        day = date.fromisoformat(row["d"])
        if day not in index:
            skipped.append(f"{day}: no Nifty 50 open")
            continue
        opened, closed = index[day]
        strike = round(opened / STEP) * STEP
        legs = {
            (strike_, right): open_
            for strike_, right, open_, _, _ in row["opt"]
            if strike_ == strike and open_
        }
        call, put = legs.get((strike, "CE")), legs.get((strike, "PE"))
        if not call or not put:
            skipped.append(f"{day}: strike {strike:.0f} call or put did not trade")
            continue
        out.append(Trade(day, float(strike), call, put, closed, NOTIONAL / opened))
    return out, skipped


def _stats(pnl: Sequence[float]) -> dict[str, Any]:
    if not pnl:
        return {"trades": 0}
    mean = statistics.fmean(pnl)
    sd = statistics.stdev(pnl) if len(pnl) > 1 else 0.0
    equity, peak, drawdown = 0.0, 0.0, 0.0
    for value in pnl:
        equity += value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    return {
        "trades": len(pnl),
        "total_return": round(sum(pnl) / NOTIONAL, 6),
        "mean_bps_of_notional": round(mean / NOTIONAL * 10_000, 2),
        "sharpe": round(mean / sd * math.sqrt(WEEKS_A_YEAR), 3) if sd else None,
        "win_rate": round(sum(1 for x in pnl if x > 0) / len(pnl), 4),
        "worst_trade_bps": round(min(pnl) / NOTIONAL * 10_000, 1),
        "best_trade_bps": round(max(pnl) / NOTIONAL * 10_000, 1),
        "max_drawdown_of_notional": round(drawdown / NOTIONAL, 4),
    }


def evaluate(book: Sequence[Trade], skipped: Sequence[str]) -> dict[str, Any]:
    gross = [t.gross for t in book]
    net = [t.gross - t.costs for t in book]
    halves = {
        "before_2024": [n for t, n in zip(book, net, strict=True) if t.day.year < 2024],
        "2024": [n for t, n in zip(book, net, strict=True) if t.day.year >= 2024],
    }
    worst = sorted(zip(net, book, strict=True), key=lambda item: item[0])[:5]
    return {
        "id": RUN_ID,
        "hypothesis": "H-0041",
        "research": "docs/RESEARCH/153-day-trading-candidates-india.md",
        "params": {
            "strike": f"Nifty 50 open rounded to {STEP}",
            "entry": f"each leg's bhavcopy OPEN, less {SLIPPAGE_POINTS} point",
            "exit": "intrinsic value at the Nifty 50 close (settlement)",
            "sizing": f"₹{NOTIONAL:,.0f} of Nifty notional, continuous units",
        },
        "window": [book[0].day.isoformat(), book[-1].day.isoformat()] if book else [],
        "spent_trials": 0,
        "gross": _stats(gross),
        "net": _stats(net),
        "net_halves": {name: _stats(values) for name, values in halves.items()},
        "mean_premium_points": round(statistics.fmean(t.premium for t in book), 2)
        if book
        else None,
        "mean_payout_points": round(statistics.fmean(t.payout for t in book), 2) if book else None,
        "worst_days": [
            {
                "day": t.day.isoformat(),
                "net_bps": round(n / NOTIONAL * 10_000, 1),
                "premium": round(t.call_open + t.put_open, 2),
                "move": round(t.settle - t.strike, 2),
            }
            for n, t in worst
        ],
        "skipped": list(skipped),
        "estimated_costs_rupees": round(sum(t.costs for t in book), 2),
    }


def fetch_days(days: Sequence[date], path: Path = DAYS, workers: int = 4) -> int:
    """Read each missing expiry day's bhavcopy once; returns the days that failed."""
    import boto3

    from eulerlab.env import require
    from eulerlab.ingest import landing_reader

    have = set()
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            have = {json.loads(line)["d"] for line in handle}
    by_day = nifty_history.archives(landing_reader.available)
    todo = [d.isoformat() for d in days if d.isoformat() not in have]
    client = boto3.client(
        "s3",
        endpoint_url="https://s3.us-west-004.backblazeb2.com",
        aws_access_key_id=require("B2_KEY_ID"),
        aws_secret_access_key=require("B2_APP_KEY"),
    )

    def fetch(day: str) -> tuple[str, bytes | None]:
        archive = by_day.get(day)
        if archive is None:
            return day, None
        local = landing_reader.LANDING_ROOT / archive
        try:
            if local.exists():
                return day, local.read_bytes()
            return day, client.get_object(Bucket="eulerdata", Key=f"nse/{archive}")["Body"].read()
        except Exception:  # one bad day must not stop the run; re-run to retry
            return day, None

    failed = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with cf.ThreadPoolExecutor(max_workers=workers) as pool, path.open("a") as out:
        for day, payload in pool.map(fetch, todo):
            if payload is None:
                failed += 1
                continue
            out.write(json.dumps(extract(payload, day), separators=(",", ":")) + "\n")
            out.flush()
    return failed


def run(output: Path = OUT) -> dict[str, Any]:
    days = expiry_days()
    failed = fetch_days(days)
    if failed:
        msg = f"{failed} expiry days could not be read; run again to retry"
        raise RuntimeError(msg)
    with DAYS.open(encoding="utf-8") as handle:
        rows = sorted((json.loads(line) for line in handle), key=lambda r: r["d"])
    rows = [r for r in rows if START.isoformat() <= r["d"] <= END.isoformat()]
    book, skipped = trades(rows, index_days())
    result = evaluate(book, skipped)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="expiry-straddle")
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    result = run(args.output)
    gross, net = result["gross"], result["net"]
    print(
        f"{result['id']}: {net['trades']} expiries; gross {gross['mean_bps_of_notional']} bps "
        f"a trade, net {net['mean_bps_of_notional']} (Sharpe {net['sharpe']}); worst "
        f"{net['worst_trade_bps']} bps; drawdown {net['max_drawdown_of_notional']:.1%}"
    )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
