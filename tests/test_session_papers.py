"""Two intraday papers coded for NSE hours (research 071).

Sessions here are built by hand: `q[m]` is the price at minute `m` after 09:15,
so bar `m` opens at `q[m]` and closes at `q[m + 1]`. Every expected number
below can be worked out from that.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from eulerlab.costs.schedule import Side
from eulerlab.intraday import session_papers as sp
from eulerlab.intraday.tweezer import Candle

IST = ZoneInfo("Asia/Kolkata")
MONDAY = date(2026, 6, 1)


def bars(
    day: date, price: Callable[[int], float], *, skip: frozenset[int] = frozenset()
) -> list[Candle]:
    out = []
    for m in range(sp.SESSION_MINUTES):
        if m in skip:
            continue
        o, c = price(m), price(m + 1)
        stamp = datetime.combine(day, time(9, 15), IST) + timedelta(minutes=m)
        out.append(Candle(ts=stamp, open=o, high=max(o, c), low=min(o, c), close=c, volume=100.0))
    return out


def one(day: date, price: Callable[[int], float]) -> sp.Session:
    built, skipped = sp.sessions(bars(day, price))
    assert skipped == []
    return built[0]


def flat(level: float) -> Callable[[int], float]:
    return lambda m: level


def weekdays(start: date, count: int) -> list[date]:
    out: list[date] = []
    day = start
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


# --- sessions ---------------------------------------------------------------------


def test_a_missing_minute_carries_the_close_and_offers_no_fill() -> None:
    session = sp.sessions(bars(MONDAY, lambda m: 100.0 + m, skip=frozenset({10, 11})))[0][0]
    assert session.open_[10] is None and session.open_[11] is None
    assert session.close[11] == session.close[9] == 110.0
    assert session.fill_at(10) == (12, 112.0), "the first minute that actually traded"


def test_a_short_or_shifted_session_is_skipped() -> None:
    muhurat = [c for c in bars(MONDAY, flat(100.0)) if c.ts.time() >= time(14, 0)]
    half = bars(MONDAY + timedelta(days=1), flat(100.0))[:200]
    built, skipped = sp.sessions(muhurat + half)
    assert built == [] and skipped == [MONDAY, MONDAY + timedelta(days=1)]


def test_vwap_is_volume_weighted_typical_price() -> None:
    session = one(MONDAY, lambda m: 100.0 if m < 2 else 106.0)
    # bar 0: 100,100,100 -> 100 ; bar 1: open 100 close 106 -> (106+100+106)/3 = 104
    assert session.vwap[0] == pytest.approx(100.0)
    assert session.vwap[1] == pytest.approx(102.0)


# --- Gao, Han, Li, Zhou -------------------------------------------------------------


def test_r1_runs_from_the_previous_close_to_0945_and_r12_from_1430_to_1500() -> None:
    def price(m: int) -> float:
        if m <= 30:
            return 101.0
        if m <= 315:
            return 100.0
        return 102.0 if m <= 345 else 105.0

    r1, r12 = sp.gao_signals(100.0, one(MONDAY, price))
    assert r1 == pytest.approx(0.01), "includes the overnight gap, as the paper defines it"
    assert r12 == pytest.approx(0.02)


def test_the_direction_rules_are_the_papers() -> None:
    assert sp.gao_direction("r1", 0.001, -1) == 1
    assert sp.gao_direction("r1", 0.0, 1) == -1, "eq. (4): short when r1 <= 0"
    assert sp.gao_direction("r12", -1, 0.001) == 1
    assert sp.gao_direction("both", 0.01, 0.01) == 1
    assert sp.gao_direction("both", -0.01, -0.01) == -1
    assert sp.gao_direction("both", 0.01, -0.01) == 0, "they disagree: stay out"


def _two_days(second: Callable[[int], float]) -> list[sp.Session]:
    return [one(MONDAY, flat(100.0)), one(MONDAY + timedelta(days=1), second)]


def test_a_positive_first_half_hour_buys_at_1500_and_sells_at_the_close() -> None:
    def price(m: int) -> float:
        return 101.0 if m <= 345 else 102.0  # up 1% by 09:45; 101 at 15:00; 102 after

    days = _two_days(price)
    run = sp.gao_timing(days, signal="r1", capital=10_100.0, cost=sp.no_cost, slippage_bps=0.0)
    (trade,) = run.trades
    assert (trade.direction, trade.entry_minute, trade.entry) == (1, 345, 101.0)
    assert (trade.exit_minute, trade.exit, trade.shares) == (374, 102.0, 100)
    assert trade.gross == pytest.approx(100.0)
    ((day, day_return),) = run.days
    assert day == days[1].day and day_return == pytest.approx(100.0 / 10_100.0)


def test_a_negative_first_half_hour_sells_short_and_profits_from_a_fall() -> None:
    days = _two_days(lambda m: 99.0 if m <= 345 else 98.0)
    run = sp.gao_timing(days, signal="r1", capital=9_900.0, cost=sp.no_cost, slippage_bps=0.0)
    (trade,) = run.trades
    assert trade.direction == -1 and trade.gross == pytest.approx(100.0)


def test_the_tradable_exit_leaves_at_1524_not_at_the_close() -> None:
    def price(m: int) -> float:
        if m <= 345:
            return 101.0
        return 102.0 if m <= sp.TRADABLE_EXIT else 110.0  # the last minutes are not ours

    run = sp.gao_timing(
        _two_days(price), exit_at=sp.TRADABLE_EXIT, cost=sp.no_cost, slippage_bps=0.0
    )
    (trade,) = run.trades
    assert (trade.exit_minute, trade.exit) == (sp.TRADABLE_EXIT, 102.0)


def test_nothing_after_1500_can_change_the_decision() -> None:
    up = sp.gao_timing(_two_days(lambda m: 101.0 if m <= 345 else 150.0), cost=sp.no_cost)
    down = sp.gao_timing(_two_days(lambda m: 101.0 if m <= 345 else 50.0), cost=sp.no_cost)
    assert up.trades[0].direction == down.trades[0].direction == 1
    assert up.trades[0].entry == down.trades[0].entry == 101.0


def test_costs_and_slippage_come_off_the_trade() -> None:
    def cost(price: float, shares: int, side: Side, day: date) -> float:
        return 7.0

    days = _two_days(lambda m: 101.0 if m <= 345 else 102.0)
    run = sp.gao_timing(days, capital=10_100.0, cost=cost, slippage_bps=10.0)
    (trade,) = run.trades
    assert trade.costs == 14.0
    assert trade.slippage == pytest.approx((101.0 + 102.0) * 100 * 10 / 1e4)
    assert trade.net == pytest.approx(100.0 - 14.0 - 20.3)


def test_a_split_sized_gap_is_skipped_and_said() -> None:
    days = [one(MONDAY, flat(100.0)), one(MONDAY + timedelta(days=1), flat(50.0))]
    run = sp.gao_timing(days, cost=sp.no_cost)
    assert run.trades == [] and "overnight gap -50.0%" in run.skipped[0]


# --- Zarattini, Aziz, Barbon --------------------------------------------------------


def test_sigma_is_the_average_absolute_move_from_the_anchor() -> None:
    # The anchor is the first minute's close, q[1]; the move is measured from it.
    up = one(MONDAY, lambda m: 100.0 if m <= 1 else 101.0)
    down = one(MONDAY + timedelta(days=1), lambda m: 100.0 if m <= 1 else 97.0)
    sigma = sp.noise_sigma([up, down])
    assert sigma[100] == pytest.approx(0.02), "(1% + 3%) / 2, sign ignored"


def test_the_first_print_is_never_the_open() -> None:
    # A stray first print 5% above the market: 105 at 09:15, 100 from 09:16.
    session = one(MONDAY, lambda m: 105.0 if m == 0 else 100.0)
    assert session.open_[0] == 105.0 and session.anchor == 100.0
    calm = sp.noise_sigma([session])
    assert max(calm) == pytest.approx(0.0), "measured from 100, the day never moved"


def test_the_official_close_is_the_close_when_it_is_known() -> None:
    day_two = MONDAY + timedelta(days=1)
    candles = bars(MONDAY, flat(100.0)) + bars(day_two, lambda m: 101.0 if m <= 345 else 102.0)
    built, _ = sp.sessions(candles, official={MONDAY: 99.0, day_two: 101.5})
    assert built[0].settle == 99.0 and built[0].last_close == 100.0
    r1, _ = sp.gao_signals(built[0].settle, built[1])
    assert r1 == pytest.approx(101.0 / 99.0 - 1), "from the exchange's close, not the last bar"
    run = sp.gao_timing(built, capital=10_100.0, cost=sp.no_cost, slippage_bps=0.0)
    assert run.trades[0].exit == 101.5, "the published exit is the official close"
    assert sp.sessions(candles)[0][1].settle == 102.0, "without one, the last bar stands in"


def test_the_bounds_widen_towards_an_overnight_gap() -> None:
    session = one(MONDAY, flat(100.0))
    sigma = [0.01] * sp.SESSION_MINUTES
    lower, upper = sp.noise_bounds(session, 102.0, sigma, 50)
    assert upper == pytest.approx(102.0 * 1.01), "gap down: the upper bound starts at yesterday"
    assert lower == pytest.approx(100.0 * 0.99)


def _history() -> list[sp.Session]:
    """Fourteen days that each drift 0.5% from the open, so sigma is 0.5%."""
    return [one(d, lambda m: 100.0 if m <= 1 else 100.5) for d in weekdays(MONDAY, 14)]


def _after_history(price: Callable[[int], float]) -> list[sp.Session]:
    history = _history()
    last = one(history[-1].day, lambda m: 100.0)  # close the history at 100
    day = weekdays(history[-1].day + timedelta(days=1), 1)[0]
    return [*history[:-1], last, one(day, price)]


def test_a_breakout_is_traded_only_at_the_next_half_hour_mark() -> None:
    # Leaves the 0.5% band at minute 31, just after the 09:45 decision.
    def price(m: int) -> float:
        return 100.0 if m <= 31 else 102.0

    run = sp.noise_area(_after_history(price), cost=sp.no_cost, slippage_bps=0.0)
    (trade,) = run.trades
    assert trade.direction == 1
    assert trade.entry_minute == 60, "seen at 10:14, filled at the 10:15 open"
    assert (trade.exit_minute, trade.exit) == (374, 102.0)


def test_a_day_inside_the_noise_area_does_not_trade() -> None:
    run = sp.noise_area(_after_history(lambda m: 100.2), cost=sp.no_cost)
    assert run.trades == [] and run.days[-1][1] == 0.0


def test_the_vwap_stop_closes_a_long_that_falls_back_and_the_base_model_holds() -> None:
    def price(m: int) -> float:
        if m <= 20:
            return 100.0
        return 102.0 if m <= 80 else 100.2  # out by 09:45, back inside by 10:45

    days = _after_history(price)
    stopped = sp.noise_area(days, vwap_stop=True, cost=sp.no_cost, slippage_bps=0.0)
    held = sp.noise_area(days, vwap_stop=False, cost=sp.no_cost, slippage_bps=0.0)
    assert [(t.entry_minute, t.exit_minute) for t in stopped.trades] == [(30, 90)]
    assert [(t.entry_minute, t.exit_minute) for t in held.trades] == [(30, 374)], (
        "the base model leaves only at the opposite band or the close"
    )


def test_a_fall_through_the_lower_bound_goes_short() -> None:
    run = sp.noise_area(
        _after_history(lambda m: 100.0 if m <= 20 else 98.0), cost=sp.no_cost, slippage_bps=0.0
    )
    (trade,) = run.trades
    assert trade.direction == -1 and trade.entry == 98.0 and trade.gross == pytest.approx(0.0)


def test_the_first_fourteen_days_only_build_the_noise_area() -> None:
    run = sp.noise_area(_history(), cost=sp.no_cost)
    assert run.days == [] and run.trades == []


# --- results ------------------------------------------------------------------------


def test_stats_count_flat_days_and_split_by_date() -> None:
    result = sp.Result("x", 100.0)
    result.days = [(MONDAY, 0.01), (MONDAY + timedelta(days=1), 0.0), (date(2026, 7, 1), -0.01)]
    whole = result.stats()
    assert whole["days"] == 3 and whole["total_return"] == pytest.approx(1.01 * 0.99 - 1, abs=1e-5)
    assert result.stats(end=date(2026, 7, 1))["days"] == 2
    assert result.stats(start=date(2026, 7, 1))["total_return"] == pytest.approx(-0.01)


def test_the_real_cost_of_a_round_trip_is_a_few_basis_points() -> None:
    buy = sp.nse_intraday_cost(270.0, 3_700, Side.BUY, MONDAY)
    sell = sp.nse_intraday_cost(270.0, 3_700, Side.SELL, MONDAY)
    bps = (buy + sell) / (270.0 * 3_700) * 1e4
    assert 2.0 < bps < 8.0, "if this moves, every result in research 071 moves with it"
