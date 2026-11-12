"""Short at-the-money index straddles inside one session (research 166).

Four pre-registered rules, all sold at the F&O bhavcopy OPEN and closed the
same day:

- **H-0041** Nifty, on weekly expiry day, held to settlement (research 153).
- **H-0103** BankNifty, on expiry day, held to settlement.
- **H-0104** FinNifty, on expiry day, held to settlement.
- **H-0105** Nifty, on the session *before* expiry: the expiring call and put
  are bought back at their bhavcopy CLOSE.

The strike is the index open rounded to the underlying's step. Settlement is
intrinsic value at the index close (A-109, A-116). Each leg pays 1 index point
of slippage a side. P&L is per unit of index and sized to ₹10 lakh of notional
in continuous units (S-039), so no lot size is needed.

One pass over every F&O bhavcopy from 2019-02 to 2024-11 keeps, per day and
underlying, the nearest expiry's options in
`data/derived/index_expiry_options.jsonl` (resumable, one line a day).
`make index-expiry` writes `data/derived/index_expiry.json`.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import Any

from eulerlab.costs.schedule import Segment, Side
from eulerlab.intraday import cross_section as cs
from eulerlab.master.derivatives import ContractType, parse_legacy_row, parse_udiff_row
from eulerlab.options import nifty_history
from eulerlab.options.chain import CLOSE_FIELDS, OPEN_FIELDS, VOLUME_FIELDS, _number
from eulerlab.options.strategies import _cost
from eulerlab.paths import data_path

DAYS = data_path("derived/index_expiry_options.jsonl")
OUT = data_path("derived/index_expiry.json")
INDEX = data_path("derived/index_history.jsonl")
FIRST = date(2019, 2, 1)
END = date(2024, 11, 30)
"""The minute research window's end, as H-0041; the holdout starts after it."""
SLIPPAGE_POINTS = 1.0
NOTIONAL = 1_000_000.0

UNDERLYINGS: dict[str, tuple[str, int]] = {
    "NIFTY": ("Nifty 50", 50),
    "BANKNIFTY": ("Nifty Bank", 100),
    "FINNIFTY": ("Nifty Financial Services", 50),
}
"""Underlying -> (its index in `index_history`, strike step)."""


@dataclass(frozen=True)
class Rule:
    hypothesis: str
    run_id: str
    underlying: str
    kind: str
    """`expiry`: sell on expiry day, settle. `day_before`: sell and buy back the session before."""
    start: date
    end: date


RULES: tuple[Rule, ...] = (
    Rule(
        "H-0041",
        "nifty_expiry_day_short_straddle",
        "NIFTY",
        "expiry",
        date(2019, 2, 14),
        date(2024, 11, 28),
    ),
    Rule(
        "H-0103",
        "banknifty_expiry_day_short_straddle",
        "BANKNIFTY",
        "expiry",
        date(2019, 2, 14),
        date(2024, 11, 28),
    ),
    Rule(
        "H-0104",
        "finnifty_expiry_day_short_straddle",
        "FINNIFTY",
        "expiry",
        date(2021, 1, 11),
        date(2024, 11, 28),
    ),
    Rule(
        "H-0105",
        "nifty_day_before_expiry_short_straddle",
        "NIFTY",
        "day_before",
        date(2019, 2, 13),
        date(2024, 11, 27),
    ),
)
BY_ID = {rule.hypothesis: rule for rule in RULES}


# --- one pass over the bhavcopies ------------------------------------------------------


def extract(payload: bytes, day: str) -> dict[str, Any]:
    """Per underlying, the nearest expiry on or after `day` and its options:
    [strike, right, open, close, volume]; open and close only where it traded."""
    found: dict[str, dict[str, list[list[Any]]]] = {u: {} for u in UNDERLYINGS}
    for row in nifty_history._rows(payload):
        contract = parse_udiff_row(row) or parse_legacy_row(row)
        if (
            contract is None
            or contract.underlying not in UNDERLYINGS
            or contract.contract_type is not ContractType.OPTION
            or contract.strike is None
            or contract.expiry.isoformat() < day
        ):
            continue
        volume = _number(row, VOLUME_FIELDS) or 0.0
        opened = _number(row, OPEN_FIELDS) if volume > 0 else None
        closed = _number(row, CLOSE_FIELDS) if volume > 0 else None
        right = contract.right.value if contract.right else ""
        found[contract.underlying].setdefault(contract.expiry.isoformat(), []).append(
            [float(contract.strike), right, opened, closed, volume]
        )
    out: dict[str, Any] = {"d": day, "u": {}}
    for underlying, by_expiry in found.items():
        if by_expiry:
            nearest = min(by_expiry)
            out["u"][underlying] = {"e": nearest, "opt": sorted(by_expiry[nearest])}
    return out


def fetch_days(path: Path = DAYS, workers: int = 8) -> int:
    """Read each missing trading day's bhavcopy once; returns the days that failed."""
    from eulerlab.ingest import landing_reader

    have: set[str] = set()
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            have = {json.loads(line)["d"] for line in handle if line.strip()}
    by_day = nifty_history.archives(landing_reader.available)
    todo = [
        d for d in sorted(by_day) if FIRST.isoformat() <= d <= END.isoformat() and d not in have
    ]

    def fetch(day: str) -> tuple[str, bytes | None]:
        try:
            return day, landing_reader.read(by_day[day], cache=False)
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


def load_days(path: Path = DAYS) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    return sorted(rows, key=lambda r: r["d"])


def index_days(name: str, path: Path = INDEX) -> dict[date, tuple[float, float]]:
    """{day: (open, close)} of one index."""
    out = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            bar = row["indices"].get(name) or {}
            if bar.get("o") and bar.get("c"):
                out[date.fromisoformat(row["d"])] = (float(bar["o"]), float(bar["c"]))
    return out


# --- the trade -------------------------------------------------------------------------


@dataclass(frozen=True)
class Trade:
    """A short straddle opened and closed in one session.

    `symbol` and `day` let the validation battery (ADR-139) read it as it reads
    a stock trade; `gross` and `costs` are rupees.
    """

    symbol: str
    day: date
    strike: float
    call_open: float
    put_open: float
    call_exit: float
    put_exit: float
    units: float
    settled: bool
    """True: exit is intrinsic value at settlement (no fill, no charge). False: bought back."""

    @property
    def gross(self) -> float:
        return (self.call_open + self.put_open - self.call_exit - self.put_exit) * self.units

    @property
    def costs(self) -> float:
        legs = 2 if self.settled else 4
        slippage = legs * SLIPPAGE_POINTS * self.units
        charges = sum(
            _cost(self.day, Segment.OPTIONS, Side.SELL, price, self.units)
            for price in (self.call_open, self.put_open)
        )
        if not self.settled:
            charges += sum(
                _cost(self.day, Segment.OPTIONS, Side.BUY, price, self.units)
                for price in (self.call_exit, self.put_exit)
            )
        return slippage + charges


def trades(
    rule: Rule, days: Sequence[Mapping[str, Any]], index: Mapping[date, tuple[float, float]]
) -> tuple[list[Trade], list[str]]:
    """One trade per qualifying day; the reasons for every qualifying day skipped."""
    _, step = UNDERLYINGS[rule.underlying]
    sessions = [r["d"] for r in days]
    nxt = dict(pairwise(sessions))
    out: list[Trade] = []
    skipped: list[str] = []
    for row in days:
        day = date.fromisoformat(row["d"])
        if not rule.start <= day <= rule.end:
            continue
        chain = row["u"].get(rule.underlying)
        if chain is None:
            continue
        expiry = chain["e"]
        if rule.kind == "expiry" and expiry != row["d"]:
            continue
        if rule.kind == "day_before" and expiry != nxt.get(row["d"]):
            continue
        if day not in index:
            skipped.append(f"{day}: no index open")
            continue
        opened, closed = index[day]
        strike = round(opened / step) * step
        legs = {(k, right): (o, c) for k, right, o, c, _ in chain["opt"] if k == strike}
        call, put = legs.get((strike, "CE")), legs.get((strike, "PE"))
        if not call or not put or not call[0] or not put[0]:
            skipped.append(f"{day}: strike {strike:.0f} call or put did not trade")
            continue
        units = NOTIONAL / opened
        if rule.kind == "expiry":
            # ASSUMPTION A-109 / A-116: settles at intrinsic value on the index close.
            out.append(
                Trade(
                    rule.underlying,
                    day,
                    float(strike),
                    call[0],
                    put[0],
                    max(closed - strike, 0.0),
                    max(strike - closed, 0.0),
                    units,
                    True,
                )
            )
        else:
            if not call[1] or not put[1]:
                skipped.append(f"{day}: strike {strike:.0f} has no close")
                continue
            out.append(
                Trade(
                    rule.underlying,
                    day,
                    float(strike),
                    call[0],
                    put[0],
                    call[1],
                    put[1],
                    units,
                    False,
                )
            )
    return out, skipped


def sessions_for(rule: Rule, days: Sequence[Mapping[str, Any]]) -> list[date]:
    """Every trading day in the rule's window: a day it did not trade is a zero return."""
    return [d for r in days if rule.start <= (d := date.fromisoformat(r["d"])) <= rule.end]


def evaluate(rule: Rule, days: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    name, step = UNDERLYINGS[rule.underlying]
    book, skipped = trades(rule, days, index_days(name))
    sessions = sessions_for(rule, days)
    run = cs.report(
        rule.run_id,
        [_as_stock_shape(t) for t in book],
        sessions,
        params={
            "underlying": rule.underlying,
            "kind": rule.kind,
            "strike": f"{name} open rounded to {step}",
            "slippage_points_a_leg_a_side": SLIPPAGE_POINTS,
            "notional": NOTIONAL,
        },
        capital=NOTIONAL,
    )
    net = sorted(((t.gross - t.costs) / NOTIONAL * 10_000, t) for t in book)[:5]
    run["hypothesis"] = rule.hypothesis
    run["spent_trials"] = 0
    run["per_trade_bps"] = _per_trade(book)
    run["worst_days"] = [
        {"day": t.day.isoformat(), "net_bps_of_notional": round(n, 1)} for n, t in net
    ]
    run["skipped"] = skipped
    run["halves"] = _halves(book, sessions)
    run.pop("trade_log", None)
    return run


def _per_trade(book: Sequence[Trade]) -> dict[str, Any]:
    if not book:
        return {}
    gross = [t.gross / NOTIONAL * 10_000 for t in book]
    net = [(t.gross - t.costs) / NOTIONAL * 10_000 for t in book]
    return {
        "gross_mean": round(sum(gross) / len(gross), 2),
        "net_mean": round(sum(net) / len(net), 2),
        "net_win_rate": round(sum(1 for x in net if x > 0) / len(net), 4),
    }


def _halves(book: Sequence[Trade], sessions: Sequence[date]) -> dict[str, float]:
    """Net bps of notional summed over each half of the sessions, split at the midpoint."""
    if not sessions:
        return {}
    middle = sessions[len(sessions) // 2]
    first = sum(t.gross - t.costs for t in book if t.day < middle) / NOTIONAL * 10_000
    second = sum(t.gross - t.costs for t in book if t.day >= middle) / NOTIONAL * 10_000
    return {"first_net_bps_total": round(first, 1), "second_net_bps_total": round(second, 1)}


class _Shaped:
    """A straddle seen through `cs.report`'s eyes: gross, costs, notional, day."""

    def __init__(self, trade: Trade) -> None:
        self.symbol = trade.symbol
        self.day = trade.day
        self.gross = trade.gross
        self.costs = trade.costs
        self.notional = NOTIONAL
        self.direction = -1
        self.quantity = 0
        self.entry_minute = 0
        self.entry = trade.call_open + trade.put_open
        self.exit_minute = 374
        self.exit = trade.call_exit + trade.put_exit
        self.reason = "settle" if trade.settled else "close"


def _as_stock_shape(trade: Trade) -> Any:
    return _Shaped(trade)


def validation_run(hypothesis: str) -> Any:
    """The rule's trades for the validation battery (ADR-139). No late-entry stress:
    the bhavcopy holds one opening price per contract."""
    from eulerlab.validation.intraday import IntradayRun

    rule = BY_ID[hypothesis]
    days = load_days()
    name, _ = UNDERLYINGS[rule.underlying]
    book, _ = trades(rule, days, index_days(name))
    return IntradayRun(book, [], sessions_for(rule, days), NOTIONAL)


def run(output: Path = OUT) -> dict[str, Any]:
    failed = fetch_days()
    if failed:
        msg = f"{failed} days could not be read; run again to retry"
        raise RuntimeError(msg)
    days = load_days()
    result = {"research": "166", "runs": [evaluate(rule, days) for rule in RULES]}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="index-expiry")
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    for r in run(args.output)["runs"]:
        print(
            f"{r['hypothesis']} {r['id']}: {r['trades']} trades; gross "
            f"{r['per_trade_bps'].get('gross_mean')} bps, net {r['per_trade_bps'].get('net_mean')} "
            f"bps of notional a trade; net Sharpe {r['net'].get('sharpe')}; halves {r['halves']}"
        )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
