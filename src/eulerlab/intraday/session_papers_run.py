"""`make intraday-papers` — run research 071's two papers on NIFTYBEES and report.

Reads the Kite minute archive through `intraday.store.fetch` and writes
`data/derived/intraday_papers.json`. Each rule is run with the exit the paper
states and with the exit a broker allows, and each at three cost levels:
gross, after NSE charges, and after charges plus slippage (A-052).

Screening runs of published settings: no trial is recorded in the ledger.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections.abc import Callable, Sequence
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import Any

from eulerlab.intraday import session_papers as sp

OUT = Path("data/derived/intraday_papers.json")
SYMBOL = "NIFTYBEES"
CAPITAL = 1_000_000.0
SPLIT = date(2024, 1, 1)

Runner = Callable[[Sequence[sp.Session], sp.CostFn, float], sp.Result]


def _gao(signal: str, exit_at: int | None) -> Runner:
    def run(days: Sequence[sp.Session], cost: sp.CostFn, slip: float) -> sp.Result:
        return sp.gao_timing(
            days, signal=signal, exit_at=exit_at, capital=CAPITAL, cost=cost, slippage_bps=slip
        )

    return run


def _noise(vwap_stop: bool, exit_at: int | None) -> Runner:
    def run(days: Sequence[sp.Session], cost: sp.CostFn, slip: float) -> sp.Result:
        return sp.noise_area(
            days,
            vwap_stop=vwap_stop,
            exit_at=exit_at,
            capital=CAPITAL,
            cost=cost,
            slippage_bps=slip,
        )

    return run


def predictive_regressions(days: Sequence[sp.Session]) -> dict[str, Any]:
    """The paper's eq. (2): the last half-hour return on r1, and on r12.

    Returns slope, R-squared, t and n for each, on 15:00 to 15:24 — traded
    prices at both ends. The official close is a 30-minute VWAP, so a return
    measured to it is partly the same prices as the 15:00 mark. This is the
    claim under the strategy; the strategy can only be as good as this is.
    """
    r1s, r12s, r13s = [], [], []
    for previous, session in pairwise(days):
        if abs(session.anchor / previous.settle - 1) > sp.MAX_OVERNIGHT_GAP:
            continue
        r1, r12 = sp.gao_signals(previous.settle, session)
        exit_fill = session.fill_at(sp.TRADABLE_EXIT)
        if exit_fill is None:
            continue
        r1s.append(r1)
        r12s.append(r12)
        r13s.append(exit_fill[1] / session.close[sp.LAST_HALF_HOUR_START - 1] - 1)

    def fit(xs: list[float]) -> dict[str, Any]:
        slope, intercept = statistics.linear_regression(xs, r13s)
        r = statistics.correlation(xs, r13s)
        n = len(xs)
        return {
            "slope": round(slope, 4),
            "t": round(r * ((n - 2) / (1 - r * r)) ** 0.5, 2),
            "intercept_bps": round(intercept * 1e4, 3),
            "r_squared": round(r * r, 5),
            "n": len(xs),
        }

    return {"r13_on_r1": fit(r1s), "r13_on_r12": fit(r12s)}


def official_closes(
    symbol: str, path: Path = Path("data/derived/price_panel.jsonl")
) -> dict[date, float]:
    """The exchange's closing price per day, from the price panel (raw closes).

    The panel is 745 MB of JSON lines; only lines naming the symbol are parsed.
    """
    out: dict[date, float] = {}
    if not path.exists():
        return out
    needle = f'"s": "{symbol}"'
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if needle in line:
                row = json.loads(line)
                out[date.fromisoformat(row["d"])] = float(row["c"])
    return out


def rules() -> list[tuple[str, str, Runner]]:
    """(paper, rule, runner) for every configuration the papers publish."""
    out: list[tuple[str, str, Runner]] = []
    for label, exit_at in (("published", None), ("tradable", sp.TRADABLE_EXIT)):
        for signal in ("r1", "r12", "both"):
            rule = f"last half-hour on {signal}, {label} exit"
            out.append(("gao-2018", rule, _gao(signal, exit_at)))
        for vwap_stop, name in ((False, "opposite-band stop"), (True, "band+VWAP stop")):
            rule = f"noise area, {name}, {label} exit"
            out.append(("zarattini-2024", rule, _noise(vwap_stop, exit_at)))
    return out


def main(argv: Sequence[str] | None = None) -> int:
    from eulerlab.intraday.store import fetch

    parser = argparse.ArgumentParser(prog="intraday-papers")
    parser.add_argument("--symbol", default=SYMBOL)
    args = parser.parse_args(argv)

    candles = fetch(args.symbol)
    days, skipped = sp.sessions(candles, official=official_closes(args.symbol))
    missing = sum(1 for d in days if d.official_close is None)
    print(
        f"{args.symbol}: {len(candles):,} minute bars, {len(days)} normal sessions "
        f"{days[0].day} to {days[-1].day}, {len(skipped)} special sessions skipped, "
        f"{missing} without an official close"
    )
    regression = predictive_regressions(days)
    for name, fit in regression.items():
        print(
            f"  {name}: slope {fit['slope']}, t {fit['t']}, R2 {fit['r_squared']:.2%}, n {fit['n']}"
        )

    hold = sp.buy_and_hold(days, capital=CAPITAL)
    out: dict[str, Any] = {
        "symbol": args.symbol,
        "window": [days[0].day.isoformat(), days[-1].day.isoformat()],
        "sessions": len(days),
        "sessions_without_official_close": missing,
        "skipped_sessions": [d.isoformat() for d in skipped],
        "capital": CAPITAL,
        "split": SPLIT.isoformat(),
        "slippage_bps_per_side": sp.SLIPPAGE_BPS,
        "spent_trials": 0,
        "regression": regression,
        "buy_and_hold": {
            "whole": hold.stats(),
            "before_2024": hold.stats(end=SPLIT),
            "from_2024": hold.stats(start=SPLIT),
        },
        "runs": [],
    }

    header = (
        f"{'rule':<52}{'trades':>7}{'gross':>8}{'costs':>8}{'net':>8}"
        f"{'net tot':>9}{'maxDD':>8}{'hit':>6}{'bps/tr':>8} | {'<2024':>7}{'2024+':>7}"
    )
    print("\n" + header + "\n" + "-" * len(header))
    for paper, rule, runner in rules():
        gross = runner(days, sp.no_cost, 0.0)
        charged = runner(days, sp.nse_intraday_cost, 0.0)
        net = runner(days, sp.nse_intraday_cost, sp.SLIPPAGE_BPS)
        whole, before, after = net.stats(), net.stats(end=SPLIT), net.stats(start=SPLIT)
        out["runs"].append(
            {
                "paper": paper,
                "rule": rule,
                "gross": gross.stats(),
                "gross_before_2024": gross.stats(end=SPLIT),
                "gross_from_2024": gross.stats(start=SPLIT),
                "after_charges": charged.stats(),
                "net": whole,
                "net_before_2024": before,
                "net_from_2024": after,
                "skipped": net.skipped,
                "daily": [[d.isoformat(), round(r, 6)] for d, r in net.days],
            }
        )
        g, c = gross.stats(), charged.stats()
        print(
            f"{rule:<52}{whole['trades']:>7}"
            f"{g['sharpe'] or 0:>8.2f}{c['sharpe'] or 0:>8.2f}{whole['sharpe'] or 0:>8.2f}"
            f"{whole['total_return']:>9.1%}"
            f"{whole['max_drawdown']:>8.1%}{whole['hit_rate'] or 0:>6.0%}"
            f"{g['gross_bps_per_trade'] or 0:>8.2f} | "
            f"{before.get('sharpe') or 0:>7.2f}{after.get('sharpe') or 0:>7.2f}"
        )
    h = out["buy_and_hold"]["whole"]
    print(
        f"\nbuy and hold: Sharpe {h['sharpe']}, total {h['total_return']:.1%}, "
        f"max drawdown {h['max_drawdown']:.1%}"
    )
    print("gross/costs/net are Sharpe ratios: no costs, NSE charges, charges + slippage")
    print("bps/tr is the gross profit per trade in basis points of traded value")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
