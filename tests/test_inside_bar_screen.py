from datetime import date

from eulerlab.intraday.india_papers import Day
from eulerlab.strategies.studies import inside_bar as screen


def test_inside_bar_close_break_enters_next_bar_with_two_r_target() -> None:
    bars = [
        screen.Bar(5, 100.0, 103.0, 99.0, 101.0, 10.0),
        screen.Bar(10, 101.0, 102.0, 100.0, 101.0, 8.0),
        screen.Bar(15, 101.0, 103.0, 100.5, 102.5, 12.0),
        screen.Bar(20, 103.0, 104.0, 102.0, 103.5, 9.0),
    ]

    signal = screen._signal(bars, 2)

    assert signal == {
        "direction": 1,
        "signal_start": 15,
        "entry_start": 20,
        "entry": 103.0,
        "stop": 100.0,
        "target": 109.0,
    }


def test_inside_bar_rejects_non_contiguous_or_non_inside_pattern() -> None:
    bars = [
        screen.Bar(5, 100.0, 103.0, 99.0, 101.0, 10.0),
        screen.Bar(15, 101.0, 102.0, 100.0, 101.0, 8.0),
        screen.Bar(20, 101.0, 103.0, 100.5, 102.5, 12.0),
        screen.Bar(25, 103.0, 104.0, 102.0, 103.5, 9.0),
    ]

    assert screen._signal(bars, 2) is None


def test_same_bar_stop_target_collision_resolves_stop_first() -> None:
    day = Day(
        date(2024, 1, 2),
        tuple([None] * 375),
        tuple([None] * 375),
        tuple([None] * 375),
        tuple([100.0] * 375),
        tuple([0.0] * 375),
        374,
    )
    bars = [screen.Bar(20, 103.0, 110.0, 99.0, 104.0, 10.0)]
    signal = {"direction": 1, "entry_start": 20, "entry": 103.0, "stop": 100.0, "target": 109.0}

    assert screen._exit(day, bars, signal) == (20, 100.0, "stop_first")
