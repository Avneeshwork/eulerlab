"""Mukherjee & Mandal (2025): candle colour and VIX change against the next gap.

Research 072. Days here are written by hand so every count can be read off.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from eulerlab.research import gap_forecast as gf
from eulerlab.research.session_studies import Overnight

D0 = date(2026, 6, 1)


def day(
    offset: int,
    open_: float,
    close: float,
    vix_open: float,
    vix_close: float,
    vix_previous: float | None = None,
) -> gf.Day:
    return gf.Day(D0 + timedelta(days=offset), open_, close, vix_open, vix_close, vix_previous)


GREEN_CALM = day(0, 100, 102, 15, 14)
RED_FEAR = day(1, 102, 100, 14, 16)
GREEN_FEAR = day(2, 100, 101, 14, 15)
RED_CALM = day(3, 101, 100, 15, 14)
DOJI = day(4, 100, 100, 14, 14)


def test_the_candle_is_close_against_open_and_a_doji_is_no_signal() -> None:
    assert GREEN_CALM.candle == "up" and RED_FEAR.candle == "down" and DOJI.candle is None


def test_the_papers_vix_change_is_close_minus_open_the_same_day() -> None:
    mixed = day(0, 100, 101, 15.0, 14.0, vix_previous=13.0)  # fell in the day, up on yesterday
    assert mixed.vix_move(gf.VixChange.INTRADAY) == "down"
    assert mixed.vix_move(gf.VixChange.CLOSE_TO_CLOSE) == "up"
    assert DOJI.vix_move() is None, "a flat VIX is left out, as the paper's 8 rows are"
    assert GREEN_CALM.vix_move(gf.VixChange.CLOSE_TO_CLOSE) is None, "no previous close known"


def test_each_model_predicts_what_the_paper_says() -> None:
    assert gf.predict(gf.Model.VIX, RED_FEAR) == "down", "VIX up -> gap down"
    assert gf.predict(gf.Model.VIX, RED_CALM) == "up", "VIX down -> gap up"
    assert gf.predict(gf.Model.CANDLE, GREEN_FEAR) == "up"
    assert gf.predict(gf.Model.CANDLE, RED_CALM) == "down"
    assert gf.predict(gf.Model.JOINT, GREEN_CALM) == "up"
    assert gf.predict(gf.Model.JOINT, RED_FEAR) == "down"
    assert gf.predict(gf.Model.JOINT, GREEN_FEAR) is None, "they disagree: inconclusive"
    assert gf.predict(gf.Model.JOINT, RED_CALM) is None
    assert gf.predict(gf.Model.JOINT, DOJI) is None and gf.predict(gf.Model.VIX, DOJI) is None


def _sample() -> list[gf.Day]:
    """Six sessions. Gaps after each of the first five: up, up, down, up, zero."""
    return [
        day(0, 100, 102, 15, 14),  # green, calm  -> next opens 103: up
        day(1, 103, 101, 14, 16),  # red, fear    -> next opens 102: up   (bear signal wrong)
        day(2, 102, 104, 16, 15),  # green, calm  -> next opens 103: down (bull signal wrong)
        day(3, 103, 102, 15, 17),  # red, fear    -> next opens 104: up   (wrong)
        day(4, 104, 105, 17, 18),  # green, fear  -> next opens 105: no gap, dropped
        day(5, 105, 106, 18, 17),
    ]


def test_a_zero_gap_is_not_an_observation() -> None:
    seen = gf.observations(_sample())
    assert [direction for _, direction in seen] == ["up", "up", "down", "up"]


def test_the_joint_table_counts_and_sets_them_against_the_base_rate() -> None:
    block = gf.tables(_sample())
    assert block["days"] == 4 and block["gap_up_any_day"] == 0.75
    joint = block["joint"]
    bull, bear = joint["rows"]
    assert (bull["signal"], bull["count"], bull["success"]) == ("GREEN & VIX down -> gap up", 2, 1)
    assert (bear["count"], bear["success"]) == (2, 0)
    assert bull["base_rate"] == 0.75 and bull["lift"] == pytest.approx(-0.25)
    assert bear["base_rate"] == 0.25, "a gap down happens on a quarter of all days here"
    assert joint["accuracy"] == 0.25 and joint["inconclusive_days"] == 0
    assert joint["always_predict_up"] == 0.75


def test_the_window_is_on_the_signal_day() -> None:
    sample = _sample()
    early = gf.tables(sample, end=sample[1].day)
    assert early["days"] == 2
    assert gf.tables(sample, start=sample[2].day)["days"] == 2


def test_a_signal_no_better_than_other_days_has_z_zero() -> None:
    assert gf.two_proportion_z(7, 10, 70, 100) == pytest.approx(0.0)
    z = gf.two_proportion_z(80, 100, 600, 1000)
    assert z is not None and z > 3.5
    assert gf.p_value(0.0) == pytest.approx(1.0) and gf.p_value(1.96) == pytest.approx(
        0.05, abs=1e-3
    )
    assert gf.two_proportion_z(0, 0, 5, 10) is None


def test_the_two_vix_definitions_are_counted_when_they_differ() -> None:
    days = [
        day(0, 100, 101, 15, 14, vix_previous=16),  # both down
        day(1, 100, 101, 15, 14, vix_previous=13),  # intraday down, close-to-close up
        day(2, 100, 101, 14, 14, vix_previous=13),  # intraday flat
    ]
    assert gf.agreement(days) == {"same": 1, "differ": 1, "flat_or_unknown": 1}


def _legs(sample: list[gf.Day], opens: list[float], closes: list[float]) -> list[Overnight]:
    """A future that closes at `closes[i]` on day i and opens at `opens[i]` on day i+1."""
    return [
        Overnight(sample[i + 1].day, closes[i], opens[i], closes[i + 1], "2026-06-25")
        for i in range(len(sample) - 1)
    ]


def test_the_trade_is_long_on_a_bullish_night_and_short_on_a_bearish_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gf, "round_trip_cost", lambda day, price: 0.001)
    sample = _sample()
    # Future: close 100 each day; opens next morning 101, 99, 100.5, 102, 100.
    legs = _legs(sample, [101, 99, 100.5, 102, 100], [100, 100, 100, 100, 100, 100])
    both = gf.trade(gf.Model.JOINT, sample, legs)
    # Nights: long +1%, short (future fell 1%) +1%, long +0.5%, short (rose 2%) -2%, none.
    assert (both["nights"], both["long_nights"], both["short_nights"]) == (4, 2, 2)
    assert both["future_gapped_as_predicted"] == 0.75
    assert both["gross"]["total_return"] == pytest.approx(1.01 * 1.01 * 1.005 * 0.98 - 1, abs=1e-6)
    assert both["net"]["total_return"] < both["gross"]["total_return"]
    assert both["net"]["round_trips"] == 4

    long_only = gf.trade(gf.Model.JOINT, sample, legs, side="long")
    assert (long_only["nights"], long_only["short_nights"]) == (2, 0)
    assert long_only["gross"]["total_return"] == pytest.approx(1.01 * 1.005 - 1, abs=1e-6)


def test_the_signal_is_read_from_the_session_before_the_leg() -> None:
    sample = _sample()
    legs = _legs(sample, [101, 99, 100.5, 102, 100], [100, 100, 100, 100, 100, 100])
    # Only signals from day 2 onward: the first two nights are not traded.
    late = gf.trade(gf.Model.JOINT, sample, legs, start=sample[2].day)
    assert late["nights"] == 2 and late["gross"]["days"] == 3


def test_the_yardstick_is_long_every_night() -> None:
    sample = _sample()
    legs = _legs(sample, [101, 99, 100.5, 102, 100], [100, 100, 100, 100, 100, 100])
    always = gf.trade(None, sample, legs)
    assert always["model"] == "every night" and always["nights"] == 5 == always["long_nights"]
    expected = 1.01 * 0.99 * 1.005 * 1.02 * 1.0 - 1
    assert always["gross"]["total_return"] == pytest.approx(expected, abs=1e-6)
