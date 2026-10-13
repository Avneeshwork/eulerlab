"""Five intraday rules from Indian sources, each pinned on a day built by hand.

Research 076. The days below are synthetic: one bar a minute at a price the
test chooses, so every entry, stop, target and exit can be worked out on paper.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import eulerlab.intraday.india_papers as ip
import eulerlab.intraday.session_papers as sp

MONDAY = date(2026, 1, 5)


def make(
    prices: dict[int, float],
    *,
    day: date = MONDAY,
    last: int = 374,
    volume: float = 100.0,
    volumes: dict[int, float] | None = None,
    wick: float = 0.0,
) -> ip.Day:
    """A day whose bar at minute m opens and closes at the newest price at or
    before m. `wick` widens every bar's high and low by that much."""
    rows: dict[int, tuple[float, float, float, float, float]] = {}
    price = prices[0]
    for m in range(last + 1):
        price = prices.get(m, price)
        rows[m] = (price, price + wick, price - wick, price, (volumes or {}).get(m, volume))
    return ip.days_from_rows({day.isoformat(): rows})[0]


# --- reading days -----------------------------------------------------------------------


def test_a_day_that_ends_at_the_auction_is_normal_and_a_short_one_is_not() -> None:
    assert make({0: 100.0}, last=359).last == 359
    short = dict.fromkeys(range(60), (1.0, 1.0, 1.0, 1.0, 1.0))  # a Muhurat hour
    saturday = dict.fromkeys(range(375), (1.0, 1.0, 1.0, 1.0, 1.0))
    late = dict.fromkeys(range(5, 375), (1.0, 1.0, 1.0, 1.0, 1.0))  # no 09:15 bar
    assert ip.days_from_rows({"2026-01-05": short}) == []
    assert ip.days_from_rows({"2026-01-03": saturday}) == []
    assert ip.days_from_rows({"2026-01-05": late}) == []


def test_a_minute_with_no_trade_cannot_fill_and_carries_the_close() -> None:
    rows = {m: (100.0, 100.0, 100.0, 100.0, 1.0) for m in range(375) if m not in (10, 11)}
    day = ip.days_from_rows({"2026-01-05": rows})[0]
    assert day.open_[10] is None and day.close[10] == 100.0
    assert day.fill_at(10) == (12, 100.0)
    assert day.fill_at(0) == (1, 100.0), "nothing fills on the first print"


def test_load_keeps_one_bar_a_minute_and_the_later_file_wins(tmp_path: Path) -> None:
    def write(name: str, close: float) -> None:
        stamps = [
            f"2026-01-05T{9 + (15 + m) // 60:02d}:{(15 + m) % 60:02d}:00+0530" for m in range(375)
        ]
        n = len(stamps)
        table = pa.table(
            {
                "ts": stamps,
                "open": [close] * n,
                "high": [close] * n,
                "low": [close] * n,
                "close": [close] * n,
                "volume": [5] * n,
            }
        )
        (tmp_path / "AAA").mkdir(exist_ok=True)
        pq.write_table(table, tmp_path / "AAA" / name)

    write("2025-12-01_2026-01-05.parquet", 100.0)
    write("2025-12-02_2026-01-06.parquet", 101.0)
    days = ip.load("AAA", tmp_path)
    assert len(days) == 1 and days[0].close[0] == 101.0 and days[0].volume[0] == 5.0


# --- 1. the long opening range ----------------------------------------------------------


def test_late_orb_follows_a_three_minute_close_and_ignores_the_first_print() -> None:
    # A wild first print, then 100-101 until 11:15. 102 from 11:20 on.
    day = make({0: 150.0, 1: 100.0, 60: 101.0, 100: 100.5, 125: 102.0})
    found = ip.late_orb_trade(day, window_end=120, exit_at=369)
    # 3-minute bars after the range: 120-122, 123-125 (closes 102 > 101), so in at 126.
    assert found == (1, (126, 102.0), (369, 102.0))
    assert ip.late_orb_trade(make({0: 150.0, 1: 100.0}), window_end=120, exit_at=369) is None


def test_late_orb_stops_at_the_other_side_of_the_range() -> None:
    day = make({0: 100.0, 60: 101.0, 100: 100.0, 125: 102.0, 200: 99.0})
    stopped = ip.late_orb_trade(day, window_end=120, exit_at=369)
    # The bar opened through the stop at 100, so it filled at its open.
    assert stopped == (1, (126, 102.0), (200, 99.0))
    short = make({0: 100.0, 60: 101.0, 100: 100.0, 125: 99.0, 200: 101.5}, wick=0.0)
    assert ip.late_orb_trade(short, window_end=120, exit_at=369) == (-1, (126, 99.0), (200, 101.5))


# --- 2. thirty minutes, twice the risk --------------------------------------------------


def test_orb_two_r_enters_on_the_break_and_takes_twice_the_risk() -> None:
    # Range 100-102 (risk 2). Breaks up at minute 40; target 102 + 4 = 106.
    day = make({0: 100.0, 10: 102.0, 20: 101.0, 40: 103.0, 90: 107.0})
    assert ip.orb_two_r_trade(day) == (1, (40, 103.0), (90, 107.0))


def test_orb_two_r_stops_out_or_leaves_at_half_past_two() -> None:
    stopped = make({0: 100.0, 10: 102.0, 20: 101.0, 40: 103.0, 90: 99.0})
    assert ip.orb_two_r_trade(stopped) == (1, (40, 103.0), (90, 99.0))
    drifting = make({0: 100.0, 10: 102.0, 20: 101.0, 40: 103.0})
    assert ip.orb_two_r_trade(drifting) == (1, (40, 103.0), (315, 103.0))
    quiet = make({0: 100.0, 10: 102.0, 20: 101.0})
    assert ip.orb_two_r_trade(quiet) is None
    both = make({0: 100.0, 10: 102.0, 20: 101.0}, wick=0.0)
    both_sides = ip.days_from_rows(
        {
            MONDAY.isoformat(): {
                m: (
                    (101.0, 103.0, 99.0, 101.0, 1.0)
                    if m == 40
                    else (
                        both.open_[m] or 101.0,
                        both.high[m] or 101.0,
                        both.low[m] or 101.0,
                        both.close[m],
                        1.0,
                    )
                )
                for m in range(375)
            }
        }
    )[0]
    assert ip.orb_two_r_trade(both_sides) is None, "one bar through both edges is not a signal"


# --- 3. a breakout that needs volume ----------------------------------------------------


def test_orb_volume_needs_the_surge_and_holds_a_set_number_of_bars() -> None:
    usual = [100.0 * 15] * 25
    # 15-minute bars. Range from the first bar: 100-101. Bar 2 (minutes 30-44) closes at 103.
    quiet = make({0: 100.0, 5: 101.0, 10: 100.5, 30: 103.0})
    assert ip.orb_volume_trade(quiet, usual, size=15, surge=1.5, hold=3) is None
    loud = make(
        {0: 100.0, 5: 101.0, 10: 100.5, 30: 103.0}, volumes=dict.fromkeys(range(30, 45), 200.0)
    )
    assert ip.orb_volume_trade(loud, usual, size=15, surge=1.5, hold=3) == (
        1,
        (45, 103.0),
        (90, 103.0),
    )
    down = make(
        {0: 100.0, 5: 101.0, 10: 100.5, 30: 99.0}, volumes=dict.fromkeys(range(30, 45), 200.0)
    )
    assert ip.orb_volume_trade(down, usual, size=15, surge=1.5, hold=2) == (
        -1,
        (45, 99.0),
        (75, 99.0),
    )


def test_orb_volume_uses_only_earlier_days_for_the_usual_volume() -> None:
    quiet_days = [
        make({0: 100.0}, day=MONDAY + timedelta(days=i))
        for i in range(40)
        if (MONDAY + timedelta(days=i)).weekday() < 5
    ]
    history = quiet_days[: ip.SURGE_LOOKBACK]
    loud_day = make(
        {0: 100.0, 5: 101.0, 10: 100.5, 30: 103.0},
        day=date(2026, 3, 2),
        volumes=dict.fromkeys(range(30, 45), 200.0),
    )
    signals = ip.orb_volume_signals([*history, loud_day], size=15, surge=1.5, hold=3)
    assert list(signals) == [date(2026, 3, 2)]
    # With one day too few of history there is no "usual" and so no signal.
    assert ip.orb_volume_signals([*history[1:], loud_day], size=15, surge=1.5, hold=3) == {}
    # A surge measured against its own day would never fire: 200 against 200.
    all_loud = [make({0: 100.0}, day=d.day, volume=200.0) for d in history]
    assert ip.orb_volume_signals([*all_loud, loud_day], size=15, surge=1.5, hold=3) == {}


# --- 4. the day so far, into the last half-hour -----------------------------------------


def test_rest_of_day_trades_the_last_half_hour_with_the_day_so_far() -> None:
    first = make({0: 100.0}, day=MONDAY)
    up = make({0: 101.0, 350: 102.0}, day=MONDAY + timedelta(days=1))
    down = make({0: 101.0, 300: 100.0, 350: 99.0}, day=MONDAY + timedelta(days=2))
    result = ip.rest_of_day([first, up, down], {MONDAY: 100.0}, cost=sp.no_cost, slippage_bps=0.0)
    long, short = result.trades
    assert (long.direction, long.entry_minute, long.entry, long.exit_minute, long.exit) == (
        1,
        345,
        101.0,
        369,
        102.0,
    )
    # Down day: 14:59 close 100 against the previous day's last bar 102.
    assert (short.direction, short.entry, short.exit) == (-1, 100.0, 99.0)
    assert len(result.days) == 2


def test_rest_of_day_measures_from_the_official_close_when_it_has_one() -> None:
    first = make({0: 100.0}, day=MONDAY)
    flat = make({0: 100.5}, day=MONDAY + timedelta(days=1))
    # Last bar 100, official close 101: the day so far is down, not up.
    result = ip.rest_of_day([first, flat], {MONDAY: 101.0}, cost=sp.no_cost, slippage_bps=0.0)
    assert result.trades[0].direction == -1


# --- 5. fade the extremes ---------------------------------------------------------------


def test_the_three_biggest_moves_each_way_are_picked_whatever_the_order() -> None:
    moves = {f"S{i}": i / 100 for i in range(10)}
    assert ip.extreme_picks(moves) == (["S0", "S1", "S2"], ["S7", "S8", "S9"])
    assert ip.extreme_picks(dict(reversed(moves.items()))) == ip.extreme_picks(moves)
    assert ip.extreme_picks({f"S{i}": 0.0 for i in range(6)}) == ([], []), "too few to rank"


def test_a_penny_stock_and_a_broken_print_are_not_measured() -> None:
    cheap = make({0: 9.0})
    assert ip.half_hour_return(cheap, cheap, "open") is None
    split = make({0: 50.0}, day=MONDAY + timedelta(days=1))
    assert ip.half_hour_return(make({0: 100.0}), split, "open") is None
    assert ip.half_hour_return(None, split, "open") is None
    assert ip.half_hour_return(None, make({0: 100.0, 160: 102.0}), "midday") == pytest.approx(0.02)


def test_extreme_reversal_buys_the_losers_and_sells_the_winners() -> None:
    tuesday = MONDAY + timedelta(days=1)
    universe = {}
    for i in range(8):
        # Stock i gaps by (i - 3.5)% and then stays there until 09:45.
        opened = 100.0 * (1 + (i - 3.5) / 100)
        days = [make({0: 100.0}, day=MONDAY), make({0: opened, 30: 100.0}, day=tuesday)]
        universe[f"S{i}"] = ip.reversal_marks(days)
    signals = ip.extreme_reversal_signals(universe, event="open", hold_ticks=1)
    assert list(signals) == [tuesday]
    picked = signals[tuesday]
    assert {s: v[0] for s, v in picked.items()} == {
        "S0": 1,
        "S1": 1,
        "S2": 1,
        "S5": -1,
        "S6": -1,
        "S7": -1,
    }
    _, entry, exit_ = picked["S0"]
    assert entry[0] == 1 and entry[1] == pytest.approx(96.5)
    assert exit_ == (30, 100.0)

    result = ip.portfolio(
        "fade", [MONDAY, tuesday], signals, slots=6, cost=sp.no_cost, slippage_bps=0.0
    )
    assert [d for d, _ in result.days] == [MONDAY, tuesday]
    assert result.days[0][1] == 0.0 and result.days[1][1] > 0.02
    assert len(result.trades) == 6 and all(t.net > 0 for t in result.trades)


def test_midday_marks_use_the_half_hour_to_quarter_past_twelve() -> None:
    day = make({0: 100.0, 160: 103.0, 200: 101.0})
    marks = ip.reversal_marks([day])[MONDAY]
    assert marks.moves == {"open": None, "midday": pytest.approx(0.03)}
    assert marks.fills[180] == (180, 103.0) and marks.fills[209] == (209, 101.0)


def test_a_portfolio_splits_equity_over_its_slots_and_charges_each_trade() -> None:
    signals = {MONDAY: {"AAA": (1, (1, 100.0), (30, 110.0)), "BBB": (-1, (1, 50.0), (30, 55.0))}}
    gross = ip.portfolio(
        "x", [MONDAY], signals, slots=4, capital=1_000_000.0, cost=sp.no_cost, slippage_bps=0.0
    )
    # 250,000 a slot: 2,500 shares up 10, and 5,000 shares short down 5.
    assert [t.shares for t in gross.trades] == [2500, 5000]
    assert gross.days[0][0] == MONDAY and gross.days[0][1] == pytest.approx(0.0)
    net = ip.portfolio("x", [MONDAY], signals, slots=4, capital=1_000_000.0)
    assert net.days[0][1] < 0 and all(t.costs > 0 and t.slippage > 0 for t in net.trades)


def test_the_universe_is_the_largest_companies_with_minute_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    import eulerlab.features.company as digest
    import eulerlab.intraday.india_papers_run as run

    for name in ("BIG", "MID", "SMALL"):
        (tmp_path / name).mkdir()
    held = {
        s: SimpleNamespace(symbol=s, market_cap=cap)
        for s, cap in (
            ("BIG", 9e12),
            ("MID", 5e12),
            ("SMALL", 1e12),
            ("NOFILES", 8e12),
            ("NOCAP", None),
        )
    }
    monkeypatch.setattr(digest, "load_digest", lambda: held)
    assert run.universe(2, tmp_path) == ["BIG", "MID"]
