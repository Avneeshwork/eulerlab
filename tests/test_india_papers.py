"""Strategies from papers on Indian equities: their rules, checked by hand."""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from eulerlab.backtest import india_papers as ip
from eulerlab.backtest.strategy import MarketView
from eulerlab.features.panel import PanelRow
from eulerlab.research import library
from eulerlab.strategies import REGISTRY


def weekdays(start: date, n: int, skip: frozenset[date] = frozenset()) -> list[date]:
    out: list[date] = []
    day = start
    while len(out) < n:
        if day.weekday() < 5 and day not in skip:
            out.append(day)
        day += timedelta(days=1)
    return out


def rows(
    symbol: str, closes: list[float], start: date = date(2024, 1, 1), isin: str = "INE000"
) -> list[PanelRow]:
    days = weekdays(start, len(closes))
    return [
        PanelRow(day=d, symbol=symbol, close=c, volume=1000, turnover=1e7, isin=isin)
        for d, c in zip(days, closes, strict=True)
    ]


# --- calendar rules -------------------------------------------------------------


def test_turn_of_month_is_the_last_day_and_the_first_two() -> None:
    cal = weekdays(date(2024, 1, 25), 10)  # Jan 25 .. Feb 7
    held = [d for i, d in enumerate(cal) if ip.turn_of_month(cal, i)]
    assert held == [date(2024, 1, 31), date(2024, 2, 1), date(2024, 2, 2)]


def test_expiry_is_the_last_thursday_or_the_day_before_a_holiday() -> None:
    cal = weekdays(date(2024, 1, 1), 40)
    assert next(d for i, d in enumerate(cal) if ip.is_monthly_expiry(cal, i)) == date(2024, 1, 25)
    shut = weekdays(date(2024, 1, 1), 40, skip=frozenset({date(2024, 1, 25)}))
    assert next(d for i, d in enumerate(shut) if ip.is_monthly_expiry(shut, i)) == date(2024, 1, 24)


def test_expiry_moves_to_tuesday_from_september_2025() -> None:
    cal = weekdays(date(2025, 9, 1), 22)
    assert [d for i, d in enumerate(cal) if ip.is_monthly_expiry(cal, i)] == [date(2025, 9, 30)]


def test_post_holiday_is_the_day_after_a_weekday_closure_not_a_weekend() -> None:
    cal = weekdays(date(2024, 1, 1), 10, skip=frozenset({date(2024, 1, 3)}))
    held = [d for i, d in enumerate(cal) if ip.post_holiday(cal, i)]
    assert held == [date(2024, 1, 4)]


def test_a_calendar_decision_sets_the_position_two_days_ahead() -> None:
    """Decided at day d's close, filled at d+1's close, held over d+2."""
    cal = weekdays(date(2024, 1, 1), 10)  # Mon Jan 1 ...
    strategy = ip.IndexCalendar("t", cal, ip.monday_or_wednesday)
    view = MarketView(as_of=cal[0], history={"NIFTYBEES": rows("NIFTYBEES", [100.0])})
    assert strategy.target_weights(view) == {"NIFTYBEES": 1.0}  # holds Wed Jan 3
    view = MarketView(as_of=cal[1], history={"NIFTYBEES": rows("NIFTYBEES", [100.0])})
    assert strategy.target_weights(view) == {}  # Thu Jan 4


# --- scores ---------------------------------------------------------------------


def test_momentum_skips_the_last_month() -> None:
    history = rows("A", [100.0] * 5 + [200.0] + [100.0] * 3)
    assert ip.momentum(5, 3)(history) == pytest.approx(1.0)


def test_max_l5_reads_only_the_last_five_days_of_last_month() -> None:
    closes = [100.0] * 30
    history = rows("A", closes, start=date(2024, 1, 1))
    jan = [i for i, r in enumerate(history) if r.day.month == 1]
    history[jan[-3]] = PanelRow(
        day=history[jan[-3]].day, symbol="A", close=110.0, volume=1, turnover=1, isin="INE000"
    )
    history[jan[-10]] = PanelRow(
        day=history[jan[-10]].day, symbol="A", close=150.0, volume=1, turnover=1, isin="INE000"
    )
    assert ip.max_last5(history) == pytest.approx(0.10)


def test_monthly_volatility_uses_month_end_closes() -> None:
    closes = []
    for month in range(40):
        closes += [100.0 * (1.1 if month % 2 else 1.0)] * 21
    history = rows("A", closes, start=date(2020, 1, 1))
    value = ip.monthly_volatility(36, 12)(history)
    assert value is not None and value > 0.05


# --- strategies -----------------------------------------------------------------


def test_rank_top_never_holds_a_fund() -> None:
    history = {f"S{i}": rows(f"S{i}", [100.0] * 40 + [100.0 + i]) for i in range(40)}
    history["NIFTYBEES"] = rows("NIFTYBEES", [100.0] * 40 + [500.0], isin="INF732E01011")
    strategy = ip.RankTop(
        "t", lambda r: r[-1].close, fraction=0.1, highest=True, rebalance_every=21, lookback=5
    )
    weights = strategy.target_weights(MarketView(as_of=history["S0"][-1].day, history=history))
    assert "NIFTYBEES" not in weights
    assert set(weights) == {"S39", "S38", "S37", "S36"}


def test_the_pair_holds_the_cheap_leg() -> None:
    n = ip.YEAR + 10
    a = [100.0] * n
    b = [100.0] * (n - 1) + [80.0]  # b falls: a/b jumps, a is rich
    history = {"A": rows("A", a), "B": rows("B", b)}
    weights = ip.PairRatio("t", "A", "B").target_weights(
        MarketView(as_of=history["A"][-1].day, history=history)
    )
    assert weights == {"B": 1.0}


def test_the_universe_is_the_most_traded_on_the_day() -> None:
    days = 40
    history = {
        f"S{i}": [
            PanelRow(
                day=d, symbol=f"S{i}", close=100.0, volume=1, turnover=float(i + 1), isin="INE"
            )
            for d in weekdays(date(2024, 1, 1), days)
        ]
        for i in range(10)
    }
    view = MarketView(as_of=history["S0"][-1].day, history=history)
    assert ip.liquid_universe(view, top=3) == ["S9", "S8", "S7"]


def test_low_beta_holds_the_low_beta_half() -> None:
    n = 800
    market = [100 * math.exp(0.01 * math.sin(k / 3) + 0.0003 * k) for k in range(n)]
    history = {"NIFTYBEES": rows("NIFTYBEES", market, isin="INF")}
    for s in range(40):
        scale = 0.2 + s * 0.05
        history[f"S{s:02d}"] = rows(f"S{s:02d}", [100 * (m / market[0]) ** scale for m in market])
    weights = ip.LowBeta().target_weights(MarketView(as_of=history["S00"][-1].day, history=history))
    assert weights and max(weights, key=weights.__getitem__) == "S00"
    assert all(int(s[1:]) < 20 for s in weights)


# --- registration and papers ------------------------------------------------------


def test_every_paper_strategy_is_registered_and_cites_a_library_paper() -> None:
    papers = {p.id: p for p in library.all_papers()}
    for spec in ip.STRATEGIES:
        assert spec.id in REGISTRY
        assert spec.paper in papers, spec.paper
        assert any(link.id == spec.id for link in papers[spec.paper].strategies)
