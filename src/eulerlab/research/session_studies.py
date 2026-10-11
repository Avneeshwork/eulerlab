"""`make session-studies` — three Indian papers the daily engines cannot run.

Two trade from one close to the next open: Knuteson (2020) holds the index
overnight and is out during the day; Mukherjee (2025) buys at the close after a
rising day on which India VIX fell. Tier A and Tier B fill a decision at the
next close, so neither trade can be expressed as target weights. The third,
Gavhale (2025), is a monthly savings plan, not a strategy.

So these are **calculations**, not engine runs: no `Strategy`, no fills, no
result store, no trial. Each says so wherever its result is shown.

**The instrument is the Nifty future, not NIFTYBEES.** The ETF's open is its
first print of the day, and over 2016-2026 those prints sit up to 20% away from
the previous close on days the index moved under 1%: its mean overnight "gap"
was +0.78% a day against the index's +0.11%. Trading them would have reported
a fortune made from bad prints. The near-month future is the most-traded
instrument on the exchange and its open is a real price. Each overnight leg
uses one contract for both prices: the nearest expiry still alive the next
morning, so no leg spans a roll. Costs are the platform's cost model for
futures, charged on every round trip; the position is fully paid for, so a
1% move is a 1% return.

The index itself (`market_history.index_history`) is reported beside it,
gross, as the paper measured it. Results land in
`data/derived/session_studies.json`; research 064 reads them.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any

OUT = Path("data/derived/session_studies.json")
START, END = date(2016, 1, 1), date(2026, 9, 30)
NOTIONAL = Decimal(1_000_000)


@dataclass(frozen=True)
class Session:
    day: date
    open: float
    close: float


@dataclass(frozen=True)
class Overnight:
    """One contract from one close to the next day's open and close."""

    day: date
    """The second day: the open and close are this day's."""
    previous_close: float
    open: float
    close: float
    expiry: str


# --- data ------------------------------------------------------------------------


def index_sessions(name: str) -> list[tuple[Session, float]]:
    """One index's open and close per day, with India VIX's close beside it."""
    from eulerlab.market_history import INDEX_HISTORY, _stored_days

    out = []
    for day in _stored_days(INDEX_HISTORY):
        bar, vix = day["indices"].get(name), day["indices"].get("India VIX")
        if bar and vix and bar.get("o") and bar.get("c") and vix.get("c"):
            session = Session(date.fromisoformat(day["d"]), bar["o"], bar["c"])
            out.append((session, float(vix["c"])))
    return sorted(out, key=lambda item: item[0].day)


def futures_legs() -> list[Overnight]:
    """Each pair of consecutive trading days, on the nearest contract alive on
    the second day and quoted on both."""
    from eulerlab.market_history import NIFTY_FUTURES, _stored_days

    days = sorted(_stored_days(NIFTY_FUTURES), key=lambda d: str(d["d"]))
    return [leg for before, after in pairwise(days) if (leg := _leg(before, after))]


def _leg(before: dict[str, Any], after: dict[str, Any]) -> Overnight | None:
    today = str(after["d"])
    for expiry in sorted(after["contracts"]):
        if expiry < today or expiry not in before["contracts"]:
            continue
        a, b = before["contracts"][expiry], after["contracts"][expiry]
        if a.get("c") and b.get("o") and b.get("c"):
            return Overnight(date.fromisoformat(today), a["c"], b["o"], b["c"], expiry)
        return None
    return None


# --- costs and statistics ----------------------------------------------------------


def round_trip_cost(day: date, price: float) -> float:
    """Buying and selling one future once, as a fraction of the money traded."""
    from eulerlab.costs.model import cost_of_trade
    from eulerlab.costs.schedule import Segment, Side

    unit = Decimal(str(round(price, 4)))
    quantity = max(1, int(NOTIONAL / unit))
    total = sum(
        (
            cost_of_trade(
                trade_date=day, segment=Segment.FUTURES, side=side, price=unit, quantity=quantity
            ).total
            for side in (Side.BUY, Side.SELL)
        ),
        Decimal(0),
    )
    return float(total / (unit * quantity))


def summarise(days: Sequence[date], returns: Sequence[float], trades: int) -> dict[str, Any]:
    from eulerlab.validation.statistics import sharpe_stats

    equity = [1.0]
    for r in returns:
        equity.append(equity[-1] * (1.0 + r))
    peak, worst = equity[0], 0.0
    for value in equity:
        peak = max(peak, value)
        worst = min(worst, value / peak - 1.0)
    # At least one day: a window of a single session has a span of zero, and
    # annualising over 1e-9 years overflowed (a two-session request, T-4043).
    years = max((days[-1] - days[0]).days, 1) / 365.25 if days else 1.0
    return {
        "total_return": round(equity[-1] - 1.0, 6),
        "annual_return": round(equity[-1] ** (1 / years) - 1.0, 6),
        "sharpe": round(sharpe_stats(list(returns)).sharpe, 4),
        "max_drawdown": round(worst, 6),
        "round_trips": trades,
        "days": len(returns),
    }


def _inside(day: date) -> bool:
    return START <= day <= END


# --- Knuteson (2020): overnight vs intraday -----------------------------------------


def overnight_and_intraday(legs: Sequence[Overnight]) -> dict[str, Any]:
    """Hold the future from each close to the next open, or from each open to
    the same close, every day."""
    kept = [leg for leg in legs if _inside(leg.day)]
    days = [leg.day for leg in kept]
    night, night_net, day, day_net = [], [], [], []
    for leg in kept:
        cost = round_trip_cost(leg.day, leg.open)
        gap = leg.open / leg.previous_close - 1.0
        move = leg.close / leg.open - 1.0
        night.append(gap)
        night_net.append((1 + gap) * (1 - cost) - 1)
        day.append(move)
        day_net.append((1 + move) * (1 - cost) - 1)
    trips = len(kept)
    return {
        "overnight_gross": summarise(days, night, 0),
        "overnight_net": summarise(days, night_net, trips),
        "intraday_gross": summarise(days, day, 0),
        "intraday_net": summarise(days, day_net, trips),
    }


def index_split(rows: Sequence[tuple[Session, float]]) -> dict[str, Any]:
    """The same split on the Nifty 50 index itself, gross, and the index held."""
    kept = [s for s, _ in rows if _inside(s.day)]
    days = [b.day for _, b in pairwise(kept)]
    pairs = list(pairwise(kept))
    return {
        "buy_and_hold_gross": summarise(days, [b.close / a.close - 1 for a, b in pairs], 0),
        "overnight_gross": summarise(days, [b.open / a.close - 1 for a, b in pairs], 0),
        "intraday_gross": summarise(days, [b.close / b.open - 1 for _, b in pairs], 0),
    }


# --- Mukherjee (2025): calm rising days gap up ----------------------------------------


def calm_rise(previous_vix: float, session: Session, vix: float) -> bool:
    """A rising day (close above open) on which India VIX closed lower.

    # ASSUMPTION: the day's index and VIX closes are known at the moment of
    # buying at the close. In practice the order goes in a minute or two
    # before, on values that are almost final. See A-046."""
    return session.close > session.open and vix < previous_vix


def fear_fall(previous_vix: float, session: Session, vix: float) -> bool:
    """A falling day on which India VIX closed higher."""
    return session.close < session.open and vix > previous_vix


def gap_rates(rows: Sequence[tuple[Session, float]]) -> dict[str, Any]:
    """How often the next open gapped the predicted way after each signal,
    against how often it gapped up, or down, on any day."""
    inside = [(s, v) for s, v in rows if _inside(s.day)]
    counts = {
        "any_day_gap_up": [0, 0],
        "any_day_gap_down": [0, 0],
        "calm_rise_gap_up": [0, 0],
        "fear_fall_gap_down": [0, 0],
    }
    for (_, v0), (today, v1), (after, _) in zip(inside, inside[1:], inside[2:], strict=False):
        up = after.open > today.close
        down = after.open < today.close
        for name, hit, fired in (
            ("any_day_gap_up", up, True),
            ("any_day_gap_down", down, True),
            ("calm_rise_gap_up", up, calm_rise(v0, today, v1)),
            ("fear_fall_gap_down", down, fear_fall(v0, today, v1)),
        ):
            if fired:
                counts[name][0] += 1
                counts[name][1] += int(hit)
    return {
        name: {"signals": n, "hits": h, "rate": round(h / n, 4) if n else None}
        for name, (n, h) in counts.items()
    }


def futures_gap_rates(
    legs: Sequence[Overnight], rows: Sequence[tuple[Session, float]]
) -> dict[str, Any]:
    """The same rates on the future's own open against its previous close. The
    index's open is built from its constituents' first prints and its close
    from a 30-minute average, which leans its "gaps" upward; the future's are
    two trades in one contract."""
    calm, fear = set(), set()
    for (_, v0), (today, v1) in pairwise(rows):
        if calm_rise(v0, today, v1):
            calm.add(today.day)
        elif fear_fall(v0, today, v1):
            fear.add(today.day)
    previous = {b.day: a.day for a, b in pairwise([s for s, _ in rows])}
    counts = {
        "any_day_gap_up": [0, 0],
        "calm_rise_gap_up": [0, 0],
        "fear_fall_gap_down": [0, 0],
    }
    for leg in legs:
        if not _inside(leg.day) or leg.day not in previous:
            continue
        before = previous[leg.day]
        up, down = leg.open > leg.previous_close, leg.open < leg.previous_close
        for name, hit, fired in (
            ("any_day_gap_up", up, True),
            ("calm_rise_gap_up", up, before in calm),
            ("fear_fall_gap_down", down, before in fear),
        ):
            if fired:
                counts[name][0] += 1
                counts[name][1] += int(hit)
    return {
        name: {"signals": n, "hits": h, "rate": round(h / n, 4) if n else None}
        for name, (n, h) in counts.items()
    }


def calm_rise_trade(
    legs: Sequence[Overnight], rows: Sequence[tuple[Session, float]]
) -> dict[str, Any]:
    """Buy the future at the close of a calm rising Nifty day, sell at the next open."""
    signal = {today.day for (_, v0), (today, v1) in pairwise(rows) if calm_rise(v0, today, v1)}
    previous = {b.day: a.day for a, b in pairwise([s for s, _ in rows])}
    days, gross, net, trips = [], [], [], 0
    for leg in legs:
        if not _inside(leg.day):
            continue
        days.append(leg.day)
        if previous.get(leg.day) not in signal:
            gross.append(0.0)
            net.append(0.0)
            continue
        gap = leg.open / leg.previous_close - 1.0
        trips += 1
        gross.append(gap)
        net.append((1 + gap) * (1 - round_trip_cost(leg.day, leg.open)) - 1)
    return {"gross": summarise(days, gross, 0), "net": summarise(days, net, trips)}


# --- Gavhale (2025): expiry-day vs first-day SIP --------------------------------------


def xirr(flows: Sequence[tuple[date, float]]) -> float | None:
    """The annual rate that sets the flows' present value to zero, by bisection."""
    if not flows:
        return None
    first = flows[0][0]

    def value(rate: float) -> float:
        return float(
            sum(amount / (1 + rate) ** ((day - first).days / 365.0) for day, amount in flows)
        )

    low, high = -0.99, 10.0
    if value(low) * value(high) > 0:
        return None
    for _ in range(200):
        mid = (low + high) / 2
        if value(low) * value(mid) <= 0:
            high = mid
        else:
            low = mid
    return (low + high) / 2


def sip(
    closes: Sequence[tuple[date, float]],
    buy_on: Callable[[Sequence[date], int], bool],
    *,
    since: date,
    amount: float = 10_000.0,
) -> dict[str, Any]:
    """Invest `amount` at the close on every day `buy_on` selects from `since`
    to END, valued at END's close. Returns units, value and XIRR."""
    inside = [(d, c) for d, c in closes if since <= d <= END]
    days = [d for d, _ in inside]
    units, flows = 0.0, []
    for i, (day, close) in enumerate(inside):
        if buy_on(days, i):
            units += amount / close
            flows.append((day, -amount))
    if not flows:
        return {"instalments": 0}
    final_day, final_close = inside[-1]
    flows.append((final_day, units * final_close))
    rate = xirr(flows)
    return {
        "instalments": len(flows) - 1,
        "invested": amount * (len(flows) - 1),
        "value": round(units * final_close, 2),
        "xirr": round(rate, 6) if rate is not None else None,
    }


def first_of_month(days: Sequence[date], i: int) -> bool:
    return i == 0 or (days[i].year, days[i].month) != (days[i - 1].year, days[i - 1].month)


def expiry_vs_first_day(
    closes: Sequence[tuple[date, float]], expiries: Sequence[date]
) -> dict[str, Any]:
    """Both plans over the last 1, 3, 5 and 10 years and the whole window."""
    known = set(expiries)
    out: dict[str, Any] = {}
    for label, since in (
        ("1y", date(END.year - 1, END.month, 1)),
        ("3y", date(END.year - 3, END.month, 1)),
        ("5y", date(END.year - 5, END.month, 1)),
        ("10y", date(END.year - 10, END.month, 1)),
        ("all", START),
    ):
        out[label] = {
            "first_day": sip(closes, first_of_month, since=since),
            "expiry_day": sip(closes, lambda d, i: d[i] in known, since=since),
        }
    return out


# --- the run ------------------------------------------------------------------------


def run() -> dict[str, Any]:
    from eulerlab.market_history import nifty_expiries

    legs = futures_legs()
    nifty = index_sessions("Nifty 50")
    closes = [(s.day, s.close) for s, _ in nifty]
    return {
        "window": [START.isoformat(), END.isoformat()],
        "instrument": "Nifty futures, nearest contract alive the next morning",
        "note": (
            "Calculations, not engine runs: no fills, no result store, no trial. "
            "Net figures charge the platform's futures cost model on every round trip."
        ),
        "knuteson_2020": {
            "nifty_futures": overnight_and_intraday(legs),
            "nifty50_index": index_split(nifty),
        },
        "mukherjee_2025": {
            "gap_rates_nifty50_index": gap_rates(nifty),
            "gap_rates_nifty_futures": futures_gap_rates(legs, nifty),
            "calm_rise_overnight_futures": calm_rise_trade(legs, nifty),
        },
        "gavhale_2025": expiry_vs_first_day(closes, nifty_expiries()),
    }


def main(argv: Sequence[str] | None = None) -> int:
    argparse.ArgumentParser(prog="session-studies").parse_args(argv)
    result = run()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"written to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
