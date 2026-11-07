"""Research 172's two PROMOTEs on every liquid NSE stock, daily bars (research 173).

HISTORY #82: every stock screen chose from today's F&O list. Here the
universe each day is the 500 most traded NSE stocks by 20-session mean traded
value in the price panel, so nothing about today's lists enters.

- **H-0161** (H-0160's rule): yesterday +3% on half the usual delivery %:
  short at today's official open, cover at the official close, at most ten a
  day, cash intraday charges plus 2 bps a side. 2016-2024.
- **H-0162** (H-0153's rule): a SAST promoter purchase: buy at the next
  session's official open, sell at the official close 20 sessions later,
  at most ten open, delivery charges plus 2 bps a side. 2021-07 to 2024-11.

Raw prices: a window whose day-to-day close ratio leaves 0.6-1.6 is dropped
as a likely corporate action (A-119). `make daily-universe` writes
`data/derived/daily_universe.json`.
"""

from __future__ import annotations

import argparse
import bisect
import json
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from eulerlab.validation.intraday import IntradayRun

from eulerlab.intraday import cross_section as cs
from eulerlab.intraday import other_data_screen as od
from eulerlab.intraday import screen_common as sc

OUT = Path("data/derived/daily_universe.json")
PANEL = Path("data/derived/price_panel.jsonl")
TOP = 500
VALUE_DAYS = 20
TRADE = 100_000.0
CAPITAL = 1_000_000.0
FIRST_0161 = date(2016, 1, 1)
FIRST_0162 = date(2021, 7, 1)
END = cs.DATA_END
SPLIT_LOW, SPLIT_HIGH = 0.6, 1.6


@dataclass(frozen=True)
class Bar:
    open: float
    close: float
    value: float


def load_panel(
    path: Path = PANEL, *, start: date = date(2015, 1, 1), end: date = END
) -> dict[str, dict[date, Bar]]:
    out: dict[str, dict[date, Bar]] = defaultdict(dict)
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            day = date.fromisoformat(row["d"])
            if not start <= day <= end or not row.get("o") or not row.get("c"):
                continue
            out[row["s"]][day] = Bar(float(row["o"]), float(row["c"]), float(row.get("t") or 0.0))
    return out


def liquid_sets(
    panel: Mapping[str, Mapping[date, Bar]], sessions: Sequence[date]
) -> dict[date, frozenset[str]]:
    """The TOP stocks by mean traded value over each stock's previous 20 sessions."""
    del sessions
    ranked: dict[date, list[tuple[float, str]]] = defaultdict(list)
    for symbol, bars in panel.items():
        days = sorted(bars)
        prefix = [0.0]
        for d in days:
            prefix.append(prefix[-1] + bars[d].value)
        for k in range(VALUE_DAYS, len(days)):
            mean = (prefix[k] - prefix[k - VALUE_DAYS]) / VALUE_DAYS
            ranked[days[k]].append((-mean, symbol))
    return {day: frozenset(s for _, s in sorted(r)[:TOP]) for day, r in ranked.items()}


def _clean(bars: Mapping[date, Bar], days: Sequence[date]) -> bool:
    closes = [bars[d].close for d in days]
    return all(SPLIT_LOW <= b / a <= SPLIT_HIGH for a, b in pairwise(closes))


def h0161_trades(
    panel: Mapping[str, Mapping[date, Bar]],
    sessions: Sequence[date],
    liquid: Mapping[date, frozenset[str]],
    delivery: Mapping[str, Mapping[date, float]],
) -> list[cs.Trade]:
    by_day: dict[date, list[tuple[float, str, cs.Trade]]] = defaultdict(list)
    for i in range(2, len(sessions)):
        day, p, q = sessions[i], sessions[i - 1], sessions[i - 2]
        if day < FIRST_0161:
            continue
        for symbol in liquid.get(day, frozenset()):
            bars = panel[symbol]
            if day not in bars or p not in bars or q not in bars:
                continue
            r = bars[p].close / bars[q].close - 1.0
            ratio = delivery.get(symbol, {}).get(p)
            if r < 0.03 or ratio is None or ratio > 0.5 or not _clean(bars, (q, p, day)):
                continue
            bar = bars[day]
            quantity = cs.sized(TRADE, bar.open)
            if quantity and bar.open >= cs.MIN_PRICE:
                trade = cs.Trade(symbol, day, -1, quantity, 0, bar.open, 374, bar.close, "close")
                by_day[day].append((ratio, symbol, trade))
    out: list[cs.Trade] = []
    for day in sorted(by_day):
        out.extend(t for _, _, t in sorted(by_day[day], key=lambda x: (x[0], x[1]))[:10])
    return out


def h0162_positions(
    panel: Mapping[str, Mapping[date, Bar]],
    sessions: Sequence[date],
    liquid: Mapping[date, frozenset[str]],
    promoters: Mapping[str, Mapping[date, float]],
) -> list[od.Swing]:
    found = []
    for symbol, days in promoters.items():
        bars = panel.get(symbol)
        if not bars:
            continue
        for day, share in days.items():
            if not FIRST_0162 <= day <= END or symbol not in liquid.get(day, frozenset()):
                continue
            i = bisect.bisect_left(sessions, day)
            if i + 20 >= len(sessions) or sessions[i] != day:
                continue
            window = sessions[i : i + 21]
            if (
                sessions[i + 20] > END
                or any(d not in bars for d in window)
                or not _clean(bars, window)
            ):
                continue
            first = bars[day]
            quantity = int(TRADE / first.open) if first.open >= cs.MIN_PRICE else 0
            if not quantity:
                continue
            marks = tuple((d, bars[d].close) for d in window[:-1])
            swing = od.Swing(
                symbol, day, window[-1], quantity, first.open, bars[window[-1]].close, marks
            )
            found.append((day, -share, symbol, swing))
    return od.cap_swings(found)


TOW_TOP = 100
TOW_SIDE = 5
TOW_DAYS = 20


def h0163_trades(
    panel: Mapping[str, Mapping[date, Bar]],
    sessions: Sequence[date],
    liquid_ranked: Mapping[date, list[str]],
    *,
    notional: float,
) -> list[cs.Trade]:
    """H-0163 (research 175): H-0132's tug of war on daily bars, open to close."""
    index = {d: i for i, d in enumerate(sessions)}
    overnight: dict[str, dict[date, float]] = {}
    for symbol, bars in panel.items():
        days = sorted(bars)
        found = {}
        for a, b in pairwise(days):
            ratio = bars[b].open / bars[a].close if bars[a].close > 0 else 0.0
            if index.get(b, 0) - index.get(a, 0) == 1 and SPLIT_LOW <= ratio <= SPLIT_HIGH:
                found[b] = ratio - 1.0
        overnight[symbol] = found
    out: list[cs.Trade] = []
    for i, day in enumerate(sessions):
        if day < FIRST_0161 or i < TOW_DAYS:
            continue
        before = sessions[i - TOW_DAYS : i]
        scored = []
        for symbol in liquid_ranked.get(day, [])[:TOW_TOP]:
            moves = overnight.get(symbol, {})
            bar = panel[symbol].get(day)
            values = [moves[d] for d in before if d in moves]
            if bar is None or len(values) < 15 or bar.open < cs.MIN_PRICE:
                continue
            if not SPLIT_LOW <= bar.close / bar.open <= SPLIT_HIGH:
                continue
            scored.append((statistics.fmean(values), symbol, bar))
        if len(scored) < 20:
            continue
        scored.sort(key=lambda x: (x[0], x[1]))
        for side, chosen in ((1, scored[:TOW_SIDE]), (-1, scored[-TOW_SIDE:])):
            for _, symbol, bar in chosen:
                quantity = cs.sized(notional, bar.open)
                if quantity:
                    out.append(
                        cs.Trade(symbol, day, side, quantity, 0, bar.open, 374, bar.close, "close")
                    )
    return out


def liquid_ranked(panel: Mapping[str, Mapping[date, Bar]]) -> dict[date, list[str]]:
    """Each day's stocks by mean traded value over their previous 20 sessions, largest first."""
    ranked: dict[date, list[tuple[float, str]]] = defaultdict(list)
    for symbol, bars in panel.items():
        days = sorted(bars)
        prefix = [0.0]
        for d in days:
            prefix.append(prefix[-1] + bars[d].value)
        for k in range(VALUE_DAYS, len(days)):
            ranked[days[k]].append((-(prefix[k] - prefix[k - VALUE_DAYS]) / VALUE_DAYS, symbol))
    return {d: [s for _, s in sorted(r)[:TOP]] for d, r in ranked.items()}


class Context:
    def __init__(self) -> None:
        from eulerlab.intraday import nse_reports_screen as rep

        self.panel = load_panel()
        self.sessions = sorted({d for bars in self.panel.values() for d in bars})
        self.liquid = liquid_sets(self.panel, self.sessions)
        self.delivery = od.delivery_ratios()
        sast = [x for _, found in rep._parsed("sast", rep.promoter_buys) for x in found]
        self.promoters = rep.promoter_events(sast, self.sessions)


def _window(ctx: Context, first: date) -> list[date]:
    return [d for d in ctx.sessions if first <= d <= END]


def _summary(
    pieces: Sequence[Any], sessions: Sequence[date], capital: float = CAPITAL
) -> dict[str, Any]:
    net: dict[date, float] = defaultdict(float)
    twice: dict[date, float] = defaultdict(float)
    for p in pieces:
        net[p.day] += (p.gross - p.costs) / capital
        twice[p.day] += (p.gross - 2 * p.costs) / capital
    daily = [net.get(d, 0.0) for d in sessions]
    middle = len(daily) // 2
    years: dict[int, list[float]] = defaultdict(list)
    for d in sessions:
        years[d.year].append(net.get(d, 0.0))
    return {
        "net": sc.daily_stats(daily),
        "halves": {
            "first": sc.daily_stats(daily[:middle]),
            "second": sc.daily_stats(daily[middle:]),
        },
        "net_at_2x_costs": sc.daily_stats([twice.get(d, 0.0) for d in sessions]),
        "net_by_year": {str(y): sc.daily_stats(v) for y, v in sorted(years.items())},
    }


def evaluate(ctx: Context) -> list[dict[str, Any]]:
    trades = h0161_trades(ctx.panel, ctx.sessions, ctx.liquid, ctx.delivery)
    swings = h0162_positions(ctx.panel, ctx.sessions, ctx.liquid, ctx.promoters)
    t_net = [(t.gross - t.costs) / t.notional * 1e4 for t in trades]
    s_net = [(s.gross_total - sum(s.costs_at())) / s.notional * 1e4 for s in swings]
    return [
        {
            "hypothesis": "H-0161",
            "id": "daily_low_delivery_rally_fade_all_nse",
            "trades": len(trades),
            "per_trade_bps": {
                "gross_mean": round(statistics.fmean(t.gross / t.notional * 1e4 for t in trades), 2)
                if trades
                else None,
                "net_mean": round(statistics.fmean(t_net), 2) if t_net else None,
            },
            **_summary(trades, _window(ctx, FIRST_0161)),
        },
        {
            "hypothesis": "H-0162",
            "id": "daily_promoter_buy_20d_all_nse",
            "positions": len(swings),
            "per_position_bps": {"net_mean": round(statistics.fmean(s_net), 2) if s_net else None},
            **_summary([p for s in swings for p in s.pieces()], _window(ctx, FIRST_0162)),
        },
    ]


def evaluate_h0163(ctx: Context) -> list[dict[str, Any]]:
    ranked = liquid_ranked(ctx.panel)
    out = []
    for label, notional, capital in (("5x MIS", 500_000.0, CAPITAL), ("1x", TRADE, CAPITAL)):
        trades = h0163_trades(ctx.panel, ctx.sessions, ranked, notional=notional)
        net = [(t.gross - t.costs) / t.notional * 1e4 for t in trades]
        legs = {
            side: round(
                statistics.fmean(t.gross / t.notional * 1e4 for t in trades if t.direction == d), 2
            )
            for side, d in (("long_gross", 1), ("short_gross", -1))
        }
        out.append(
            {
                "hypothesis": "H-0163",
                "size": label,
                "trades": len(trades),
                "per_trade_bps": {
                    "gross_mean": round(
                        statistics.fmean(t.gross / t.notional * 1e4 for t in trades), 2
                    ),
                    "net_mean": round(statistics.fmean(net), 2),
                    **legs,
                },
                **_summary(trades, _window(ctx, FIRST_0161), capital),
            }
        )
    return out


def validation_run(hypothesis: str) -> IntradayRun:
    from eulerlab.validation.intraday import IntradayRun

    ctx = Context()
    if hypothesis == "H-0163":
        trades = h0163_trades(ctx.panel, ctx.sessions, liquid_ranked(ctx.panel), notional=500_000.0)
        return IntradayRun(trades, [], _window(ctx, FIRST_0161), CAPITAL)
    if hypothesis == "H-0161":
        trades = h0161_trades(ctx.panel, ctx.sessions, ctx.liquid, ctx.delivery)
        return IntradayRun(trades, [], _window(ctx, FIRST_0161), CAPITAL)
    swings = h0162_positions(ctx.panel, ctx.sessions, ctx.liquid, ctx.promoters)
    return IntradayRun(
        [p for s in swings for p in s.pieces()], [], _window(ctx, FIRST_0162), CAPITAL
    )


def main() -> int:
    parser = argparse.ArgumentParser(prog="daily-universe")
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--tug-of-war", action="store_true", help="H-0163 only (research 175)")
    args = parser.parse_args()
    if args.tug_of_war:
        found = evaluate_h0163(Context())
        Path("data/derived/tug_of_war_daily_all_nse.json").write_text(json.dumps(found, indent=1))
        for one in found:
            print(
                f"H-0163 {one['size']}: {one['trades']} trades; {one['per_trade_bps']}; net Sharpe "
                f"{one['net']['sharpe']}; halves {one['halves']['first']['sharpe']} / "
                f"{one['halves']['second']['sharpe']}; 2x {one['net_at_2x_costs']['sharpe']}; "
                f"years { {y: round(v['total_return'], 3) for y, v in one['net_by_year'].items()} }"
            )
        return 0
    runs = evaluate(Context())
    args.output.write_text(
        json.dumps({"research": "173", "spent_trials": 0, "runs": runs}, indent=1)
    )
    for one in runs:
        per = one.get("per_trade_bps") or one.get("per_position_bps")
        print(
            f"{one['hypothesis']}: {one.get('trades', one.get('positions'))}; {per}; net Sharpe "
            f"{one['net']['sharpe']}; halves {one['halves']['first']['sharpe']} / "
            f"{one['halves']['second']['sharpe']}; 2x {one['net_at_2x_costs']['sharpe']}; "
            f"years { {y: round(v['total_return'], 3) for y, v in one['net_by_year'].items()} }"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
