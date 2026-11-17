"""Ten paper-backed, market-neutral stock day trades (research 170, H-0131 to H-0140).

Each rule scores the 100 most traded F&O stocks at 09:20 from information
known by then, goes long five and short five, and holds from the open after
the 09:20 close to 15:10 (H-0136: to 10:20). Same market, fills and costs as
`mft_screen` (research 168, ADR-146): ₹5 lakh a position at 5x MIS, ten open
on ₹10 lakh of margin, 8.46 bps a round trip.

A stricter screen was fixed in advance: a rule is gated only if it is net
positive in both halves and at twice the costs.

`make quant-screen` writes `data/derived/quant_screen.json`.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from eulerlab.paths import data_path

if TYPE_CHECKING:
    from eulerlab.validation.intraday import IntradayRun

from eulerlab.intraday import cross_section as cs
from eulerlab.intraday import screen_common as sc
from eulerlab.strategies.studies import cash_five as five
from eulerlab.strategies.studies import mft as mft
from eulerlab.strategies.studies import minute_six as six

OUT = data_path("derived/quant_screen.json")
SIDE = 5
MIN_NAMES = 20
DECIDE = 5
"""09:20, as minutes after 09:15."""
START_52W = date(2022, 9, 1)

Score = Callable[[mft.Market, str, date], float | None]


def back(mk: mft.Market, day: date, n: int) -> list[date]:
    """The `n` sessions before `day`, newest first; shorter if history runs out."""
    out: list[date] = []
    d: date | None = day
    while len(out) < n and d is not None:
        d = mk.prev(d)
        if d is not None:
            out.append(d)
    return out


def _snap(mk: mft.Market, symbol: str, day: date) -> six.Snap | None:
    return mk.snaps.get(symbol, {}).get(day)


def _ret(mk: mft.Market, symbol: str, day: date) -> float | None:
    """Close-to-close return of `day` (last close over the previous session's)."""
    p = mk.prev(day)
    a, b = (_snap(mk, symbol, p) if p else None), _snap(mk, symbol, day)
    if a is None or b is None or a.last_close <= 0:
        return None
    return b.last_close / a.last_close - 1.0


def _nifty_ret(mk: mft.Market, day: date) -> float | None:
    """The Nifty's official close-to-close return on `day`."""
    today, before = mk.nifty_close.get(day), mk.nifty_prev.get(day)
    return today / before - 1.0 if today and before else None


def _gap(mk: mft.Market, symbol: str, day: date) -> float | None:
    p = mk.prev(day)
    a, b = (_snap(mk, symbol, p) if p else None), _snap(mk, symbol, day)
    if a is None or b is None or a.last_close <= 0:
        return None
    return b.closes[mft._k(DECIDE)] / a.last_close - 1.0


def _nifty_gap(mk: mft.Market, day: date) -> float | None:
    prev = mk.nifty_prev.get(day)
    return mk.nifty[day][DECIDE] / prev - 1.0 if prev else None


# --- the ten scores ------------------------------------------------------------------


def s0131(mk: mft.Market, symbol: str, day: date) -> float | None:
    g, n, b = _gap(mk, symbol, day), _nifty_gap(mk, day), mk.beta.get((symbol, day))
    return None if g is None or n is None or b is None else g - b * n


def s0132(mk: mft.Market, symbol: str, day: date) -> float | None:
    gaps = [_gap(mk, symbol, d) for d in back(mk, day, 20)]
    found = [g for g in gaps if g is not None]
    return statistics.fmean(found) if len(found) >= 15 else None


def _residual(mk: mft.Market, symbol: str, day: date, d: date) -> float | None:
    r, n, b = _ret(mk, symbol, d), _nifty_ret(mk, d), mk.beta.get((symbol, day))
    return None if r is None or n is None or b is None else r - b * n


def s0133(mk: mft.Market, symbol: str, day: date) -> float | None:
    p = mk.prev(day)
    return _residual(mk, symbol, day, p) if p else None


def s0134(mk: mft.Market, symbol: str, day: date) -> float | None:
    days = back(mk, day, 21)
    if len(days) < 21:
        return None
    y = _snap(mk, symbol, days[0])
    before = [s.value for d in days[1:] if (s := _snap(mk, symbol, d)) is not None]
    if y is None or len(before) < 15 or statistics.fmean(before) <= 0:
        return None
    return y.value / statistics.fmean(before)


def s0136(mk: mft.Market, symbol: str, day: date) -> float | None:
    moves = []
    for d in back(mk, day, 20):
        s = _snap(mk, symbol, d)
        if s is not None:
            moves.append(s.closes[mft._k(65)] / s.closes[mft._k(DECIDE)] - 1.0)
    return statistics.fmean(moves) if len(moves) >= 15 else None


def s0137(mk: mft.Market, symbol: str, day: date) -> float | None:
    found = [_residual(mk, symbol, day, d) for d in back(mk, day, 5)]
    return sum(f for f in found if f is not None) if all(f is not None for f in found) else None


def s0138(mk: mft.Market, symbol: str, day: date) -> float | None:
    if day < START_52W:
        return None
    days = back(mk, day, 250)
    closes = [s.last_close for d in days if (s := _snap(mk, symbol, d)) is not None]
    if len(closes) < 200 or max(closes) <= 0:
        return None
    return closes[0] / max(closes)


def s0139(mk: mft.Market, symbol: str, day: date) -> float | None:
    days = back(mk, day, 22)
    if len(days) < 22:
        return None
    last, first = _snap(mk, symbol, days[0]), _snap(mk, symbol, days[21])
    if last is None or first is None or first.last_close <= 0:
        return None
    return last.last_close / first.last_close - 1.0


def _turnover(mk: mft.Market, symbol: str, day: date) -> float | None:
    days = back(mk, day, 20)
    values = [s.value for d in days if (s := _snap(mk, symbol, d)) is not None]
    today = _snap(mk, symbol, day)
    if len(values) < 15 or today is None or today.entry <= 0:
        return None
    return statistics.fmean(values) / today.entry


# --- the book ------------------------------------------------------------------------


def _long_short(
    mk: mft.Market,
    day: date,
    scored: list[tuple[float, str]],
    low_long: bool,
    hold: int | None,
    delay: int,
) -> Iterator[mft.Signal]:
    if len(scored) < MIN_NAMES:
        return
    scored.sort()
    low, high = scored[:SIDE], scored[-SIDE:]
    for side, chosen in ((1 if low_long else -1, low), (-1 if low_long else 1, high)):
        for _, symbol in chosen:
            s = mk.snaps[symbol][day]
            sig = mft.held(s, day, symbol, side, DECIDE, hold=hold, delay=delay)
            if sig:
                yield sig


def ranked(
    score: Score, *, low_long: bool, hold: int | None = None
) -> Callable[..., Iterator[mft.Signal]]:
    def rule(mk: mft.Market, day: date, delay: int = 0) -> Iterator[mft.Signal]:
        scored = []
        for symbol in mk.liquid.get(day, [])[:100]:
            if mft._today(mk, symbol, day) is None:
                continue
            value = score(mk, symbol, day)
            if value is not None:
                scored.append((value, symbol))
        yield from _long_short(mk, day, scored, low_long, hold, delay)

    return rule


def h0135(mk: mft.Market, day: date, delay: int = 0) -> Iterator[mft.Signal]:
    p = mk.prev(day)
    if p is None:
        return
    groups: dict[str, list[str]] = defaultdict(list)
    for symbol in mk.liquid.get(day, [])[:200]:  # by traded value, largest first
        if symbol in mk.industry and mft._today(mk, symbol, day) is not None:
            groups[mk.industry[symbol]].append(symbol)
    means = []
    for group, members in sorted(groups.items()):
        rets = [r for m in members if (r := _ret(mk, m, p)) is not None]
        if len(members) >= SIDE and len(rets) >= SIDE:
            means.append((statistics.fmean(rets), group))
    if len(means) < 2:
        return
    means.sort()
    for side, group in ((-1, means[0][1]), (1, means[-1][1])):
        for symbol in groups[group][:SIDE]:
            sig = mft.held(mk.snaps[symbol][day], day, symbol, side, DECIDE, delay=delay)
            if sig:
                yield sig


def h0139(mk: mft.Market, day: date, delay: int = 0) -> Iterator[mft.Signal]:
    pool = []
    for symbol in mk.liquid.get(day, [])[:100]:
        if mft._today(mk, symbol, day) is None:
            continue
        t, r = _turnover(mk, symbol, day), s0139(mk, symbol, day)
        if t is not None and r is not None:
            pool.append((t, r, symbol))
    pool.sort(reverse=True)
    yield from _long_short(mk, day, [(r, sym) for _, r, sym in pool[:20]], False, None, delay)


def h0140(mk: mft.Market, day: date, delay: int = 0) -> Iterator[mft.Signal]:
    gaps: dict[str, float] = {}
    groups: dict[str, list[str]] = defaultdict(list)
    for symbol in mk.liquid.get(day, [])[:200]:
        g = _gap(mk, symbol, day)
        if g is not None and symbol in mk.industry and mft._today(mk, symbol, day):
            gaps[symbol] = g
            groups[mk.industry[symbol]].append(symbol)
    scored = []
    for symbol in mk.liquid.get(day, [])[:100]:
        if symbol not in gaps:
            continue
        peers = [gaps[p] for p in groups[mk.industry[symbol]] if p != symbol]
        if len(peers) >= 4:
            scored.append((gaps[symbol] - statistics.fmean(peers), symbol))
    yield from _long_short(mk, day, scored, True, None, delay)


RULES: dict[str, tuple[str, Callable[..., Iterator[mft.Signal]]]] = {
    "H-0131": ("quant_overnight_gap_reversal", ranked(s0131, low_long=True)),
    "H-0132": ("quant_tug_of_war_mis", ranked(s0132, low_long=True)),
    "H-0133": ("quant_one_day_residual_reversal", ranked(s0133, low_long=True)),
    "H-0134": ("quant_high_volume_premium", ranked(s0134, low_long=False)),
    "H-0135": ("quant_industry_momentum_one_day", h0135),
    "H-0136": ("quant_same_hour_seasonality_open", ranked(s0136, low_long=False, hold=60)),
    "H-0137": ("quant_weekly_residual_reversal", ranked(s0137, low_long=True)),
    "H-0138": ("quant_near_52_week_high", ranked(s0138, low_long=False)),
    "H-0139": ("quant_turnover_short_term_momentum", h0139),
    "H-0140": ("quant_industry_gap_reversal", h0140),
}


def trades_for(mk: mft.Market, hypothesis: str, *, delay: int = 0) -> list[cs.Trade]:
    _, rule = RULES[hypothesis]
    out = []
    for sig in mft.book([s for day in mk.sessions for s in rule(mk, day, delay)]):
        fill = five.Fill(
            sig.decided,
            sig.direction,
            sig.entry_minute,
            sig.entry,
            sig.exit_minute,
            sig.exit,
            sig.reason,
        )
        trade = five._trade(sig.symbol, sig.day, fill, sig.direction, mft.TRADE)
        if trade:
            out.append(trade)
    return out


def evaluate(mk: mft.Market, hypothesis: str) -> dict[str, Any]:
    run_id, _ = RULES[hypothesis]
    trades = trades_for(mk, hypothesis)
    sessions = mk.sessions if hypothesis != "H-0138" else [d for d in mk.sessions if d >= START_52W]
    run = cs.report(run_id, trades, sessions, params={"notional": mft.TRADE}, capital=mft.CAPITAL)
    daily = [r for _, r in run["daily"]]
    middle = len(daily) // 2
    run["halves"] = {
        "first": sc.daily_stats(daily[:middle]),
        "second": sc.daily_stats(daily[middle:]),
    }
    by_day: dict[date, float] = defaultdict(float)
    for t in trades:
        by_day[t.day] += (t.gross - 2 * t.costs) / mft.CAPITAL
    run["net_at_2x_costs"] = sc.daily_stats([by_day.get(d, 0.0) for d in sessions])
    run["hypothesis"] = hypothesis
    run["trades_a_day"] = round(len(trades) / len(sessions), 2) if sessions else 0
    run["long_short_bps"] = _legs(trades)
    run.pop("trade_log", None)
    return run


def _legs(trades: list[cs.Trade]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for name, side in (("long_gross", 1), ("short_gross", -1)):
        bps = [t.gross / t.notional * 1e4 for t in trades if t.direction == side and t.notional]
        out[name] = round(statistics.fmean(bps), 2) if bps else None
    return out


def validation_run(hypothesis: str) -> IntradayRun:
    from eulerlab.validation.intraday import IntradayRun

    mk = mft.market()
    sessions = mk.sessions if hypothesis != "H-0138" else [d for d in mk.sessions if d >= START_52W]
    return IntradayRun(
        trades_for(mk, hypothesis),
        trades_for(mk, hypothesis, delay=mft.LATE),
        sessions,
        mft.CAPITAL,
    )


def run(output: Path = OUT) -> dict[str, Any]:
    mk = mft.market()
    result = {"research": "170", "spent_trials": 0, "runs": [evaluate(mk, h) for h in RULES]}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def passes_screen(one: Mapping[str, Any]) -> bool:
    """Research 170's screen: both halves and the 2x-cost run net positive."""
    sharpes = (
        one["halves"]["first"]["sharpe"],
        one["halves"]["second"]["sharpe"],
        one["net_at_2x_costs"]["sharpe"],
    )
    return all(s is not None and s > 0 for s in sharpes)


def main() -> int:
    parser = argparse.ArgumentParser(prog="quant-screen")
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    for one in run(args.output)["runs"]:
        pt = one["per_trade_bps"]
        print(
            f"{one['hypothesis']} {one['id']}: {one['trades']} trades ({one['trades_a_day']}/day); "
            f"{pt['gross_mean']} gross, {pt['net_mean']} net bps; legs {one['long_short_bps']}; "
            f"net Sharpe {one['net']['sharpe']}; halves {one['halves']['first']['sharpe']} / "
            f"{one['halves']['second']['sharpe']}; 2x {one['net_at_2x_costs']['sharpe']}; "
            f"{'PASS' if passes_screen(one) else 'fail'}"
        )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
