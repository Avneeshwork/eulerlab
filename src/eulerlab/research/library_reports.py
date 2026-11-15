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


def _fills_for(hypothesis: str, run: Any, cut: date | None = None) -> tuple[list[Any], int]:
    """(two fills per position, distinct symbols) for the report; no swing exits on or after `cut`."""
    from eulerlab.backtest.events import Fill
    from eulerlab.costs.schedule import Side
    from eulerlab.intraday import cross_section as cs

    trades = list(run.trades)
    if trades and isinstance(trades[0], cs.Trade):
        return fh.leg_fills(trades), len({t.symbol for t in trades})
    swings = [s for s in _swings(hypothesis) if cut is None or s.exit_day < cut]
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
    from eulerlab.intraday import daily_more_screen as dm
    from eulerlab.intraday import more_signals_screen as ms
    from eulerlab.intraday import new_signals_screen as ns

    if _engine_card(hypothesis):
        from eulerlab.intraday import rule_engine

        spec = rule_engine.card_spec(hypothesis)
        assert spec is not None
        return rule_engine.Engine(rule_engine.Data()).swings(spec)
    if hypothesis == "H-0162":
        from eulerlab.intraday import daily_universe_screen as du

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
        from eulerlab.intraday import other_data_screen as od

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
        one = store_one(hypothesis)
        found.append(one)
        print(
            f"{hypothesis}: stored; Sharpe {one['sharpe']}, total {one['total_return']:.1%}, "
            f"drawdown {one['max_drawdown']:.1%}, {one['years_positive']} years positive"
        )
    add_recommended(found)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
