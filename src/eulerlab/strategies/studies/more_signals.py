"""Four more signals on every liquid NSE stock (research 179, H-0194 to H-0197).

Research 178's frame and books (`new_signals_screen`, `daily_more_screen`):

- **H-0194** a 3% gap with no NSE filing since the previous close: fade, open to close.
- **H-0195** a SAST promoter sale: short the next session, open to close.
- **H-0196** a dividend ex-date ten sessions ahead: buy, sell at the close before it.
- **H-0197** a new 250-session low on half the usual delivery: buy next day, open to close.

`make more-signals` writes `data/derived/more_signals.json`.
"""

from __future__ import annotations

import argparse
import bisect
import json
import statistics
from collections import defaultdict
from collections.abc import Callable, Mapping
from datetime import date, datetime, time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from eulerlab.paths import data_path

if TYPE_CHECKING:
    from eulerlab.validation.intraday import IntradayRun

from eulerlab.strategies.studies import daily_more as dm
from eulerlab.strategies.studies import daily_universe as du
from eulerlab.strategies.studies import new_signals as ns
from eulerlab.strategies.studies import onex as onex

OUT = data_path("derived/more_signals.json")
CORP_MANIFEST = data_path("landing/nse/manifest.jsonl")
Event = dm.Event


def promoter_sales(sessions: list[date]) -> dict[str, dict[date, float]]:
    """{symbol: {first session after the disclosure: % sold}} for promoter sales."""
    from eulerlab.strategies.studies import nse_reports as rep

    out: dict[str, dict[date, float]] = defaultdict(dict)
    for _, text in rep.report_files("sast", rep.FIRST_DAY):
        for row in json.loads(text).get("data") or []:
            if row.get("promoterType") != "Y" or row.get("acqSaleType") != "Sale":
                continue
            try:
                when = datetime.strptime(str(row.get("timestamp")), "%d-%b-%Y %H:%M").replace(
                    tzinfo=rep.IST
                )
            except ValueError:
                continue
            target = rep.session_after(sessions, when)
            symbol = str(row.get("symbol") or "")
            if target is not None and symbol:
                share = rep._number(str(row.get("totSaleShare") or row.get("totAcqShare") or ""))
                out[symbol][target] = max(out[symbol].get(target, 0.0), share)
    return out


def dividend_exdates() -> dict[str, list[date]]:
    """{symbol: ex-dates of dividends} from NSE's corporate-actions feed."""
    from eulerlab.ingest import landing_reader

    out: dict[str, set[date]] = defaultdict(set)
    for line in CORP_MANIFEST.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry.get("segment") != "corp_actions":
            continue
        for row in json.loads(landing_reader.read(f"nse/{entry['path']}")):
            if row.get("series") != "EQ" or "dividend" not in str(row.get("subject", "")).lower():
                continue
            try:
                ex = (
                    datetime.strptime(str(row.get("exDate")), "%d-%b-%Y")
                    .replace(tzinfo=onex.IST)
                    .date()
                )
            except ValueError:
                continue
            out[str(row.get("symbol"))].add(ex)
    return {s: sorted(v) for s, v in out.items()}


class Context(ns.Context):
    def __init__(self) -> None:
        super().__init__()
        self.news = onex.load_news(set(self.panel))
        self.sales = promoter_sales(self.sessions)
        self.dividends = dividend_exdates()


def no_news_gaps(ctx: Context) -> list[Event]:
    out: list[Event] = []
    for day in ctx.sessions:
        p = ctx.prev(day)
        if p is None or not dm.REPORTS_FIRST <= day <= dm.END:
            continue
        start, end = onex._at(p, time(15, 30)), onex._at(day, time(9, 15))
        for symbol in ctx.liquid.get(day, frozenset()):
            g = dm._gap(ctx, symbol, day)
            if g is None or abs(g) < 0.03 or not ctx.tradable(symbol, day):
                continue
            if onex.had_news(ctx.news.get(symbol, ()), start, end):
                continue
            out.append((day, symbol, -1 if g > 0 else 1, -abs(g)))
    return out


def sale_shorts(ctx: Context) -> list[Event]:
    return [
        (day, symbol, -1, -share)
        for symbol, days in ctx.sales.items()
        for day, share in days.items()
        if dm.REPORTS_FIRST <= day <= dm.END and ctx.tradable(symbol, day)
    ]


def dividend_runups(ctx: Context) -> list[tuple[date, str, int]]:
    """(entry day, symbol, sessions held) for buys ten sessions before an ex-date."""
    out = []
    for symbol, exdates in ctx.dividends.items():
        for ex in exdates:
            i = bisect.bisect_left(ctx.sessions, ex)
            if i < 10 or i >= len(ctx.sessions):
                continue
            entry = ctx.sessions[i - 10]
            if dm.FIRST <= entry <= dm.END and ctx.tradable(symbol, entry):
                out.append((entry, symbol, 9))  # out at the close of the session before the ex-date
    return out


def thin_lows(ctx: Context) -> list[Event]:
    out: list[Event] = []
    for symbol, bars in ctx.panel.items():
        days = sorted(bars)
        closes = [bars[d].close for d in days]
        for k in range(251, len(days)):
            p, day = days[k - 1], days[k]
            if not dm.FIRST <= day <= dm.END or ctx.prev(day) != p:
                continue
            if closes[k - 1] > min(closes[k - 251 : k - 1]):
                continue
            ratio = ctx.delivery.get(symbol, {}).get(p)
            if ratio is not None and ratio <= 0.5 and ctx.tradable(symbol, day):
                out.append((day, symbol, 1, ratio))
    return out


DAY_RULES: dict[str, tuple[str, Callable[[Context], list[Event]], date]] = {
    "H-0194": ("daily_no_news_gap_fade", no_news_gaps, dm.REPORTS_FIRST),
    "H-0195": ("daily_promoter_sale_short", sale_shorts, dm.REPORTS_FIRST),
    "H-0197": ("daily_thin_new_low_buy", thin_lows, dm.FIRST),
}


def dividend_book(ctx: Context) -> list[Any]:
    events = [(d, s, 1, 0.0) for d, s, _ in dividend_runups(ctx)]
    return dm.swing_book(ctx, events, 9)


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
                **du._summary(trades, ns._window(ctx, first), dm.CAPITAL),
            }
        )
    swings = dividend_book(ctx)
    net = [(s.gross_total - sum(s.costs_at())) / s.notional * 1e4 for s in swings]
    runs.append(
        {
            "hypothesis": "H-0196",
            "id": "swing_dividend_runup",
            "positions": len(swings),
            "per_position_bps": {"net_mean": round(statistics.fmean(net), 2) if net else None},
            **du._summary(
                [p for s in swings for p in s.pieces()], ns._window(ctx, dm.FIRST), dm.CAPITAL
            ),
        }
    )
    return runs


def validation_run(hypothesis: str) -> IntradayRun:
    from eulerlab.validation.intraday import IntradayRun

    ctx = Context()
    if hypothesis in DAY_RULES:
        _, events, first = DAY_RULES[hypothesis]
        return IntradayRun(dm.day_book(ctx, events(ctx)), [], ns._window(ctx, first), dm.CAPITAL)
    pieces = [p for s in dividend_book(ctx) for p in s.pieces()]
    return IntradayRun(pieces, [], ns._window(ctx, dm.FIRST), dm.CAPITAL)


def passes(one: Mapping[str, Any]) -> bool:
    return dm.passes(one)


def main() -> int:
    parser = argparse.ArgumentParser(prog="more-signals")
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    runs = evaluate(Context())
    args.output.write_text(
        json.dumps({"research": "179", "spent_trials": 0, "runs": runs}, indent=1)
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
