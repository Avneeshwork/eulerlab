"""The validation battery for intraday rules (ADR-139)."""

from __future__ import annotations

from datetime import date, timedelta

from eulerlab.intraday import cross_section as cs
from eulerlab.validation import intraday

DAYS = [date(2022, 1, 3) + timedelta(days=i) for i in range(400)]


def _trade(day: date, symbol: str, gain: float) -> cs.Trade:
    # A short of 1,000 shares at 100 that gains `gain` rupees a share.
    return cs.Trade(symbol, day, -1, 1000, 5, 100.0, 355, 100.0 - gain, "time_exit")


def _run() -> intraday.IntradayRun:
    trades = []
    for i, d in enumerate(DAYS):
        if i % 2 == 0:
            trades.append(_trade(d, f"S{i % 7}", 0.6 if i % 3 else -0.3))
    late = [_trade(t.day, t.symbol, 0.5 if t.entry > t.exit else -0.3) for t in trades]
    return intraday.IntradayRun(trades, late, DAYS, 1_000_000.0)


def test_daily_returns_cover_every_session_and_scale_costs() -> None:
    run = _run()
    base = intraday.daily_returns(run.trades, run.sessions, run.capital)
    double = intraday.daily_returns(run.trades, run.sessions, run.capital, cost_multiple=2.0)
    assert len(base) == len(DAYS) and base[DAYS[1]] == 0.0
    assert double[DAYS[0]] < base[DAYS[0]]


def test_stresses_carry_the_names_the_gate_reads() -> None:
    names = {s.name for s in intraday.stresses(_run())}
    assert {"costs x2", "drop best 5 names", "regime: first half", "regime: second half"} <= names


def test_cpcv_scores_every_path_without_leakage() -> None:
    scored, notes = intraday.evaluate(_run(), n_blocks=6, test_blocks=2, horizon=1, embargo=5)
    assert not notes
    (one,) = scored
    assert len(one.in_sample) == len(one.out_of_sample) == 15
    assert len(one.dated_returns) == len(DAYS)


def test_only_registered_hypotheses_are_supported() -> None:
    assert intraday.supported("H-0096") and not intraday.supported("H-0001")
