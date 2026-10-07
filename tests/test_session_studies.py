"""The calculations for papers the daily engines cannot run (research 064)."""

from __future__ import annotations

from datetime import date

import pytest

from eulerlab.research import session_studies as ss


def test_an_overnight_leg_never_spans_a_roll() -> None:
    expiry_day = {
        "d": "2024-01-25",
        "contracts": {"2024-01-25": {"c": 100.0}, "2024-02-29": {"c": 101.0}},
    }
    next_day = {"d": "2024-01-26", "contracts": {"2024-02-29": {"o": 102.0, "c": 103.0}}}
    leg = ss._leg(expiry_day, next_day)
    assert leg is not None
    assert (leg.expiry, leg.previous_close, leg.open) == ("2024-02-29", 101.0, 102.0)
    # A contract missing on either side gives no leg rather than mixing two.
    assert ss._leg({"d": "2024-01-24", "contracts": {}}, next_day) is None


def test_gap_rates_compare_the_signal_with_any_day() -> None:
    def s(day: int, o: float, c: float) -> ss.Session:
        return ss.Session(date(2024, 1, day), o, c)

    rows = [
        (s(1, 100, 100), 15.0),
        (s(2, 100, 101), 14.0),  # rising, VIX down: calm rise
        (s(3, 102, 101), 15.0),  # gapped up; falling, VIX up: fear fall
        (s(4, 100, 99), 15.0),  # gapped down
    ]
    rates = ss.gap_rates(rows)
    assert rates["calm_rise_gap_up"] == {"signals": 1, "hits": 1, "rate": 1.0}
    assert rates["fear_fall_gap_down"] == {"signals": 1, "hits": 1, "rate": 1.0}
    assert rates["any_day_gap_up"]["signals"] == 2


def test_xirr_and_a_plan_that_doubles() -> None:
    assert ss.xirr([(date(2021, 1, 1), -100.0), (date(2022, 1, 1), 210.0)]) == pytest.approx(
        1.1, abs=1e-3
    )
    closes = [(date(2024, 1, 2), 10.0), (date(2024, 1, 3), 11.0), (date(2024, 2, 1), 20.0)]
    plan = ss.sip(closes, ss.first_of_month, since=date(2024, 1, 1), amount=100.0)
    assert plan["instalments"] == 2
    assert plan["value"] == pytest.approx((10 + 5) * 20.0)


def test_a_futures_round_trip_costs_a_few_basis_points() -> None:
    assert 0.0001 < ss.round_trip_cost(date(2025, 3, 3), 22000.0) < 0.0006


def test_futures_gap_rates_read_the_signal_from_the_day_before() -> None:
    def s(day: int, o: float, c: float) -> ss.Session:
        return ss.Session(date(2024, 1, day), o, c)

    rows = [(s(1, 100, 100), 15.0), (s(2, 100, 101), 14.0), (s(3, 102, 101), 15.0)]
    legs = [
        ss.Overnight(date(2024, 1, 2), 100.0, 99.0, 101.0, "2024-01-25"),
        ss.Overnight(date(2024, 1, 3), 101.0, 102.0, 101.0, "2024-01-25"),
    ]
    rates = ss.futures_gap_rates(legs, rows)
    assert rates["calm_rise_gap_up"] == {"signals": 1, "hits": 1, "rate": 1.0}
    assert rates["any_day_gap_up"] == {"signals": 2, "hits": 1, "rate": 0.5}
