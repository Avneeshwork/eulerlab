"""Research 166: index-futures rules on 15-minute bars, index-option expiry
straddles, and the F&O ban exit. Synthetic sessions, so each rule's entry,
exit and cost path is pinned without market data."""

from __future__ import annotations

from datetime import date, timedelta
from itertools import pairwise

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


# --- research 168: MFT scalps on 5-minute closes -----------------------------------------

from eulerlab.intraday import mft_screen as mft  # noqa: E402


def _path_snap(closes: list[float], last_close: float = 100.0) -> six.Snap:
    """A snapshot whose checkpoint closes follow `closes`; fills at the close."""
    n = len(six.CHECKPOINTS)
    closes = closes + [closes[-1]] * (n - len(closes))
    return six.Snap(
        5,
        closes[0],
        355,
        closes[-1],
        array("d", closes),
        array("d", closes),
        array("h", [m + 1 for m in six.CHECKPOINTS]),
        last_close,
        1e7,
        None,
    )


def test_held_exits_after_its_holding_time() -> None:
    s = _path_snap([100.0] * 10 + [101.0] * 10)
    sig = mft.held(s, date(2023, 1, 2), "ABC", 1, 15, hold=30)
    assert sig is not None
    assert (sig.entry_minute, sig.exit_minute, sig.reason) == (16, 46, "time")


def test_held_stops_on_a_close() -> None:
    s = _path_snap([100.0] * 5 + [98.0] * 20)
    sig = mft.held(s, date(2023, 1, 2), "ABC", 1, 5, stop=lambda c: c < 99.0)
    assert sig is not None and sig.reason == "stop" and sig.exit == 98.0


def test_book_caps_open_positions_at_ten_and_one_per_stock() -> None:
    d = date(2023, 1, 2)
    sigs = [mft.Signal(d, f"S{i}", 1, 5, 6 + i, 100.0, 300, 101.0, "time") for i in range(12)]
    sigs.append(mft.Signal(d, "S0", 1, 5, 20, 100.0, 300, 101.0, "time"))
    kept = mft.book(sigs)
    assert len(kept) == 10 and [s.symbol for s in kept] == [f"S{i}" for i in range(10)]


def test_noon_pullback_buys_a_trend_stock_below_its_high() -> None:
    d0, d1 = _weekdays(date(2023, 1, 2), 2)
    path = [103.0] * 20 + [104.0] * 10 + [103.3] * 10  # up 3.3%, 0.7% off the high at 12:00
    mk = mft.Market(
        snaps={"ABC": {d0: _path_snap([100.0]), d1: _path_snap(path)}},
        sessions=[d1],
        nifty={d1: [20_000.0] * 375},
        nifty_prev={d1: 19_900.0},
        beta={},
        liquid={d1: ["ABC"]},
        industry={},
        previous={d1: d0},
    )
    (sig,) = list(mft.h0118(mk, d1))
    assert (sig.direction, sig.decided, sig.exit_minute) == (1, 165, 355)


def _one_stock_market(today: list[float], prev_close: float = 100.0) -> tuple[mft.Market, date]:
    d0, d1 = _weekdays(date(2023, 1, 2), 2)
    mk = mft.Market(
        snaps={"ABC": {d0: _path_snap([prev_close], last_close=prev_close), d1: _path_snap(today)}},
        sessions=[d1],
        nifty={d1: [20_000.0] * 375},
        nifty_prev={d1: 19_900.0},
        beta={},
        liquid={d1: ["ABC"]},
        industry={},
        previous={d1: d0},
    )
    return mk, d1


def test_afternoon_pullback_is_the_noon_rule_at_1330() -> None:
    path = [103.0] * 40 + [104.0] * 10 + [103.3] * 10  # 0.7% off the high at 13:30
    mk, d1 = _one_stock_market(path)
    (sig,) = list(mft.h0121(mk, d1))
    assert (sig.direction, sig.decided) == (1, 255)


def test_tight_range_break_follows_the_morning_move() -> None:
    path = [101.0] * 11 + [102.0] * 13 + [102.1] * 2 + [102.5] * 10  # +2% by 10:15, tight, then up
    mk, d1 = _one_stock_market(path)
    (sig,) = list(mft.h0124(mk, d1))
    assert sig.direction == 1 and sig.decided == 125


# --- research 170: paper-backed long/short books -------------------------------------------

from eulerlab.intraday import quant_screen as qs  # noqa: E402


def test_long_short_takes_five_each_side_from_the_ranks() -> None:
    days = _weekdays(date(2023, 1, 2), 2)
    names = [f"S{i:02d}" for i in range(20)]
    snaps = {n: {d: _path_snap([100.0]) for d in days} for n in names}
    mk = mft.Market(
        snaps=snaps,
        sessions=[days[1]],
        nifty={days[1]: [20_000.0] * 375},
        nifty_prev={days[1]: 20_000.0},
        beta={},
        liquid={days[1]: names},
        industry={},
        previous={days[1]: days[0]},
    )
    scored = [(float(i), n) for i, n in enumerate(names)]
    sigs = list(qs._long_short(mk, days[1], scored, True, None, 0))
    longs = sorted(s.symbol for s in sigs if s.direction == 1)
    shorts = sorted(s.symbol for s in sigs if s.direction == -1)
    assert longs == names[:5] and shorts == names[-5:]


def test_tug_of_war_score_is_the_mean_overnight_gap() -> None:
    days = _weekdays(date(2023, 1, 2), 17)
    snaps = {"ABC": {d: _path_snap([101.0], last_close=100.0) for d in days}}
    mk = mft.Market(
        snaps=snaps,
        sessions=days,
        nifty={},
        nifty_prev={},
        beta={},
        liquid={},
        industry={},
        previous={b: a for a, b in pairwise(days)},
    )
    assert qs.s0132(mk, "ABC", days[-1]) == pytest.approx(0.01)


def test_the_stricter_screen_needs_both_halves_and_2x_costs() -> None:
    ok = {
        "halves": {"first": {"sharpe": 1.0}, "second": {"sharpe": 0.1}},
        "net_at_2x_costs": {"sharpe": 0.01},
    }
    bad = {
        "halves": {"first": {"sharpe": 1.0}, "second": {"sharpe": 0.1}},
        "net_at_2x_costs": {"sharpe": -0.2},
    }
    assert qs.passes_screen(ok) and not qs.passes_screen(bad)


# --- research 171: 1x rules ------------------------------------------------------------------

from datetime import datetime  # noqa: E402

from eulerlab.intraday import onex_screen as onex  # noqa: E402


def test_news_excludes_administrative_filings() -> None:
    rows = [
        {"symbol": "ABC", "desc": "Trading Window", "exchdisstime": "02-Jan-2023 20:00:00"},
        {"symbol": "ABC", "desc": "Press Release", "exchdisstime": "02-Jan-2023 21:00:00"},
        {"symbol": "XYZ", "desc": "Press Release", "exchdisstime": "02-Jan-2023 21:00:00"},
    ]
    found = onex.news_times(rows, {"ABC"})
    assert list(found) == ["ABC"] and len(found["ABC"]) == 1
    assert found["ABC"][0].hour == 21


def test_no_news_gap_is_faded_and_news_gap_followed() -> None:
    d0, d1 = _weekdays(date(2023, 1, 2), 2)
    mk = mft.Market(
        snaps={"ABC": {d0: _path_snap([100.0], last_close=100.0), d1: _path_snap([103.0])}},
        sessions=[d1],
        nifty={d1: [20_000.0] * 375},
        nifty_prev={d1: 20_000.0},
        beta={},
        liquid={d1: ["ABC"]},
        industry={},
        previous={d1: d0},
    )
    quiet = onex.Context(mk, {}, {}, frozenset())
    (fade,) = list(onex.RULES["H-0141"][1](quiet, d1))
    assert fade.direction == -1
    assert list(onex.RULES["H-0142"][1](quiet, d1)) == []
    news = {"ABC": [datetime(2023, 1, 2, 20, 0, tzinfo=onex.IST)]}
    loud = onex.Context(mk, news, {}, frozenset())
    (follow,) = list(onex.RULES["H-0142"][1](loud, d1))
    assert follow.direction == 1
