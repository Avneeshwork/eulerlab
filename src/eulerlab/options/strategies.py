"""Two Indian index-options strategies, on daily Nifty data. Research 070.

1. **Monthly short strangle** — Bangur (2020), *Journal of Investment
   Strategies*: on the first session after each monthly expiry, sell one
   out-of-the-money call and one out-of-the-money put of the next monthly
   expiry, and hold to expiry. Three strike distances ("legs").
2. **Covered call** — Aggarwal (2011), *Asia-Pacific Business Review*: hold
   the index and sell a call 5% in the money. The paper re-opens both every
   day at the close and squares off at the next close; a monthly-hold version
   is run beside it.

### What is assumed, and where

Bangur's legs are not defined in the abstract, the only part readable. Here
leg *k* sells the call and the put *k* x 2% out of the money, at the nearest
100-point strike. A fixed number of points would mean very different distances
in 2015 (Nifty 8,000) and 2026 (Nifty 25,000). ASSUMPTION A-049.

The index cannot be bought. The covered call's long leg is the near-month Nifty
future, rolled to the next month when it expires.

Prices: a trade fills at the contract's **close** when it traded that day and
is skipped when it did not. An option held to expiry is settled at intrinsic
value against the Nifty close on expiry day, which is how NSE cash-settles it.

**Sizing without lot sizes.** The bhavcopy carries lot sizes only from 2024,
and `CLAUDE.md` forbids hardcoding them. So a strategy holds `units` of the
index (a continuous number) sized from the capital: the strangle's capital is
the margin a broker would block, ASSUMPTION A-050 (15% of notional per sold
leg pair), and the covered call's is the full notional. Costs are charged on
those units through `costs.model` — STT on premium and on in-the-money
expiry, stamp, exchange, SEBI, GST, ₹20 per order. STUB S-039: no lot rounding.
"""

from __future__ import annotations

import json
import math
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any

from eulerlab.costs.model import cost_of_exercise, cost_of_trade
from eulerlab.costs.schedule import Segment, Side
from eulerlab.paths import data_path

STEP = 100.0
"""Strikes are taken at 100-point multiples, listed throughout 2015-2026."""

LEG_DISTANCE = 0.02
"""Each leg is this much further out of the money (A-049)."""

STRANGLE_MARGIN = 0.15
"""ASSUMPTION A-050: cash blocked to sell one call and one put, as a share of
the notional of one leg. SPAN plus exposure margin on a short Nifty strangle
has run at roughly 12-18% of notional; not measured here."""

EXPIRIES = data_path("derived/nifty_expiries.json")
INDEX_HISTORY = data_path("derived/index_history.jsonl")


@dataclass
class Day:
    day: date
    spot: float
    futures: dict[date, float]  # expiry -> traded close
    calls: dict[tuple[date, float], float]  # (expiry, strike) -> traded close
    puts: dict[tuple[date, float], float]


def load_spot(path: Path = INDEX_HISTORY) -> dict[date, float]:
    out: dict[date, float] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            nifty = (row.get("indices") or {}).get("Nifty 50")
            if nifty and nifty.get("c"):
                out[date.fromisoformat(row["d"])] = float(nifty["c"])
    return out


def load_days(raw: list[dict[str, Any]], spot: dict[date, float]) -> list[Day]:
    days = []
    for item in raw:
        d = date.fromisoformat(item["d"])
        if d not in spot:
            continue
        futures = {date.fromisoformat(f[0]): f[1] for f in item["fut"] if f[1]}
        calls: dict[tuple[date, float], float] = {}
        puts: dict[tuple[date, float], float] = {}
        for expiry, strike, right, close, _settle, volume, *_ in item["opt"]:
            if not close or volume <= 0:
                continue
            key = (date.fromisoformat(expiry), float(strike))
            (calls if right == "CE" else puts)[key] = float(close)
        days.append(Day(d, spot[d], futures, calls, puts))
    return days


def monthly_expiries(path: Path = EXPIRIES) -> list[date]:
    return sorted(date.fromisoformat(e) for e in json.loads(path.read_text())["expiries"])


# --- costs ------------------------------------------------------------------


def _cost(day: date, segment: Segment, side: Side, price: float, units: float) -> float:
    """One order. `units` is continuous (S-039); the charge is computed on a
    whole-number quantity scaled back, so ₹20 brokerage stays per order."""
    q = max(1, round(units))
    c = cost_of_trade(
        trade_date=day, segment=segment, side=side, price=Decimal(str(price)), quantity=q
    )
    total = float(c.total)
    flat = float(c.brokerage) * 1.18  # brokerage and its GST are per order
    return flat + (total - flat) * units / q


def _exercise_cost(day: date, settle: float, strike: float, units: float, *, call: bool) -> float:
    q = max(1, round(units))
    c = cost_of_exercise(
        trade_date=day,
        settlement_price=Decimal(str(settle)),
        strike=Decimal(str(strike)),
        quantity=q,
        is_call=call,
    )
    return float(c.total) * units / q


# --- results ----------------------------------------------------------------


@dataclass
class Period:
    start: date
    end: date
    pnl: float
    capital: float
    costs: float
    note: str = ""

    @property
    def ret(self) -> float:
        return self.pnl / self.capital if self.capital else 0.0


@dataclass
class Result:
    name: str
    periods: list[Period] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    periods_per_year: float = 12.0

    def stats(self, start: date | None = None, end: date | None = None) -> dict[str, float]:
        rs = [
            p.ret
            for p in self.periods
            if (not start or p.end >= start) and (not end or p.end < end)
        ]
        n = len(rs)
        if n < 2:
            return {"periods": n}
        mean = sum(rs) / n
        sd = math.sqrt(sum((r - mean) ** 2 for r in rs) / (n - 1))
        level, peak, worst = 1.0, 1.0, 0.0
        for r in rs:
            level *= 1 + r
            peak = max(peak, level)
            worst = min(worst, level / peak - 1)
        years = n / self.periods_per_year
        return {
            "periods": n,
            "sharpe": round(mean / sd * math.sqrt(self.periods_per_year), 3) if sd else 0.0,
            "total_return": round(level - 1, 4),
            "cagr": round(level ** (1 / years) - 1, 4) if level > 0 and years else -1.0,
            "max_drawdown": round(worst, 4),
            "win_rate": round(sum(1 for r in rs if r > 0) / n, 3),
            "worst_period": round(min(rs), 4),
            "costs_share": round(
                sum(p.costs for p in self.periods)
                / max(1e-9, sum(abs(p.pnl) for p in self.periods)),
                4,
            ),
        }


# --- 1. monthly short strangle ------------------------------------------------


def short_strangle(days: list[Day], expiries: list[date], *, leg: int, capital: float) -> Result:
    result = Result(f"short_strangle_leg{leg}")
    by_day = {d.day: d for d in days}
    dates = [d.day for d in days]
    usable = [e for e in expiries if dates[0] <= e <= dates[-1]]
    for prev, expiry in pairwise(usable):
        i = bisect_right(dates, prev)
        if i >= len(dates) or dates[i] >= expiry or expiry not in by_day:
            continue
        entry = days[i]
        call_k = round(entry.spot * (1 + LEG_DISTANCE * leg) / STEP) * STEP
        put_k = round(entry.spot * (1 - LEG_DISTANCE * leg) / STEP) * STEP
        call = entry.calls.get((expiry, call_k))
        put = entry.puts.get((expiry, put_k))
        if call is None or put is None:
            result.skipped.append(f"{entry.day}: {call_k:.0f}CE or {put_k:.0f}PE did not trade")
            continue
        margin = STRANGLE_MARGIN * entry.spot
        units = capital / margin
        settle = by_day[expiry].spot
        intrinsic = max(settle - call_k, 0.0) + max(put_k - settle, 0.0)
        costs = (
            _cost(entry.day, Segment.OPTIONS, Side.SELL, call, units)
            + _cost(entry.day, Segment.OPTIONS, Side.SELL, put, units)
            + (_exercise_cost(expiry, settle, call_k, units, call=True) if settle > call_k else 0.0)
            + (_exercise_cost(expiry, settle, put_k, units, call=False) if settle < put_k else 0.0)
        )
        pnl = (call + put - intrinsic) * units - costs
        result.periods.append(
            Period(
                entry.day,
                expiry,
                pnl,
                capital,
                costs,
                f"{put_k:.0f}PE/{call_k:.0f}CE @ {settle:.0f}",
            )
        )
    return result


# --- 2. covered call ----------------------------------------------------------


def _near_future(day: Day, after: date) -> tuple[date, float] | None:
    live = sorted((e, p) for e, p in day.futures.items() if e >= after)
    return live[0] if live else None


def _itm_call(day: Day, expiry: date, moneyness: float) -> tuple[float, float] | None:
    target = day.spot * (1 - moneyness)
    strikes = sorted(k for (e, k) in day.calls if e == expiry and k % STEP == 0)
    if not strikes:
        return None
    k = min(strikes, key=lambda s: (abs(s - target), s))
    return k, day.calls[(expiry, k)]


def covered_call_monthly(
    days: list[Day], expiries: list[date], *, moneyness: float = 0.05, capital: float
) -> Result:
    """Buy the month's future and sell its 5%-ITM call after each expiry; hold to expiry."""
    result = Result(f"covered_call_monthly_{int(moneyness * 100)}itm")
    by_day = {d.day: d for d in days}
    dates = [d.day for d in days]
    usable = [e for e in expiries if dates[0] <= e <= dates[-1]]
    for prev, expiry in pairwise(usable):
        i = bisect_right(dates, prev)
        if i >= len(dates) or dates[i] >= expiry or expiry not in by_day:
            continue
        entry = days[i]
        fut = entry.futures.get(expiry)
        option = _itm_call(entry, expiry, moneyness)
        if fut is None or option is None:
            result.skipped.append(f"{entry.day}: no traded future or call for {expiry}")
            continue
        k, call = option
        units = capital / entry.spot
        settle = by_day[expiry].spot
        costs = (
            _cost(entry.day, Segment.FUTURES, Side.BUY, fut, units)
            + _cost(entry.day, Segment.OPTIONS, Side.SELL, call, units)
            + (_exercise_cost(expiry, settle, k, units, call=True) if settle > k else 0.0)
        )
        pnl = ((settle - fut) + call - max(settle - k, 0.0)) * units - costs
        result.periods.append(Period(entry.day, expiry, pnl, capital, costs, f"{k:.0f}CE"))
    return result


def covered_call_daily(
    days: list[Day], expiries: list[date], *, moneyness: float = 0.05, capital: float
) -> Result:
    """Aggarwal's rule: open at each close, square off at the next close."""
    result = Result(f"covered_call_daily_{int(moneyness * 100)}itm", periods_per_year=250.0)
    for today, nxt in pairwise(days):
        near = _near_future(today, after=nxt.day)  # must still trade tomorrow
        if near is None:
            continue
        expiry, fut = near
        # The paper's one-month call: the monthly expiry the future expires on.
        option = _itm_call(today, expiry, moneyness)
        fut_next = nxt.futures.get(expiry)
        if option is None or fut_next is None:
            result.skipped.append(f"{today.day}: missing future or call")
            continue
        k, call = option
        call_next = nxt.calls.get((expiry, k))
        if call_next is None:
            result.skipped.append(f"{today.day}: {k:.0f}CE did not trade on {nxt.day}")
            continue
        units = capital / today.spot
        costs = (
            _cost(today.day, Segment.FUTURES, Side.BUY, fut, units)
            + _cost(today.day, Segment.OPTIONS, Side.SELL, call, units)
            + _cost(nxt.day, Segment.FUTURES, Side.SELL, fut_next, units)
            + _cost(nxt.day, Segment.OPTIONS, Side.BUY, call_next, units)
        )
        pnl = ((fut_next - fut) - (call_next - call)) * units - costs
        result.periods.append(Period(today.day, nxt.day, pnl, capital, costs, f"{k:.0f}CE"))
    return result


def buy_and_hold_future(days: list[Day], expiries: list[date], *, capital: float) -> Result:
    """The covered call's benchmark: the near-month future alone, held month to month."""
    result = Result("nifty_future_monthly")
    by_day = {d.day: d for d in days}
    dates = [d.day for d in days]
    usable = [e for e in expiries if dates[0] <= e <= dates[-1]]
    for prev, expiry in pairwise(usable):
        i = bisect_right(dates, prev)
        if i >= len(dates) or expiry not in by_day:
            continue
        entry = days[i]
        fut = entry.futures.get(expiry)
        if fut is None:
            continue
        units = capital / entry.spot
        costs = _cost(entry.day, Segment.FUTURES, Side.BUY, fut, units)
        pnl = (by_day[expiry].spot - fut) * units - costs
        result.periods.append(Period(entry.day, expiry, pnl, capital, costs))
    return result
