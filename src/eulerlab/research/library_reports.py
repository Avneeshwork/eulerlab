"""Stored reports for research 166-173's gated strategies, so the library shows them.

Operator, 2026-11-07: "i can't see their report" (H-0161, H-0162). `make
validate` and `make gate` write an evidence pack and a ledger entry but no
stored result, so the Strategies page and the Report page had nothing to show.
This writes, for each gated card, the run on its research window to the
workspace result store with its full report, as `full_history.store` does
(ADR-143), and adds its setting to `full_history_recommended.json` so opening
it fills the backtest controls.

The window is the research window up to the card's own `holdout.starts`: the
trade sources run to the research window's end (2025-12-31 since ADR-184),
past the holdout start, so `store_one` cuts every trade, session and swing at
that date (ADR-199). A swing still open on the holdout start is left out.

Any card with a trade source (`validation.intraday.source`) can be stored:
`--only H-xxxx ...`, or `--from-results results.jsonl` for every card a
rebacktest scored. The library shows a strategy's latest run (`results.latest`),
so a new store replaces the old report on screen; the append-only result log
keeps the old row.

`make library-reports` runs it; it spends no trial.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from eulerlab.research import full_history as fh

CARDS = (
    "H-0194",
    "H-0186",
    "H-0191",
    "H-0065",
    "H-0187",
    "H-0185",
    "H-0168",
    "H-0161",
    "H-0162",
    "H-0160",
    "H-0153",
    "H-0146",
    "H-0132",
    "H-0118",
    "H-0121",
    "H-0115",
    "H-0124",
)
"""PROMOTE and PAPER stock cards of research 168-173 (H-0103 is an option rule, out of scope)."""
TIMEFRAME = {
    "H-0161": "1d",
    "H-0162": "1d",
    "H-0153": "1d",
    "H-0168": "1d",
    "H-0187": "1d",
    "H-0185": "1d",
    "H-0186": "1d",
    "H-0191": "1d",
    "H-0194": "1d",
}

ALL_NSE = (
    *(f"H-0{n}" for n in range(161, 174)),
    *(f"H-0{n}" for n in range(184, 198)),
)
"""Daily rules on the 500 most traded NSE stocks (research 173, 176, 178, 179)."""

MINUTE = frozenset(
    {"H-0052", "H-0065", "H-0096", "H-0106", *(f"H-0{n}" for n in range(111, 161))} - {"H-0153"}
)
"""Trade sources on minute bars or 5-minute snapshots; every other source is daily."""

NOTES = {
    "H-0194": (
        "Overstated about 2x. Its five best names were ETFs with stale opening prints; "
        "without ETFs +97.7 bps net, Sharpe 6.05. On F&O stocks with minute data the gap "
        "fade made 87.4 bps gross from the official open but 41.2 bps from 09:20 "
        "(research 180). The live-price paper shadow is the test."
    ),
}
"""Caveats stored with a report, shown beside its figures."""


NO_POSITIONS = (
    "Equity curve and Sharpe are the gated run's; its individual positions are not rebuilt "
    "for this report, so the trade and instrument tabs are empty (ADR-206)."
)


def _fills_for(hypothesis: str, run: Any, cut: date | None = None) -> tuple[list[Any], int]:
    """(two fills per position, distinct symbols) for the report; no swing exits on or after `cut`."""
    from eulerlab.backtest.events import Fill
    from eulerlab.costs.schedule import Side
    from eulerlab.intraday import cross_section as cs

    trades = list(run.trades)
    if trades and isinstance(trades[0], cs.Trade):
        return fh.leg_fills(trades), len({t.symbol for t in trades})
    try:
        known = _swings(hypothesis)
    except KeyError:
        # No screen rebuilds this card's positions (H-0151, the portfolio cards):
        # the report keeps the gate's daily curve and Sharpe without per-position
        # fills, and says so (`NO_POSITIONS`), rather than not existing at all.
        return [], 0
    swings = [s for s in known if cut is None or s.exit_day < cut]
    out = []
    for s in swings:
        buy, sell = s.costs_at()
        out.append(Fill("", s.entry_day, s.symbol, Side.BUY, s.quantity, s.entry, buy))
        out.append(Fill("", s.exit_day, s.symbol, Side.SELL, s.quantity, s.exit, sell))
    return out, len({s.symbol for s in swings})


def _engine_card(hypothesis: str) -> bool:
    from eulerlab.intraday import rule_engine

    try:
        return rule_engine.card_spec(hypothesis) is not None
    except ValueError:
        return False


def _swings(hypothesis: str) -> list[Any]:
    """The positions behind a swing card's daily pieces, from the screen that made them."""
    from eulerlab.strategies.studies import daily_more as dm
    from eulerlab.strategies.studies import more_signals as ms
    from eulerlab.strategies.studies import new_signals as ns

    if _engine_card(hypothesis):
        from eulerlab.intraday import rule_engine

        spec = rule_engine.card_spec(hypothesis)
        assert spec is not None
        return rule_engine.Engine(rule_engine.Data()).swings(spec)
    if hypothesis == "H-0162":
        from eulerlab.strategies.studies import daily_universe as du

        ctx = du.Context()
        return du.h0162_positions(ctx.panel, ctx.sessions, ctx.liquid, ctx.promoters)
    if hypothesis in ns.SWING_RULES:
        signals = ns.Context()
        _, events, hold, _ = ns.SWING_RULES[hypothesis]
        return list(dm.swing_book(signals, events(signals), hold))
    if hypothesis in dm.SWING_RULES:
        frame = dm.Context()
        _, found, hold, _ = dm.SWING_RULES[hypothesis]
        return list(dm.swing_book(frame, found(frame), hold))
    if hypothesis == "H-0196":
        return list(ms.dividend_book(ms.Context()))
    if hypothesis == "H-0153":
        from eulerlab.strategies.studies import other_data as od

        return list(od.h0153(od._context()))
    msg = f"{hypothesis}: no swing positions known for its trades"
    raise KeyError(msg)


def holdout_start(hypothesis: str, root: Path = Path("hypotheses")) -> date:
    """The card's `holdout.starts`; a report never reaches it."""
    card = yaml.safe_load((root / f"{hypothesis}.yaml").read_text(encoding="utf-8"))
    raw = (card.get("holdout") or {}).get("starts")
    if not raw:
        msg = f"{hypothesis} declares no holdout start"
        raise ValueError(msg)
    return date.fromisoformat(str(raw)[:10])


def before(run: Any, cut: date) -> Any:
    """`run` with every session and trade on or after `cut` removed."""
    from eulerlab.validation.intraday import IntradayRun

    return IntradayRun(
        [t for t in run.trades if t.day < cut],
        [t for t in run.late_trades if t.day < cut],
        [d for d in run.sessions if d < cut],
        run.capital,
    )


def curve(run: Any) -> tuple[list[date], list[float]]:
    pnl: dict[date, float] = defaultdict(float)
    for t in run.trades:
        pnl[t.day] += t.gross - t.costs
    value, equity = float(run.capital), []
    for day in run.sessions:
        value += pnl.get(day, 0.0)
        equity.append(value)
    return list(run.sessions), equity


def setting(hypothesis: str, sessions: Sequence[date], capital: float) -> dict[str, Any]:
    start, end = sessions[0], sessions[-1]
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "window_days": (end - start).days,
        "universe": "nse_500_most_traded"
        if hypothesis in ALL_NSE or _engine_card(hypothesis)
        else "fo_stocks",
        "tier": "B",
        "asset_class": "equity",
        "timeframe": "1d"
        if _engine_card(hypothesis)
        else TIMEFRAME.get(hypothesis, "1m" if hypothesis in MINUTE else "1d"),
        "capital": capital,
    }


def store_one(hypothesis: str) -> dict[str, Any]:
    from eulerlab import reports, results, workspace
    from eulerlab.validation import intraday

    cut = holdout_start(hypothesis)
    run = before(intraday.source(hypothesis)(), cut)
    days, equity = curve(run)
    fills, symbols = _fills_for(hypothesis, run, cut)
    summary = fh.summarise(days, equity)
    chosen = setting(hypothesis, days, float(run.capital))
    params = {
        "start": chosen["start"],
        "end": chosen["end"],
        "capital": chosen["capital"],
        "configuration": "as gated",
        "holdout": f"unread (research window only, before {cut.isoformat()})",
    }
    if hypothesis in NOTES:
        params["caveat"] = NOTES[hypothesis]
    elif not fills:
        params["caveat"] = NO_POSITIONS
    version = f"research-window {chosen['start']}..{chosen['end']} as gated"
    stored = results.Run(
        strategy_id=hypothesis,
        sharpe=float(summary["sharpe"]),
        total_return=float(summary["total_return"]),
        max_drawdown=float(summary["max_drawdown"]),
        fills=len(fills),
        days=len(equity),
        tier=chosen["tier"],
        window_days=int(chosen["window_days"]),
        data_version=version,
        asset_class=chosen["asset_class"],
        universe=chosen["universe"],
        symbols=symbols,
        params=params,
        curve=results.downsample(list(equity)),
    )
    tenant = workspace.resolve(None)
    results.record(tenant, stored)
    reports.save(
        tenant,
        reports.build(
            strategy_id=hypothesis,
            configuration=stored.configuration,
            universe=chosen["universe"],
            instruments=[],
            tier=chosen["tier"],
            asset_class=chosen["asset_class"],
            window_days=int(chosen["window_days"]),
            equity=equity,
            days=days,
            fills=fills,
            rejections=[],
            marks={},
            starting_cash=float(chosen["capital"]),
            params=params,
            data_version=version,
        ),
    )
    return {"hypothesis": hypothesis, "setting": chosen, **summary, "fills": len(fills)}


def is_factor_card(hypothesis: str, root: Path = Path("hypotheses")) -> bool:
    """A card whose every configuration is a daily rank-and-hold book (idea-lab and factor cards)."""
    from eulerlab.validation import intraday

    if hypothesis in intraday.SOURCES or _engine_card(hypothesis):
        return False
    card = yaml.safe_load((root / f"{hypothesis}.yaml").read_text(encoding="utf-8")) or {}
    configs = card.get("configurations") or []
    return bool(configs) and all(
        c.get("shape") in (None, "rank_and_hold") and c.get("feature") for c in configs
    )


def store_factor(
    hypothesis: str, rows: Sequence[Any] | None = None, root: Path = Path("hypotheses")
) -> list[dict[str, Any]]:
    """Each configuration of a rank-and-hold card, 2016 to its holdout start, stored (ADR-206).

    The same event-driven run `make full-history` stores (`full_history.daily_card`,
    a year of warm-up from 2015), cut before the card's `holdout.starts`, so the
    holdout stays unread. One stored result per configuration.
    """
    from eulerlab.features.panel import read_panel

    cut = holdout_start(hypothesis, root)
    if rows is None:
        rows = [r for r in read_panel() if fh.WARMUP_FROM <= r.day < cut]
    else:
        rows = [r for r in rows if r.day < cut]
    marks: dict[str, float] = {}
    for row in sorted(rows, key=lambda r: r.day):
        marks[row.symbol] = row.close
    out = []
    for one in fh.daily_card(hypothesis, rows, fh.DEFAULT_CAPITAL, root):
        days = one["curve_days"]
        chosen = {
            "start": days[0].isoformat(),
            "end": days[-1].isoformat(),
            "window_days": (days[-1] - days[0]).days,
            "universe": "all",
            "tier": "B",
            "asset_class": "equity",
            "timeframe": "1d",
            "capital": fh.DEFAULT_CAPITAL,
        }
        fh.store(
            hypothesis,
            one,
            chosen,
            one["configuration"],
            marks,
            holdout=f"unread (research window only, before {cut.isoformat()})",
            kind="research-window",
        )
        out.append(
            {
                "hypothesis": hypothesis,
                "setting": chosen,
                "configuration": one["configuration"],
                "sharpe": one["sharpe"],
                "total_return": one["total_return"],
                "max_drawdown": one["max_drawdown"],
                "years_positive": one.get("years_positive"),
                "fills": one["fills"],
            }
        )
    return out


def store_card(hypothesis: str) -> list[dict[str, Any]]:
    """Any gated card's report: a rank-and-hold card by `store_factor`, the rest by `store_one`."""
    if is_factor_card(hypothesis):
        return store_factor(hypothesis)
    return [store_one(hypothesis)]


def add_recommended(found: Sequence[dict[str, Any]]) -> None:
    settings = fh.load_recommended()
    for one in found:
        settings[one["hypothesis"]] = one["setting"]
    fh.RECOMMENDED_PATH.write_text(json.dumps(settings, indent=1), encoding="utf-8")


def scored(results_path: Path) -> list[str]:
    """Cards in a rebacktest log with a Sharpe and no error, in file order, each once."""
    out: dict[str, None] = {}
    for line in results_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("sharpe") is not None and not row.get("error"):
            out[str(row["id"])] = None
    return list(out)


def cards(only: Sequence[str] | None, results_path: Path | None) -> list[str]:
    if results_path is not None:
        return [*(only or []), *scored(results_path)]
    return list(only) if only else list(CARDS)


def main() -> int:
    parser = argparse.ArgumentParser(prog="library-reports")
    parser.add_argument("--only", nargs="+", default=None)
    parser.add_argument(
        "--from-results",
        type=Path,
        default=None,
        help="a rebacktest's results.jsonl: store every card it scored without an error",
    )
    args = parser.parse_args()
    found = []
    for hypothesis in cards(args.only, args.from_results):
        for one in store_card(hypothesis):
            found.append(one)
            print(
                f"{hypothesis}: stored; Sharpe {one['sharpe']}, total {one['total_return']:.1%}, "
                f"drawdown {one['max_drawdown']:.1%}, {one['years_positive']} years positive"
            )
    add_recommended(found)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
