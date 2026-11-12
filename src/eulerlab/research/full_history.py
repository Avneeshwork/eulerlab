"""`make full-history` — the gate's PROMOTE and PAPER hypotheses over every year held (ADR-143).

Operator, 2026-11-06: "backtest all these strategies over all available
timeframe", "from 2016 to 2026", and "in backtest the recommended selection
should already be filled up". Each strategy runs from 2016 (daily) or from the
first minute bar, 2021-08-20 (intraday), to the holdout end in `mandate.yaml`
(2026-10-17). Minute and daily data after that are the forward evidence the
paper books read, so they stay out.

**This reads the holdout.** Data from 2024-12 to 2026-10 was the one-read
holdout. The operator chose to read it for all fifteen strategies, knowing it
spends the project's only read; `--read-holdout OPERATOR` records one read per
hypothesis in `holdout_reads.jsonl`, and nothing runs without it.

Every run is stored in the workspace's result store (`results.record`) with
the settings it used, so the library shows it the moment a strategy is opened,
and `RECOMMENDED` is the setting the console fills in for each strategy.

- **Daily cards** (H-0001, H-0020 to H-0029): each configuration through the
  event-driven engine on the daily panel, a year of warm-up from 2015.
- **H-0096** first F&O ban day short, 09:20-15:10, ten ₹1 lakh slots.
- **H-0098** the same rule on daily bars, official open to close, from 2016.
- **H-0065** overnight winners reverse by day, two deciles, ₹80 lakh.
- **H-0052** NIFTYBEES 09:20-15:10 before a market holiday.

Intraday net returns use cash-intraday charges plus 2 bps a side
(`cross_section.Trade.costs`), as in their research.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

import yaml

from eulerlab.paths import data_path

OUT = data_path("derived/full_history.json")
DAILY_FIRST = date(2016, 1, 1)
WARMUP_FROM = date(2015, 1, 1)
MINUTE_FIRST = date(2021, 8, 20)
DAILY_CARDS = (
    "H-0001",
    "H-0020",
    "H-0021",
    "H-0022",
    "H-0023",
    "H-0024",
    "H-0025",
    "H-0026",
    "H-0027",
    "H-0028",
    "H-0029",
)
INTRADAY = ("H-0096", "H-0098", "H-0065", "H-0052")
CAPITAL = {"H-0065": 8_000_000.0}
"""Capital per strategy; ₹10 lakh unless named (H-0065 holds about 80 names a day)."""
DEFAULT_CAPITAL = 1_000_000.0


def recommended(hypothesis: str, end: date) -> dict[str, Any]:
    """The backtest setting the console fills in when this strategy is opened."""
    minute = hypothesis in INTRADAY and hypothesis != "H-0098"
    start = MINUTE_FIRST if minute else DAILY_FIRST
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "window_days": (end - start).days,
        "universe": "all",
        "tier": "B",
        "asset_class": "equity",
        "timeframe": "1m" if minute else "1d",
        "capital": CAPITAL.get(hypothesis, DEFAULT_CAPITAL),
    }


RECOMMENDED_PATH = data_path("derived/full_history_recommended.json")


def load_recommended(path: Path = RECOMMENDED_PATH) -> dict[str, dict[str, Any]]:
    """{hypothesis: setting} written by the last run, for the console. {} before any run."""
    if not path.exists():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


# --- the statistics of one series ---------------------------------------------------


def summarise(days: Sequence[date], equity: Sequence[float]) -> dict[str, Any]:
    """Sharpe, total return, drawdown and each year's net return from an equity curve."""
    from eulerlab.validation.statistics import sharpe_stats

    returns = [b / a - 1.0 for a, b in pairwise(equity) if a]
    peak, worst = equity[0] if equity else 0.0, 0.0
    for value in equity:
        peak = max(peak, value)
        if peak:
            worst = min(worst, value / peak - 1.0)
    years: dict[str, list[float]] = defaultdict(list)
    for day, value in zip(days[1:], returns, strict=False):
        years[str(day.year)].append(value)
    by_year = {y: round(math.prod(1.0 + r for r in v) - 1.0, 4) for y, v in sorted(years.items())}
    return {
        "sharpe": round(sharpe_stats(returns).sharpe, 4),
        "total_return": round(equity[-1] / equity[0] - 1.0, 6) if equity else 0.0,
        "max_drawdown": round(worst, 6),
        "first": days[0].isoformat() if days else None,
        "last": days[-1].isoformat() if days else None,
        "net_by_year": by_year,
        "years_positive": f"{sum(1 for v in by_year.values() if v > 0)} of {len(by_year)}",
    }


def curve_from_trades(
    trades: Sequence[Any], sessions: Sequence[date], capital: float
) -> tuple[list[date], list[float]]:
    """Equity over every session from same-day trades: net P&L added on its day."""
    pnl: dict[date, float] = defaultdict(float)
    for trade in trades:
        pnl[trade.day] += trade.gross - trade.costs
    equity, value = [], capital
    for day in sessions:
        value += pnl.get(day, 0.0)
        equity.append(value)
    return list(sessions), equity


def as_trades(rows: Sequence[dict[str, Any]]) -> list[Any]:
    """`rule_book` trade dicts as `cross_section.Trade`, so costs are the research ones."""
    from eulerlab.intraday import cross_section as cs

    return [
        cs.Trade(
            r["symbol"],
            r["day"],
            r["direction"],
            r["quantity"],
            r["minute"],
            r["entry"],
            355,
            r["exit"],
            "time_exit",
        )
        for r in rows
    ]


def leg_fills(trades: Sequence[Any]) -> list[Any]:
    """Each same-day trade as its two fills, for the report: in, then out, costs split."""
    from eulerlab.backtest.events import Fill
    from eulerlab.costs.schedule import Side

    out = []
    for t in trades:
        opening = Side.BUY if t.direction > 0 else Side.SELL
        closing = Side.SELL if opening is Side.BUY else Side.BUY
        half = t.costs / 2.0
        out.append(Fill("", t.day, t.symbol, opening, t.quantity, t.entry, half))
        out.append(Fill("", t.day, t.symbol, closing, t.quantity, t.exit, half))
    return out


# --- each kind of strategy ---------------------------------------------------------------


def daily_card(
    hypothesis: str, rows: Sequence[Any], capital: float, root: Path
) -> list[dict[str, Any]]:
    """Every configuration of one rank-and-hold card through the event-driven engine."""
    from eulerlab.backtest import event_driven
    from eulerlab.validation import run as validation

    card = yaml.safe_load((root / f"{hypothesis}.yaml").read_text(encoding="utf-8")) or {}
    out = []
    for config in card.get("configurations") or []:
        strategy, rebalance = validation._strategy_for(config)
        result = event_driven.run(
            rows,
            strategy,
            starting_cash=capital,
            rebalance_every=rebalance,
            warmup=253,
            asset_class="equity",
        )
        pairs = [
            (d, e) for d, e in zip(result.days, result.equity, strict=True) if d >= DAILY_FIRST
        ]
        days, equity = [d for d, _ in pairs], [e for _, e in pairs]
        out.append(
            {
                "configuration": validation._label(config),
                "fills": len(result.fills),
                "symbols": len({f.symbol for f in result.fills}),
                **summarise(days, equity),
                "curve_days": days,
                "curve": equity,
                "_fills": list(result.fills),
            }
        )
    return out


def ban_short(end: date, capital: float, *, daily: bool) -> dict[str, Any]:
    from eulerlab.deploy import rule_book
    from eulerlab.intraday import cash_five_screen as five
    from eulerlab.intraday import cross_section as cs
    from eulerlab.intraday import nse_reports_screen as rep

    first = DAILY_FIRST if daily else MINUTE_FIRST
    lists = dict(rep._parsed("fo_ban", rep.ban_list, first - timedelta(days=10), end))
    bans = rep.ban_events(lists)
    if daily:
        bars = rep.daily_bars(set(bans))
        sessions = sorted({d for b in bars.values() for d in b if first <= d <= end})
        trades = [t for t in rep.daily_ban_trades(bans, bars) if first <= t.day <= end]
        # The research sized ₹1 lakh a name; scale to this capital's ten slots.
        scale = capital / (five.TRADE * five.MAX_OPEN)
        trades = [
            cs.Trade(
                t.symbol,
                t.day,
                t.direction,
                int(t.quantity * scale),
                t.entry_minute,
                t.entry,
                t.exit_minute,
                t.exit,
                t.reason,
            )
            for t in trades
        ]
    else:
        entries = {
            d: sorted(names)
            for d, names in rule_book.first_ban_days(lists, after=first).items()
            if d <= end
        }
        rows, sessions = rule_book.ban_trades(
            entries,
            lambda s: rule_book._days(s, since=first - timedelta(days=2), through=end),
            capital,
            auction=False,
        )
        trades = as_trades(rows)
        sessions = [d for d in sessions if first <= d <= end]
    days, equity = curve_from_trades(trades, sessions, capital)
    return {
        "fills": 2 * len(trades),
        "symbols": len({t.symbol for t in trades}),
        **summarise(days, equity),
        "curve_days": days,
        "curve": equity,
        "_fills": leg_fills(trades),
    }


def overnight_reversal(end: date, capital: float, sessions: Sequence[date]) -> dict[str, Any]:
    from eulerlab.deploy import rule_book
    from eulerlab.intraday import cross_section as cs
    from eulerlab.intraday import overnight_reversal_screen as overnight
    from eulerlab.intraday import research_screen as rs

    marks: dict[str, dict[date, Any]] = {}
    for symbol in cs.universe():
        marks[symbol] = overnight.extract(symbol, rs.load_days(symbol, cutoff=end, cache=False))
    trades = as_trades(
        rule_book.overnight_trades_from_marks(marks, start=MINUTE_FIRST, capital=capital)
    )
    days, equity = curve_from_trades(trades, sessions, capital)
    return {
        "fills": 2 * len(trades),
        "symbols": len({t.symbol for t in trades}),
        **summarise(days, equity),
        "curve_days": days,
        "curve": equity,
        "_fills": leg_fills(trades),
    }


def pre_holiday(end: date, capital: float, calendar: Sequence[date]) -> dict[str, Any]:
    from eulerlab.deploy import rule_book
    from eulerlab.intraday import cash_events_screen as events
    from eulerlab.intraday import research_screen as rs

    holidays = set(events.pre_holiday_days(calendar))
    etf = rs.load_days(rule_book.ETF, cutoff=end, cache=False)
    rows: list[dict[str, Any]] = []
    for bars in etf:
        prices = rule_book._fills(bars, rule_book.ENTRY, rule_book.EXIT)
        if bars.day in holidays and prices and (quantity := int(capital / prices[0])):
            rows.append(
                rule_book._trade(bars.day, rule_book.ETF, 1, quantity, *prices, rule_book.ENTRY)
            )
    trades = as_trades(rows)
    sessions = [d.day for d in etf if MINUTE_FIRST <= d.day <= end]
    days, equity = curve_from_trades(trades, sessions, capital)
    return {
        "fills": 2 * len(trades),
        "symbols": 1,
        **summarise(days, equity),
        "curve_days": days,
        "curve": equity,
        "_fills": leg_fills(trades),
    }


# --- running -------------------------------------------------------------------------------


def store(
    hypothesis: str,
    run: dict[str, Any],
    setting: dict[str, Any],
    label: str = "",
    marks: dict[str, float] | None = None,
) -> None:
    """The run in the result store, and its full report beside it (`reports.save`)."""
    from eulerlab import reports, results, workspace

    tenant = workspace.resolve(None)
    params = {
        "start": setting["start"],
        "end": setting["end"],
        "capital": setting["capital"],
        "configuration": label,
        "holdout": "read (operator, 2026-11-06)",
    }
    # The configuration label is in the data version so each of a card's
    # configurations is its own stored result, not a recomputation of one.
    version = f"full-history {setting['start']}..{setting['end']} {label}".strip()
    stored = results.Run(
        strategy_id=hypothesis,
        sharpe=float(run["sharpe"]),
        total_return=float(run["total_return"]),
        max_drawdown=float(run["max_drawdown"]),
        fills=int(run["fills"]),
        days=len(run["curve"]),
        tier=setting["tier"],
        window_days=int(setting["window_days"]),
        data_version=version,
        asset_class=setting["asset_class"],
        universe=setting["universe"],
        symbols=int(run["symbols"]),
        params=params,
        curve=results.downsample(list(run["curve"])),
    )
    results.record(tenant, stored)
    reports.save(
        tenant,
        reports.build(
            strategy_id=hypothesis,
            configuration=stored.configuration,
            universe=setting["universe"],
            instruments=[],
            tier=setting["tier"],
            asset_class=setting["asset_class"],
            window_days=int(setting["window_days"]),
            equity=list(run["curve"]),
            days=list(run["curve_days"]),
            fills=list(run.get("_fills") or []),
            rejections=[],
            marks=marks or {},
            starting_cash=float(setting["capital"]),
            params=params,
            data_version=version,
        ),
    )


def run(operator: str, only: Sequence[str] = (), output: Path = OUT) -> dict[str, Any]:
    from eulerlab import gates
    from eulerlab.deploy import intraday_book
    from eulerlab.features.panel import read_panel, trading_days

    end = intraday_book.holdout_end()
    if end is None:
        msg = "no forward_evidence.holdout_end in mandate.yaml"
        raise SystemExit(msg)
    from eulerlab import forward

    order = ("H-0096", "H-0098", "H-0052", *DAILY_CARDS, "H-0065")
    wanted = [h for h in order if not only or h in only]
    already = {r.hypothesis for r in gates.holdout_reads()}
    for hypothesis in wanted:
        if hypothesis not in already:  # one read per strategy, however often it runs
            gates.record_holdout_read(hypothesis, authorised_by=operator)

    rows = [r for r in read_panel() if WARMUP_FROM <= r.day <= end]
    marks: dict[str, float] = {}
    for row in sorted(rows, key=lambda r: r.day):
        marks[row.symbol] = row.close
    calendar = trading_days([r for r in rows if r.symbol == "NIFTYBEES"]) or trading_days(rows)
    minute_sessions = [d for d in trading_days(rows) if MINUTE_FIRST <= d <= end]
    settings = {h: recommended(h, end) for h in (*DAILY_CARDS, *INTRADAY)}
    out: dict[str, Any] = {
        "end": end.isoformat(),
        "holdout": f"read for {len(wanted)} hypotheses by {operator}",
        "runs": {},
    }
    for hypothesis in wanted:
        capital = settings[hypothesis]["capital"]
        print(f"  {hypothesis} ...", flush=True)
        if hypothesis in DAILY_CARDS:
            found = daily_card(hypothesis, rows, capital, forward.HYPOTHESES)
        elif hypothesis == "H-0096":
            found = [{"configuration": "as registered", **ban_short(end, capital, daily=False)}]
        elif hypothesis == "H-0098":
            found = [{"configuration": "as registered", **ban_short(end, capital, daily=True)}]
        elif hypothesis == "H-0065":
            found = [
                {
                    "configuration": "as registered",
                    **overnight_reversal(end, capital, minute_sessions),
                }
            ]
        else:
            found = [{"configuration": "as registered", **pre_holiday(end, capital, calendar)}]
        for one in found:
            store(hypothesis, one, settings[hypothesis], one["configuration"], marks)
        out["runs"][hypothesis] = [
            {k: v for k, v in one.items() if k not in ("curve", "curve_days", "_fills")}
            for one in found
        ]
    # A run of some hypotheses keeps the others' earlier results.
    if output.exists():
        earlier = json.loads(output.read_text(encoding="utf-8")).get("runs") or {}
        out["runs"] = {**earlier, **out["runs"]}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(out, indent=1), encoding="utf-8")
    RECOMMENDED_PATH.write_text(json.dumps(settings, indent=1), encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(prog="full-history")
    parser.add_argument(
        "--read-holdout",
        required=True,
        metavar="OPERATOR",
        help="reads 2024-12 to the holdout end: records one holdout read per hypothesis",
    )
    parser.add_argument("--only", nargs="*", default=[])
    args = parser.parse_args()
    result = run(args.read_holdout, args.only)
    for hypothesis, runs in result["runs"].items():
        for one in runs:
            print(
                f"{hypothesis} {one['configuration'][:40]:<40} Sharpe {one['sharpe']:>6} "
                f"return {one['total_return']:>8.1%} drawdown {one['max_drawdown']:>7.1%} "
                f"years {one['years_positive']} {one['first']}..{one['last']}"
            )
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
