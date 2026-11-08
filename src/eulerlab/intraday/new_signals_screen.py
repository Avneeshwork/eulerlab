"""Ten rules on signals the rule engine lacks (research 178, H-0184 to H-0193).

Research 173's frame (the 500 most traded NSE stocks each day, daily bars,
BE/BZ skipped, 1x, ₹1 lakh a position) with signals the autopilot's engine
(ADR-150) does not have: price-limit closes (close at the day's high or low on
a 9.5%+ move), India VIX, bulk-deal client names, results reactions and
multi-day delivery. Books and costs are `daily_more_screen`'s.

`make new-signals` writes `data/derived/new_signals.json`.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import statistics
from collections import defaultdict
from collections.abc import Callable, Mapping
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from eulerlab.validation.intraday import IntradayRun

from eulerlab.intraday import daily_more_screen as dm
from eulerlab.intraday import daily_universe_screen as du

OUT = Path("data/derived/new_signals.json")
PANEL = Path("data/derived/price_panel.jsonl")
LIMIT_MOVE = 0.095
VIX_JUMP = 0.15
REACTION = 0.05
INSTITUTION = re.compile(r"MUTUAL FUND|INSURANCE|LIFE|PENSION|SICAV|ASSET MANAGEMENT|TRUSTEE| FUND")
"""Bulk-deal clients counted as institutions (research 178), fixed before any run."""

Event = dm.Event


def highs_lows(path: Path = PANEL) -> dict[str, dict[date, tuple[float, float]]]:
    """{symbol: {day: (high, low)}}, the part of the panel `du.load_panel` leaves out."""
    out: dict[str, dict[date, tuple[float, float]]] = defaultdict(dict)
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            day = date.fromisoformat(row["d"])
            if day < date(2015, 1, 1) or day > dm.END or not row.get("h") or not row.get("l"):
                continue
            out[row["s"]][day] = (float(row["h"]), float(row["l"]))
    return out


def institution_buys(sessions: list[date]) -> dict[str, dict[date, float]]:
    """{symbol: {next session: value}} of one-sided bulk buying by institutions."""
    from eulerlab.intraday import nse_reports_screen as rep

    out: dict[str, dict[date, float]] = defaultdict(dict)
    for day, text in rep.report_files("bulk_deals", rep.FIRST_DAY):
        sides: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for row in csv.DictReader(io.StringIO(text)):
            clean = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
            client = clean.get("Client Name", "").upper()
            side = clean.get("Buy / Sell", "").upper()
            symbol = clean.get("Symbol", "")
            if not symbol or side not in ("BUY", "SELL") or not INSTITUTION.search(client):
                continue
            value = rep._number(clean.get("Quantity Traded", "")) * rep._number(
                clean.get("Trade Price / Wght. Avg. Price", "")
            )
            sides[(symbol, client)][side] += value
        target = rep.next_session(sessions, day)
        if target is None:
            continue
        for (symbol, _), traded in sides.items():
            if set(traded) == {"BUY"}:
                out[symbol][target] = out[symbol].get(target, 0.0) + traded["BUY"]
    return out


class Context(dm.Context):
    def __init__(self) -> None:
        super().__init__()
        self.hl = highs_lows()
        from eulerlab.intraday import mft_screen as mft

        closes = mft._official_closes("India VIX")
        days = sorted(closes)
        self.vix_jump = {
            b: closes[b] / closes[a] - 1.0
            for a, b in pairwise(days)
            if closes[a]
        }
        self.institutions = institution_buys(self.sessions)


# --- events --------------------------------------------------------------------------


def limit_closes(ctx: Context, *, up: bool, hold_side: int) -> list[Event]:
    out: list[Event] = []
    for day in ctx.sessions:
        p = ctx.prev(day)
        if p is None or not dm.FIRST <= day <= dm.END:
            continue
        for symbol in ctx.liquid.get(day, frozenset()):
            r = ctx.ret(symbol, p)
            hl = ctx.hl.get(symbol, {}).get(p)
            if r is None or hl is None or not ctx.tradable(symbol, day):
                continue
            close = ctx.panel[symbol][p].close
            if up and r >= LIMIT_MOVE and close >= hl[0]:
                out.append((day, symbol, hold_side, -r))
            elif not up and r <= -LIMIT_MOVE and close <= hl[1]:
                out.append((day, symbol, hold_side, r))
    return out


def vix_losers(ctx: Context) -> list[Event]:
    out: list[Event] = []
    for day in ctx.sessions:
        p = ctx.prev(day)
        if p is None or not dm.FIRST <= day <= dm.END or ctx.vix_jump.get(p, 0.0) < VIX_JUMP:
            continue
        # The 100 most traded by the previous session's traded value: known before the open.
        ranked = sorted(
            ctx.liquid.get(day, frozenset()),
            key=lambda s: (-(ctx.panel[s][p].value if p in ctx.panel[s] else 0.0), s),
        )
        scored = []
        for symbol in ranked[:100]:
            r = ctx.ret(symbol, p)
            if r is not None and ctx.tradable(symbol, day):
                scored.append((r, symbol))
        out.extend((day, s, 1, r) for r, s in sorted(scored)[:10])
    return out


def reactions(ctx: Context, *, both_sides: bool) -> list[Event]:
    """The session after a 5% results reaction: follow it (long only when not `both_sides`)."""
    out: list[Event] = []
    for day, symbol in dm._results_mornings(ctx):
        i = ctx.index.get(day)
        if i is None or i + 1 >= len(ctx.sessions):
            continue
        nxt = ctx.sessions[i + 1]
        r = ctx.ret(symbol, day)
        if r is None or not dm.REPORTS_FIRST <= nxt <= dm.END or not ctx.tradable(symbol, nxt):
            continue
        if r >= REACTION:
            out.append((nxt, symbol, 1, -r))
        elif both_sides and r <= -REACTION:
            out.append((nxt, symbol, -1, r))
    return out


def institution_events(ctx: Context) -> list[Event]:
    return [
        (day, symbol, 1, -value)
        for symbol, days in ctx.institutions.items()
        for day, value in days.items()
        if dm.REPORTS_FIRST <= day <= dm.END and ctx.tradable(symbol, day)
    ]


def accumulation(ctx: Context) -> list[Event]:
    out: list[Event] = []
    for day in ctx.sessions:
        i = ctx.index[day]
        if i < 6 or not dm.FIRST <= day <= dm.END:
            continue
        window = ctx.sessions[i - 5 : i]
        start = ctx.sessions[i - 6]
        for symbol in ctx.liquid.get(day, frozenset()):
            bars, deliv = ctx.panel[symbol], ctx.delivery.get(symbol, {})
            ratios = [deliv[d] for d in window if d in deliv]
            if len(ratios) < 5 or start not in bars or window[-1] not in bars:
                continue
            move = bars[window[-1]].close / bars[start].close - 1.0
            if statistics.fmean(ratios) >= 1.5 and abs(move) <= 0.02 and ctx.tradable(symbol, day):
                out.append((day, symbol, 1, -statistics.fmean(ratios)))
    return out


DAY_RULES: dict[str, tuple[str, Callable[[Context], list[Event]], date]] = {
    "H-0184": ("daily_limit_up_fade", lambda c: limit_closes(c, up=True, hold_side=-1), dm.FIRST),
    "H-0185": (
        "daily_limit_down_bounce",
        lambda c: limit_closes(c, up=False, hold_side=1),
        dm.FIRST,
    ),
    "H-0186": ("daily_vix_jump_losers_buy", vix_losers, dm.FIRST),
    "H-0187": (
        "daily_results_day_two_follow",
        lambda c: reactions(c, both_sides=True),
        dm.REPORTS_FIRST,
    ),
    "H-0188": ("daily_institution_bulk_buy", institution_events, dm.REPORTS_FIRST),
}
SWING_RULES: dict[str, tuple[str, Callable[[Context], list[Event]], int, date]] = {
    "H-0189": ("swing_institution_bulk_buy_20d", institution_events, 20, dm.REPORTS_FIRST),
    "H-0190": (
        "swing_results_reaction_20d",
        lambda c: reactions(c, both_sides=False),
        20,
        dm.REPORTS_FIRST,
    ),
    "H-0191": ("swing_limit_up_10d", lambda c: limit_closes(c, up=True, hold_side=1), 10, dm.FIRST),
    "H-0192": ("swing_quiet_accumulation_20d", accumulation, 20, dm.FIRST),
    "H-0193": ("swing_vix_jump_losers_10d", vix_losers, 10, dm.FIRST),
}


def _window(ctx: Context, first: date) -> list[date]:
    return [d for d in ctx.sessions if first <= d <= dm.END]


def evaluate(ctx: Context) -> list[dict[str, Any]]:
    runs = []
    for h, (run_id, events, first) in DAY_RULES.items():
        trades = dm.day_book(ctx, events(ctx))
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
                **du._summary(trades, _window(ctx, first), dm.CAPITAL),
            }
        )
    for h, (run_id, events, hold, first) in SWING_RULES.items():
        swings = dm.swing_book(ctx, events(ctx), hold)
        net = [(s.gross_total - sum(s.costs_at())) / s.notional * 1e4 for s in swings]
        runs.append(
            {
                "hypothesis": h,
                "id": run_id,
                "positions": len(swings),
                "per_position_bps": {"net_mean": round(statistics.fmean(net), 2) if net else None},
                **du._summary(
                    [p for s in swings for p in s.pieces()], _window(ctx, first), dm.CAPITAL
                ),
            }
        )
    return runs


def validation_run(hypothesis: str) -> IntradayRun:
    from eulerlab.validation.intraday import IntradayRun

    ctx = Context()
    if hypothesis in DAY_RULES:
        _, events, first = DAY_RULES[hypothesis]
        return IntradayRun(dm.day_book(ctx, events(ctx)), [], _window(ctx, first), dm.CAPITAL)
    _, events, hold, first = SWING_RULES[hypothesis]
    pieces = [p for s in dm.swing_book(ctx, events(ctx), hold) for p in s.pieces()]
    return IntradayRun(pieces, [], _window(ctx, first), dm.CAPITAL)


def passes(one: Mapping[str, Any]) -> bool:
    return dm.passes(one)


def main() -> int:
    parser = argparse.ArgumentParser(prog="new-signals")
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    runs = evaluate(Context())
    args.output.write_text(
        json.dumps({"research": "178", "spent_trials": 0, "runs": runs}, indent=1)
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
