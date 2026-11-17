"""Ten more rules on every liquid NSE stock, daily bars (research 176, H-0164 to H-0173).

Research 173's frame: the 500 most traded NSE stocks each day, stocks in
series BE/BZ the previous session skipped. Intraday rules trade the official
open to the official close at cash intraday costs; swing rules buy at an
official open and sell at the official close of the exit session, delivery
costs, long only. ₹1 lakh a position, ten a day or ten open.

`make daily-more` writes `data/derived/daily_more.json`.
"""

from __future__ import annotations

import argparse
import bisect
import json
import statistics
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import date, time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from eulerlab.paths import data_path

if TYPE_CHECKING:
    from eulerlab.validation.intraday import IntradayRun

from eulerlab.intraday import cross_section as cs
from eulerlab.strategies.studies import daily_universe as du
from eulerlab.strategies.studies import other_data as od

OUT = data_path("derived/daily_more.json")
FIRST = cs.RESEARCH_START
REPORTS_FIRST = date(2021, 7, 1)
END = cs.DATA_END
TRADE = 100_000.0
CAPITAL = 1_000_000.0

Event = tuple[date, str, int, float]
"""(trade or entry day, symbol, direction, rank: smaller first)."""


class Context:
    def __init__(self) -> None:
        from eulerlab.ingest import trade_for_trade
        from eulerlab.strategies.studies import nse_reports as rep

        self.panel = du.load_panel()
        self.sessions = sorted({d for bars in self.panel.values() for d in bars})
        self.index = {d: i for i, d in enumerate(self.sessions)}
        self.liquid = du.liquid_sets(self.panel, self.sessions)
        self.delivery = od.delivery_ratios()
        self.t2t = trade_for_trade.load()
        bulk = rep._parsed("bulk_deals", rep.bulk_net)
        self.buys, self.sells = rep.bulk_events(bulk, self.sessions)
        self.results = od.results_times()

    def prev(self, day: date, back: int = 1) -> date | None:
        i = self.index.get(day)
        return self.sessions[i - back] if i is not None and i >= back else None

    def tradable(self, symbol: str, day: date) -> bool:
        p = self.prev(day)
        bars = self.panel.get(symbol, {})
        return (
            p is not None
            and day in bars
            and symbol in self.liquid.get(day, frozenset())
            and symbol not in self.t2t.get(p, frozenset())
            and bars[day].open >= cs.MIN_PRICE
        )

    def ret(self, symbol: str, day: date) -> float | None:
        p = self.prev(day)
        bars = self.panel.get(symbol, {})
        if p is None or day not in bars or p not in bars or bars[p].close <= 0:
            return None
        r = bars[day].close / bars[p].close - 1.0
        return r if du.SPLIT_LOW <= 1 + r <= du.SPLIT_HIGH else None


# --- signals -------------------------------------------------------------------------


def _delivery_move(ctx: Context, *, up: bool, high_delivery: bool) -> list[Event]:
    out: list[Event] = []
    for day in ctx.sessions:
        p = ctx.prev(day)
        if p is None or not FIRST <= day <= END:
            continue
        for symbol in ctx.liquid.get(day, frozenset()):
            r, ratio = ctx.ret(symbol, p), ctx.delivery.get(symbol, {}).get(p)
            if r is None or ratio is None or not ctx.tradable(symbol, day):
                continue
            moved = r >= 0.03 if up else r <= -0.03
            ok = ratio >= 2.0 if high_delivery else ratio <= 0.5
            if moved and ok:
                out.append((day, symbol, 1, -ratio if high_delivery else ratio))
    return out


def _bulk(ctx: Context, *, buys: bool) -> list[Event]:
    events = ctx.buys if buys else ctx.sells
    return [
        (day, symbol, 1 if buys else -1, -value)
        for symbol, days in events.items()
        for day, value in days.items()
        if REPORTS_FIRST <= day <= END and ctx.tradable(symbol, day)
    ]


def _results_mornings(ctx: Context) -> list[tuple[date, str]]:
    """(session, symbol) where results were disclosed after the previous 15:30 and before 09:15.

    A disclosure at or after 15:30 on a session day belongs to the next
    session's morning; one during 09:15-15:30 belongs to no morning. (The
    first version skipped every evening disclosure, HISTORY #84.)
    """
    out = []
    for symbol, times in ctx.results.items():
        for when in times:
            i = bisect.bisect_left(ctx.sessions, when.date())
            if i < len(ctx.sessions) and ctx.sessions[i] == when.date():
                if time(9, 15) <= when.time() < time(15, 30):
                    continue  # disclosed during that session
                if when.time() >= time(15, 30):
                    i += 1  # after the close: the next session's morning
            if i >= len(ctx.sessions):
                continue
            out.append((ctx.sessions[i], symbol))
    return sorted(set(out))


def _gap(ctx: Context, symbol: str, day: date) -> float | None:
    p = ctx.prev(day)
    bars = ctx.panel.get(symbol, {})
    if p is None or day not in bars or p not in bars or bars[p].close <= 0:
        return None
    g = bars[day].open / bars[p].close - 1.0
    return g if du.SPLIT_LOW <= 1 + g <= du.SPLIT_HIGH else None


def h0168_events(ctx: Context) -> list[Event]:
    out: list[Event] = []
    for day, symbol in _results_mornings(ctx):
        g = _gap(ctx, symbol, day)
        if (
            REPORTS_FIRST <= day <= END
            and g is not None
            and abs(g) >= 0.03
            and ctx.tradable(symbol, day)
        ):
            out.append((day, symbol, -1 if g > 0 else 1, -abs(g)))
    return out


def h0172_events(ctx: Context) -> list[Event]:
    out: list[Event] = []
    for day, symbol in _results_mornings(ctx):
        g, bars = _gap(ctx, symbol, day), ctx.panel.get(symbol, {})
        ratio = ctx.delivery.get(symbol, {}).get(day)
        i = ctx.index.get(day)
        if g is None or ratio is None or i is None or i + 1 >= len(ctx.sessions):
            continue
        entry = ctx.sessions[i + 1]
        if (
            g >= 0.03
            and bars[day].close > bars[day].open
            and ratio >= 1.5
            and ctx.tradable(symbol, entry)
            and REPORTS_FIRST <= entry <= END
        ):
            out.append((entry, symbol, 1, -g))
    return out


def h0173_events(ctx: Context) -> list[Event]:
    out: list[Event] = []
    for symbol, bars in ctx.panel.items():
        days = sorted(bars)
        closes = [bars[d].close for d in days]
        for k in range(251, len(days)):
            p, day = days[k - 1], days[k]
            if not FIRST <= day <= END or ctx.prev(day) != p:
                continue
            if closes[k - 1] < max(closes[k - 251 : k - 1]):
                continue
            ratio = ctx.delivery.get(symbol, {}).get(p)
            if ratio is not None and ratio >= 2.0 and ctx.tradable(symbol, day):
                out.append((day, symbol, 1, -ratio))
    return out


# --- books ---------------------------------------------------------------------------


Pricer = Callable[[str, date, int, str, float], float]
"""(symbol, day, +1 buy / -1 sell, "open" | "close", order value) -> fill price (#119)."""


def day_book(ctx: Context, events: Sequence[Event], pricer: Pricer | None = None) -> list[cs.Trade]:
    by_day: dict[date, list[tuple[float, str, int]]] = defaultdict(list)
    for day, symbol, side, rank in events:
        by_day[day].append((rank, symbol, side))
    out: list[cs.Trade] = []
    for day in sorted(by_day):
        for _, symbol, side in sorted(by_day[day])[:10]:
            bar = ctx.panel[symbol][day]
            if not du.SPLIT_LOW <= bar.close / bar.open <= du.SPLIT_HIGH:
                continue
            quantity = cs.sized(TRADE, bar.open)
            if quantity:
                entry, exit_ = bar.open, bar.close
                if pricer is not None:
                    entry = pricer(symbol, day, side, "open", TRADE)
                    exit_ = pricer(symbol, day, -side, "close", TRADE)
                out.append(cs.Trade(symbol, day, side, quantity, 0, entry, 374, exit_, "close"))
    return out


def swing_book(
    ctx: Context, events: Sequence[Event], hold: int, pricer: Pricer | None = None
) -> list[od.Swing]:
    # The data's own end, not the research window's: a paper book's data runs past
    # 2024-11-30, and every swing it entered was dropped here (HISTORY #91).
    last = getattr(ctx, "end", END)
    found = []
    for day, symbol, _, rank in events:
        i = ctx.index[day]
        if i + hold >= len(ctx.sessions) or ctx.sessions[i + hold] > last:
            continue
        window = ctx.sessions[i : i + hold + 1]
        bars = ctx.panel[symbol]
        if any(d not in bars for d in window) or not du._clean(bars, window):
            continue
        quantity = int(TRADE / bars[day].open)
        if not quantity:
            continue
        marks = tuple((d, bars[d].close) for d in window[:-1])
        entry, exit_ = bars[day].open, bars[window[-1]].close
        if pricer is not None:
            entry = pricer(symbol, day, 1, "open", TRADE)
            exit_ = pricer(symbol, window[-1], -1, "close", TRADE)
        found.append(
            (day, rank, symbol, od.Swing(symbol, day, window[-1], quantity, entry, exit_, marks))
        )
    return od.cap_swings(found)


DAY_RULES: dict[str, tuple[str, Callable[[Context], list[Event]], date]] = {
    "H-0164": (
        "daily_low_delivery_fall_buy",
        lambda c: _delivery_move(c, up=False, high_delivery=False),
        FIRST,
    ),
    "H-0165": (
        "daily_high_delivery_rise_buy",
        lambda c: _delivery_move(c, up=True, high_delivery=True),
        FIRST,
    ),
    "H-0166": ("daily_bulk_buy_next_day", lambda c: _bulk(c, buys=True), REPORTS_FIRST),
    "H-0167": ("daily_bulk_sell_short_next_day", lambda c: _bulk(c, buys=False), REPORTS_FIRST),
    "H-0168": ("daily_results_gap_fade", h0168_events, REPORTS_FIRST),
}
SWING_RULES: dict[str, tuple[str, Callable[[Context], list[Event]], int, date]] = {
    "H-0169": ("swing_bulk_buy_10d", lambda c: _bulk(c, buys=True), 10, REPORTS_FIRST),
    "H-0170": (
        "swing_high_delivery_rise_10d",
        lambda c: _delivery_move(c, up=True, high_delivery=True),
        10,
        FIRST,
    ),
    "H-0171": (
        "swing_low_delivery_fall_5d",
        lambda c: _delivery_move(c, up=False, high_delivery=False),
        5,
        FIRST,
    ),
    "H-0172": ("swing_results_gap_delivery_20d", h0172_events, 20, REPORTS_FIRST),
    "H-0173": ("swing_new_high_on_delivery_20d", h0173_events, 20, FIRST),
}


def _window(ctx: Context, first: date) -> list[date]:
    return [d for d in ctx.sessions if first <= d <= END]


def evaluate(ctx: Context) -> list[dict[str, Any]]:
    runs = []
    for h, (run_id, events, first) in DAY_RULES.items():
        trades = day_book(ctx, events(ctx))
        net = [(t.gross - t.costs) / t.notional * 1e4 for t in trades]
        gross = [t.gross / t.notional * 1e4 for t in trades]
        runs.append(
            {
                "hypothesis": h,
                "id": run_id,
                "trades": len(trades),
                "per_trade_bps": {
                    "gross_mean": round(statistics.fmean(gross), 2) if gross else None,
                    "net_mean": round(statistics.fmean(net), 2) if net else None,
                },
                **du._summary(trades, _window(ctx, first), CAPITAL),
            }
        )
    for h, (run_id, events, hold, first) in SWING_RULES.items():
        swings = swing_book(ctx, events(ctx), hold)
        net = [(s.gross_total - sum(s.costs_at())) / s.notional * 1e4 for s in swings]
        runs.append(
            {
                "hypothesis": h,
                "id": run_id,
                "positions": len(swings),
                "per_position_bps": {"net_mean": round(statistics.fmean(net), 2) if net else None},
                **du._summary(
                    [p for s in swings for p in s.pieces()], _window(ctx, first), CAPITAL
                ),
            }
        )
    return runs


def validation_run(hypothesis: str) -> IntradayRun:
    from eulerlab.validation.intraday import IntradayRun

    ctx = Context()
    if hypothesis in DAY_RULES:
        _, events, first = DAY_RULES[hypothesis]
        return IntradayRun(day_book(ctx, events(ctx)), [], _window(ctx, first), CAPITAL)
    _, events, hold, first = SWING_RULES[hypothesis]
    pieces = [p for s in swing_book(ctx, events(ctx), hold) for p in s.pieces()]
    return IntradayRun(pieces, [], _window(ctx, first), CAPITAL)


def passes(one: Mapping[str, Any]) -> bool:
    values = (
        one["halves"]["first"]["sharpe"],
        one["halves"]["second"]["sharpe"],
        one["net_at_2x_costs"]["sharpe"],
    )
    return all(v is not None and v > 0 for v in values)


def main() -> int:
    parser = argparse.ArgumentParser(prog="daily-more")
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    runs = evaluate(Context())
    args.output.write_text(
        json.dumps({"research": "176", "spent_trials": 0, "runs": runs}, indent=1)
    )
    for one in runs:
        per = one.get("per_trade_bps") or one.get("per_position_bps")
        print(
            f"{one['hypothesis']} {one['id']}: {one.get('trades', one.get('positions'))}; {per}; "
            f"net Sharpe {one['net']['sharpe']}; halves {one['halves']['first']['sharpe']} / "
            f"{one['halves']['second']['sharpe']}; 2x {one['net_at_2x_costs']['sharpe']}; "
            f"{'PASS' if passes(one) else 'fail'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
