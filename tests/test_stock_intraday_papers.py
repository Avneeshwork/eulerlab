"""Two stock rules from US papers, each pinned on days built by hand.

Research 078. The days are synthetic: one bar a minute at a price the test
chooses, so every sort, entry and exit can be worked out on paper.
"""

from __future__ import annotations

from datetime import date

import pytest

import eulerlab.intraday.india_papers as ip
import eulerlab.intraday.session_papers as sp
import eulerlab.intraday.stock_papers as stp

MONDAY = date(2026, 1, 5)
TUESDAY = date(2026, 1, 6)
WEDNESDAY = date(2026, 1, 7)


def make(prices: dict[int, float], day: date, *, last: int = 374) -> ip.Day:
    """A day whose bar at minute m opens and closes at the newest price at or before m."""
    rows: dict[int, tuple[float, float, float, float, float]] = {}
    price = prices[0]
    for m in range(last + 1):
        price = prices.get(m, price)
        rows[m] = (price, price, price, price, 100.0)
    return ip.days_from_rows({day.isoformat(): rows})[0]


def test_the_day_so_far_runs_from_the_last_close_to_ten_past_two() -> None:
    monday = make({0: 100.0}, MONDAY)
    # 110 from 09:15, 120 from 14:10 on: the 14:09 close is still 110.
    tuesday = make({0: 110.0, stp.SORT_END: 120.0}, TUESDAY)
    marks = stp.stock_marks([monday, tuesday])
    assert marks[MONDAY].day_so_far is None, "no session before the first"
    assert marks[TUESDAY].day_so_far == pytest.approx(0.10)
    assert marks[TUESDAY].late == ((stp.LATE_ENTRY, 120.0), (stp.LATE_EXIT, 120.0))


def test_the_opening_half_hour_starts_after_the_first_print() -> None:
    # 09:15 prints 90; 09:16 opens at 100; 105 by 09:44; 200 from 09:45.
    day = make({0: 90.0, 1: 100.0, 20: 105.0, 30: 200.0}, MONDAY)
    marks = stp.stock_marks([day])[MONDAY]
    assert marks.first_half_hour == pytest.approx(0.05)
    assert marks.early == ((1, 100.0), (30, 200.0))


def test_a_split_or_a_broken_print_is_not_a_move() -> None:
    monday = make({0: 1000.0}, MONDAY)
    tuesday = make({0: 500.0}, TUESDAY)  # a 2-for-1 split, unadjusted in minute bars
    assert stp.stock_marks([monday, tuesday])[TUESDAY].day_so_far is None


def test_a_stock_that_stops_trading_before_the_exit_has_no_late_trade() -> None:
    def late(silent: range) -> object:
        rows = {m: (100.0, 100.0, 100.0, 100.0, 1.0) for m in range(375) if m not in silent}
        return stp.stock_marks([ip.days_from_rows({MONDAY.isoformat(): rows})[0]])[MONDAY].late

    # Silent 15:10 and 15:11: the exit waits two minutes, to the square-off.
    assert late(range(355, 357)) == ((325, 100.0), (357, 100.0))
    assert late(range(355, 373)) is None, "the first trade after 15:10 is past the square-off"
    assert late(range(320, 373)) is None, "no entry before the exit time"


def test_groups_are_cut_from_both_ends_whatever_the_order() -> None:
    moves = {f"S{i:02d}": i / 100 for i in range(10)}
    shuffled = dict(reversed(list(moves.items())))
    assert stp.extremes(shuffled, 5) == (["S00", "S01"], ["S08", "S09"])
    assert stp.extremes(shuffled, 10) == (["S00"], ["S09"])
    assert stp.extremes({"A": 0.1, "B": 0.2}, 5) == ([], []), "too few stocks to cut"
    assert stp.slots(100, 5) == 40 and stp.slots(100, 10, long_only=True) == 10


def _universe(day_so_far: dict[str, float]) -> dict[str, dict[date, stp.StockMarks]]:
    fills = ((stp.LATE_ENTRY, 100.0), (stp.LATE_EXIT, 101.0))
    return {s: {TUESDAY: stp.StockMarks(move, fills, None, None)} for s, move in day_so_far.items()}


def test_end_of_day_reversal_buys_the_fallers_and_sells_the_risers() -> None:
    universe = _universe({f"S{i:02d}": (i - 5) / 100 for i in range(10)})
    both = stp.end_of_day_reversal_signals(universe, groups=5)[TUESDAY]
    assert {s: signal[0] for s, signal in both.items()} == {
        "S00": 1,
        "S01": 1,
        "S08": -1,
        "S09": -1,
    }
    assert both["S00"][1:] == ((stp.LATE_ENTRY, 100.0), (stp.LATE_EXIT, 101.0))
    longs = stp.end_of_day_reversal_signals(universe, groups=5, long_only=True)[TUESDAY]
    assert set(longs) == {"S00", "S01"}


def test_a_ranked_stock_that_cannot_be_filled_is_left_out_not_replaced() -> None:
    universe = _universe({f"S{i:02d}": (i - 5) / 100 for i in range(10)})
    universe["S00"] = {TUESDAY: stp.StockMarks(-0.05, None, None, None)}
    found = stp.end_of_day_reversal_signals(universe, groups=5)[TUESDAY]
    assert set(found) == {"S01", "S08", "S09"}


def test_same_time_follows_yesterdays_opening_half_hour() -> None:
    fills = ((1, 100.0), (30, 101.0))
    universe = {
        f"S{i:02d}": {
            MONDAY: stp.StockMarks(None, None, (i - 5) / 100, fills),
            TUESDAY: stp.StockMarks(None, None, (5 - i) / 100, fills),
            WEDNESDAY: stp.StockMarks(None, None, 0.0, fills),
        }
        for i in range(10)
    }
    found = stp.same_time_signals(universe, groups=10)
    assert MONDAY not in found, "nothing to sort on before the second session"
    assert {s: signal[0] for s, signal in found[TUESDAY].items()} == {"S09": 1, "S00": -1}
    # Wednesday is sorted on Tuesday, whose order is reversed.
    assert {s: signal[0] for s, signal in found[WEDNESDAY].items()} == {"S00": 1, "S09": -1}


def test_same_time_never_uses_a_session_older_than_the_last_one() -> None:
    fills = ((1, 100.0), (30, 101.0))
    universe = {
        f"S{i:02d}": {
            MONDAY: stp.StockMarks(None, None, i / 100, fills),
            TUESDAY: stp.StockMarks(None, None, i / 100, fills),
        }
        for i in range(10)
    }
    del universe["S09"][MONDAY]  # the top stock did not trade on Monday
    found = stp.same_time_signals(universe, groups=3)[TUESDAY]
    assert "S09" not in found
    assert {s for s, signal in found.items() if signal[0] > 0} == {"S06", "S07", "S08"}


def test_the_spread_is_scaled_back_to_long_minus_short() -> None:
    # Two sides: +1% on the longs and -1% on the shorts is a 2% spread, and a
    # book with half its equity on each side returns 1%.
    result = sp.Result("x", 1_000_000.0, days=[(MONDAY, 0.01), (TUESDAY, 0.03)])
    found = stp.spread(result, sides=2)
    assert found["bps_a_day"] == pytest.approx(400.0)
    assert found["t"] == pytest.approx(2.0)
    assert stp.spread(sp.Result("x", 1.0, days=[(MONDAY, 0.01)]), sides=1)["t"] is None


def test_a_reversal_day_through_the_portfolio_pays_costs_on_both_legs() -> None:
    universe = _universe({f"S{i:02d}": (i - 5) / 100 for i in range(10)})
    signals = stp.end_of_day_reversal_signals(universe, groups=5)
    gross = ip.portfolio("x", [TUESDAY], signals, slots=4, cost=sp.no_cost, slippage_bps=0.0)
    net = ip.portfolio("x", [TUESDAY], signals, slots=4)
    # Two longs gain 1% and two shorts lose 1% of a quarter of equity each.
    assert gross.days[0][1] == pytest.approx(0.0)
    assert len(net.trades) == 4
    assert net.days[0][1] < 0
