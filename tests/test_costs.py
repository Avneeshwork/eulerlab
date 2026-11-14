"""Transaction costs: sides, time-versioning, and the STT trap.

The published worked examples are the anchors. Everything else checks that a
charge falls on the leg that actually bears it, because a model that averages
the legs loses exactly the asymmetry that makes turnover expensive.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from eulerlab.costs.model import (
    Brokerage,
    cost_of_exercise,
    cost_of_trade,
    round_trip,
)
from eulerlab.costs.schedule import ExerciseBasis, Segment, Side, rates_on

LAKH = Decimal(100000)


# --- the published anchor ---


def test_the_exercise_example_matches_the_published_figure() -> None:
    """Zerodha's worked example: 50 units, strike 17,300, settlement 17,350.
    Intrinsic 2,500, STT 0.15% = Rs 3.75 (they print 'Rs 4, 3.75 rounded up').
    """
    cost = cost_of_exercise(
        trade_date=date(2026, 8, 1),
        settlement_price=Decimal(17350),
        strike=Decimal(17300),
        quantity=50,
    )
    assert cost.stt == Decimal("3.75")
    assert cost.turnover == Decimal(2500)


def test_the_pre_2019_rule_charges_the_full_notional() -> None:
    """The STT trap. The same expiry before 2019-09-01 is charged on the
    settlement value, not the intrinsic - Rs 1,084 on a Rs 2,500 profit."""
    cost = cost_of_exercise(
        trade_date=date(2018, 6, 1),
        settlement_price=Decimal(17350),
        strike=Decimal(17300),
        quantity=50,
    )
    assert cost.turnover == Decimal(867500)
    assert cost.stt > Decimal(1000)


def test_the_trap_could_exceed_the_profit_it_taxed() -> None:
    """Why traders abandoned in-the-money options before 2019: one point in
    the money on a large notional cost more than the point was worth."""
    profit = Decimal(1) * 50
    cost = cost_of_exercise(
        trade_date=date(2018, 6, 1),
        settlement_price=Decimal(17301),
        strike=Decimal(17300),
        quantity=50,
    )
    assert cost.stt > profit


def test_the_basis_switches_on_the_stated_date() -> None:
    assert rates_on(date(2019, 8, 31)).exercise_basis is ExerciseBasis.NOTIONAL
    assert rates_on(date(2019, 9, 1)).exercise_basis is ExerciseBasis.INTRINSIC


# --- time versioning ---


def test_futures_stt_quadrupled_across_the_backtest_window() -> None:
    """A constants file would apply today's rate to a 2016 trade and be wrong
    by a factor of four."""
    assert rates_on(date(2016, 1, 1)).stt_futures_sell == 0.000125
    assert rates_on(date(2025, 1, 1)).stt_futures_sell == 0.0002
    assert rates_on(date(2026, 8, 1)).stt_futures_sell == 0.0005


def test_the_same_trade_costs_more_at_later_rates() -> None:
    args = {
        "segment": Segment.FUTURES,
        "side": Side.SELL,
        "price": Decimal(20000),
        "quantity": 50,
    }
    old = cost_of_trade(trade_date=date(2016, 1, 1), **args)  # type: ignore[arg-type]
    new = cost_of_trade(trade_date=date(2026, 8, 1), **args)  # type: ignore[arg-type]
    assert new.stt > old.stt * 3


def test_a_date_before_the_schedule_raises_rather_than_guessing() -> None:
    """Silently costing a 1999 trade with later rates is the failure mode this
    prevents. The schedule starts 2000-01-01 (research 196)."""
    with pytest.raises(ValueError, match="no cost schedule covers"):
        rates_on(date(1999, 12, 31))


def test_old_years_are_never_cheaper_than_today() -> None:
    """Operator, 2026-11-14: each pre-2015 rate is the higher of its dated
    rate and today's."""
    from dataclasses import fields

    from eulerlab.costs.schedule import SCHEDULE, TODAY

    old = [r for r in SCHEDULE if r.effective_from < date(2015, 1, 1)]
    assert old and old[0].effective_from == date(2000, 1, 1)
    for rates in old:
        for f in fields(rates):
            value = getattr(rates, f.name)
            if isinstance(value, float):
                assert value >= getattr(TODAY, f.name), (rates.effective_from, f.name)


def test_the_dated_pre_2015_rates_that_exceed_today_apply() -> None:
    assert rates_on(date(2005, 1, 3)).stt_delivery == 0.001  # 0.075% then, 0.1% today
    assert rates_on(date(2008, 6, 2)).stt_delivery == 0.00125  # above today's 0.1%
    assert rates_on(date(2012, 7, 2)).stt_delivery == 0.001
    assert rates_on(date(2009, 9, 30)).exchange_txn_cash == 0.000035
    assert rates_on(date(2009, 10, 1)).exchange_txn_cash == 0.0000325
    assert rates_on(date(2008, 6, 2)).gst == 0.18  # service tax 12.36% then, below GST
    assert rates_on(date(2014, 12, 31)).stamp_delivery_buy == 0.00015


def test_equity_rates_did_not_change() -> None:
    for day in (date(2016, 1, 1), date(2026, 8, 1)):
        assert rates_on(day).stt_delivery == 0.001
        assert rates_on(day).stt_intraday_sell == 0.00025


# --- which leg bears which charge ---


def test_delivery_stt_falls_on_both_legs() -> None:
    for side in (Side.BUY, Side.SELL):
        cost = cost_of_trade(
            trade_date=date(2026, 8, 1),
            segment=Segment.EQUITY_DELIVERY,
            side=side,
            price=Decimal(1000),
            quantity=100,
        )
        assert cost.stt == Decimal("100.00")


def test_intraday_stt_falls_only_on_the_sell() -> None:
    """Charging both legs would roughly double STT on every round trip."""
    common = {
        "trade_date": date(2026, 8, 1),
        "segment": Segment.EQUITY_INTRADAY,
        "price": Decimal(1000),
        "quantity": 100,
    }
    assert cost_of_trade(side=Side.BUY, **common).stt == Decimal(0)  # type: ignore[arg-type]
    assert cost_of_trade(side=Side.SELL, **common).stt > Decimal(0)  # type: ignore[arg-type]


def test_futures_stt_falls_only_on_the_sell() -> None:
    common = {
        "trade_date": date(2026, 8, 1),
        "segment": Segment.FUTURES,
        "price": Decimal(20000),
        "quantity": 50,
    }
    assert cost_of_trade(side=Side.BUY, **common).stt == Decimal(0)  # type: ignore[arg-type]
    assert cost_of_trade(side=Side.SELL, **common).stt > Decimal(0)  # type: ignore[arg-type]


def test_stamp_duty_falls_only_on_the_buy() -> None:
    common = {
        "trade_date": date(2026, 8, 1),
        "segment": Segment.EQUITY_DELIVERY,
        "price": Decimal(1000),
        "quantity": 100,
    }
    assert cost_of_trade(side=Side.BUY, **common).stamp_duty > Decimal(0)  # type: ignore[arg-type]
    assert cost_of_trade(side=Side.SELL, **common).stamp_duty == Decimal(0)  # type: ignore[arg-type]


# --- GST, the easiest thing to get catastrophically wrong ---


def test_gst_is_charged_on_fees_not_on_turnover() -> None:
    """18% of turnover would overstate costs by three orders of magnitude and
    reject every strategy ever written."""
    cost = cost_of_trade(
        trade_date=date(2026, 8, 1),
        segment=Segment.EQUITY_INTRADAY,
        side=Side.SELL,
        price=Decimal(1000),
        quantity=100,
    )
    expected = (cost.brokerage + cost.exchange_txn) * Decimal("0.18")
    assert abs(cost.gst - expected) <= Decimal("0.01")
    assert cost.gst < cost.turnover * Decimal("0.001")


# --- brokerage ---


def test_delivery_brokerage_is_free_by_default() -> None:
    cost = cost_of_trade(
        trade_date=date(2026, 8, 1),
        segment=Segment.EQUITY_DELIVERY,
        side=Side.BUY,
        price=Decimal(1000),
        quantity=100,
    )
    assert cost.brokerage == Decimal(0)


def test_intraday_brokerage_is_capped() -> None:
    """0.03% or Rs 20, whichever is lower - the cap binds on any large order."""
    cost = cost_of_trade(
        trade_date=date(2026, 8, 1),
        segment=Segment.EQUITY_INTRADAY,
        side=Side.BUY,
        price=Decimal(10000),
        quantity=1000,
    )
    assert cost.brokerage == Decimal("20.00")


def test_brokerage_is_configurable_not_hardcoded() -> None:
    """It is the one line here that is a commercial choice rather than a
    statutory rate."""
    free = Brokerage(intraday_pct=Decimal(0), intraday_cap=Decimal(0))
    cost = cost_of_trade(
        trade_date=date(2026, 8, 1),
        segment=Segment.EQUITY_INTRADAY,
        side=Side.BUY,
        price=Decimal(1000),
        quantity=100,
        brokerage=free,
    )
    assert cost.brokerage == Decimal(0)


# --- round trip ---


def test_a_round_trip_pays_stamp_once_and_stt_once() -> None:
    """The asymmetry that a blended percentage would lose."""
    trip = round_trip(
        trade_date=date(2026, 8, 1),
        segment=Segment.EQUITY_INTRADAY,
        entry_price=Decimal(1000),
        exit_price=Decimal(1000),
        quantity=100,
    )
    one_leg_stamp = cost_of_trade(
        trade_date=date(2026, 8, 1),
        segment=Segment.EQUITY_INTRADAY,
        side=Side.BUY,
        price=Decimal(1000),
        quantity=100,
    ).stamp_duty
    assert trip.stamp_duty == one_leg_stamp


def test_the_breakdown_totals_its_own_lines() -> None:
    trip = round_trip(
        trade_date=date(2026, 8, 1),
        segment=Segment.EQUITY_DELIVERY,
        entry_price=Decimal(1500),
        exit_price=Decimal(1600),
        quantity=50,
    )
    assert trip.total == sum(v for _, v in trip.lines())


def test_cost_in_basis_points_is_reported() -> None:
    trip = round_trip(
        trade_date=date(2026, 8, 1),
        segment=Segment.EQUITY_DELIVERY,
        entry_price=Decimal(1000),
        exit_price=Decimal(1000),
        quantity=100,
    )
    assert Decimal(5) < trip.bps < Decimal(50)


def test_a_zero_turnover_breakdown_does_not_divide_by_zero() -> None:
    cost = cost_of_exercise(
        trade_date=date(2026, 8, 1),
        settlement_price=Decimal(100),
        strike=Decimal(200),
        quantity=50,
    )
    assert cost.turnover == Decimal(0)
    assert cost.bps == Decimal(0)


def test_an_out_of_the_money_option_has_no_intrinsic_value_to_tax() -> None:
    cost = cost_of_exercise(
        trade_date=date(2026, 8, 1),
        settlement_price=Decimal(17000),
        strike=Decimal(17300),
        quantity=50,
    )
    assert cost.stt == Decimal(0)


def test_a_put_takes_intrinsic_from_the_other_direction() -> None:
    cost = cost_of_exercise(
        trade_date=date(2026, 8, 1),
        settlement_price=Decimal(17000),
        strike=Decimal(17300),
        quantity=50,
        is_call=False,
    )
    assert cost.turnover == Decimal(15000)


def test_an_etf_unit_pays_stt_on_the_sale_only_at_a_hundredth_of_a_share() -> None:
    """HISTORY #18: an equity-oriented fund unit is not a share (research 066)."""
    from datetime import date
    from decimal import Decimal

    from eulerlab.costs.model import cost_of_trade
    from eulerlab.costs.schedule import Segment, Side

    def stt(side: Side, *, fund_unit: bool) -> Decimal:
        return cost_of_trade(
            trade_date=date(2024, 6, 3),
            segment=Segment.EQUITY_DELIVERY,
            side=side,
            price=Decimal(250),
            quantity=4000,
            fund_unit=fund_unit,
        ).stt

    assert stt(Side.BUY, fund_unit=False) == Decimal("1000.00")
    assert stt(Side.SELL, fund_unit=False) == Decimal("1000.00")
    assert stt(Side.BUY, fund_unit=True) == Decimal(0)
    assert stt(Side.SELL, fund_unit=True) == Decimal("10.00")
