"""Research 166: index-futures rules on 15-minute bars, index-option expiry
straddles, and the F&O ban exit. Synthetic sessions, so each rule's entry,
exit and cost path is pinned without market data."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from eulerlab.intraday import index_futures_screen as fut
from eulerlab.intraday import india_papers as ip
from eulerlab.intraday import nse_reports_screen as rep
from eulerlab.options import index_expiry_screen as ix
from eulerlab.validation import intraday


def _day(day: date, path: dict[int, float]) -> ip.Day:
    """A full session whose close follows `path` (minute -> price), carried forward."""
    price = path[0]
    bars = {}
    for m in range(ip.MINUTES):
        price = path.get(m, price)
        bars[m] = (price, price, price, price, 0.0)
    (built,) = ip.days_from_rows({day.isoformat(): bars})
    return built


def _weekdays(start: date, n: int) -> list[date]:
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def test_noise_area_goes_long_above_the_band_and_exits_at_1525() -> None:
    days_ = _weekdays(date(2023, 1, 2), 16)
    # Every quiet day moves 0.2% from its open by every decision mark.
    quiet = [_day(d, {0: 100.0, 20: 100.2}) for d in days_[:14]]
    trend = _day(days_[14], {0: 100.0, 40: 101.0})
    closes = dict.fromkeys(days_, 100.0)
    trades = fut.noise_area("NIFTY50", [*quiet, trend], closes)
    assert len(trades) == 1
    t = trades[0]
    assert t.direction == 1
    assert t.entry_minute == 45  # decided on the minute-44 close, filled at the next open
    assert t.exit_minute == fut.EXIT_MINUTE
    assert t.gross == pytest.approx(0.0)  # flat after entry


def test_noise_area_late_entry_fills_five_minutes_later() -> None:
    days_ = _weekdays(date(2023, 1, 2), 15)
    quiet = [_day(d, {0: 100.0, 20: 100.2}) for d in days_[:14]]
    trend = _day(days_[14], {0: 100.0, 40: 101.0})
    closes = dict.fromkeys(days_, 100.0)
    (late,) = fut.noise_area("NIFTY50", [*quiet, trend], closes, delay=fut.LATE)
    assert late.entry_minute == 50


def test_opening_range_stops_at_the_other_side() -> None:
    (d,) = _weekdays(date(2023, 3, 1), 1)
    day = _day(d, {0: 100.0, 5: 100.5, 10: 99.5, 14: 100.0, 29: 100.8, 60: 99.0})
    (t,) = fut.opening_range("NIFTYBANK", [day], {})
    assert (t.direction, t.entry_minute, t.reason) == (1, 30, "stop")
    assert t.exit_minute == 60
    assert t.exit == pytest.approx(99.0)  # gapped through the 99.5 stop: filled at the open


def test_gap_fade_targets_the_previous_close() -> None:
    before, d = _weekdays(date(2023, 3, 1), 2)
    day = _day(d, {0: 101.0, 14: 100.8, 100: 99.9})
    (t,) = fut.gap_fade("NIFTY50", [day], {before: 100.0})
    assert (t.direction, t.entry_minute, t.reason) == (-1, 15, "target")
    assert t.exit == pytest.approx(99.9)  # opened below the 100 target: filled at the open


def test_gap_fade_skips_a_gap_that_kept_going() -> None:
    before, d = _weekdays(date(2023, 3, 1), 2)
    day = _day(d, {0: 101.0, 14: 101.2})
    assert fut.gap_fade("NIFTY50", [day], {before: 100.0}) == []


def test_futures_costs_are_futures_rates_plus_slippage() -> None:
    t = fut.Trade("NIFTY50", date(2023, 6, 1), 1, 30, 20_000.0, 370, 20_000.0, "15:25")
    bps = t.costs / fut.NOTIONAL * 10_000
    assert 4.0 < bps < 5.0  # 2.35 bps of charges + 2 bps of slippage


def _chain(day: str, expiry: str, legs: list[list[object]]) -> dict[str, object]:
    return {"d": day, "u": {"NIFTY": {"e": expiry, "opt": legs}}}


def test_expiry_straddle_settles_at_intrinsic_value() -> None:
    rule = ix.BY_ID["H-0041"]
    rows = [
        _chain(
            "2023-06-15",
            "2023-06-15",
            [[18700.0, "CE", 40.0, 5.0, 1], [18700.0, "PE", 35.0, 90.0, 1]],
        )
    ]
    (t,), skipped = ix.trades(rule, rows, {date(2023, 6, 15): (18690.0, 18650.0)})
    assert not skipped and t.settled
    assert (t.call_exit, t.put_exit) == (0.0, 50.0)
    assert t.gross == pytest.approx((75.0 - 50.0) * ix.NOTIONAL / 18690.0)


def test_day_before_rule_buys_back_at_the_close_and_pays_four_legs() -> None:
    rule = ix.BY_ID["H-0105"]
    legs = [[18700.0, "CE", 60.0, 30.0, 1], [18700.0, "PE", 55.0, 40.0, 1]]
    rows = [_chain("2023-06-14", "2023-06-15", legs), _chain("2023-06-15", "2023-06-15", legs)]
    index = {date(2023, 6, 14): (18705.0, 18700.0), date(2023, 6, 15): (18700.0, 18700.0)}
    (t,), _ = ix.trades(rule, rows, index)
    assert t.day == date(2023, 6, 14) and not t.settled
    units = ix.NOTIONAL / 18705.0
    assert t.gross == pytest.approx(45.0 * units)
    assert t.costs > 4 * ix.SLIPPAGE_POINTS * units


def test_expiry_rule_skips_a_strike_that_did_not_trade() -> None:
    rule = ix.BY_ID["H-0041"]
    rows = [_chain("2023-06-15", "2023-06-15", [[18700.0, "CE", None, None, 0]])]
    found, skipped = ix.trades(rule, rows, {date(2023, 6, 15): (18690.0, 18650.0)})
    assert found == [] and len(skipped) == 1


def test_ban_exit_is_the_first_day_out_of_the_list() -> None:
    lists = {
        date(2023, 1, 2): {"A"},
        date(2023, 1, 3): {"A", "B"},
        date(2023, 1, 4): {"B"},
        date(2023, 1, 5): set(),
    }
    exits = rep.ban_exits(lists)
    assert dict(exits) == {"A": {date(2023, 1, 4): 1.0}, "B": {date(2023, 1, 5): 1.0}}


def test_battery_knows_the_new_cards() -> None:
    for card in (
        "H-0041",
        "H-0099",
        "H-0100",
        "H-0101",
        "H-0102",
        "H-0103",
        "H-0104",
        "H-0105",
        "H-0106",
    ):
        assert intraday.supported(card)


def test_battery_reads_a_straddle_like_a_stock_trade() -> None:
    t = ix.Trade("NIFTY", date(2023, 6, 15), 18700.0, 40.0, 35.0, 0.0, 50.0, 10.0, True)
    returns = intraday.daily_returns([t], [date(2023, 6, 15), date(2023, 6, 16)], 1000.0)
    assert returns[date(2023, 6, 16)] == 0.0
    assert returns[date(2023, 6, 15)] == pytest.approx((t.gross - t.costs) / 1000.0)


# --- research 167: fades after NSE queries --------------------------------------------

from array import array  # noqa: E402

from eulerlab.intraday import minute_six_screen as six  # noqa: E402
from eulerlab.intraday import nse_query_screen as q  # noqa: E402


def _snap(last_close: float, closes_at: float = 100.0) -> six.Snap:
    n = len(six.CHECKPOINTS)
    return six.Snap(
        5,
        100.0,
        355,
        99.0,
        array("d", [closes_at] * n),
        array("d", [100.5] * n),
        array("h", [m + 1 for m in six.CHECKPOINTS]),
        last_close,
        1e7,
        None,
    )


def test_outside_hours_query_fades_the_three_session_move_next_session() -> None:
    days = _weekdays(date(2023, 1, 2), 6)
    snaps = {
        "ABC": {
            days[0]: _snap(100.0),
            days[1]: _snap(101.0),
            days[2]: _snap(102.0),
            days[3]: _snap(104.0),
            days[4]: _snap(104.0),
        }
    }
    event = q.Event("ABC", "spurt", days[3], 400)  # posted after the close on day 3
    (found,) = q.candidates(q.BY_ID["H-0107"], [event], snaps, days)
    day, symbol, fill, size = found
    assert (day, symbol, fill.direction) == (days[4], "ABC", -1)
    assert size == pytest.approx(0.04)


def test_in_hours_query_trades_from_the_next_five_minute_close() -> None:
    days = _weekdays(date(2023, 1, 2), 2)
    snaps = {"ABC": {days[0]: _snap(100.0), days[1]: _snap(100.0, closes_at=97.0)}}
    event = q.Event("ABC", "news", days[1], 62)  # 10:17 -> the 10:20 close
    (found,) = q.candidates(q.BY_ID["H-0110"], [event], snaps, days)
    assert found[2].direction == 1 and found[2].minute == 65


def test_a_small_move_is_not_traded_and_in_hours_events_skip_next_session_rules() -> None:
    days = _weekdays(date(2023, 1, 2), 3)
    snaps = {"ABC": {d: _snap(100.0) for d in days}}
    assert (
        q.candidates(q.BY_ID["H-0108"], [q.Event("ABC", "news", days[1], 400)], snaps, days) == []
    )
    assert (
        q.candidates(q.BY_ID["H-0108"], [q.Event("ABC", "news", days[1], 100)], snaps, days) == []
    )
