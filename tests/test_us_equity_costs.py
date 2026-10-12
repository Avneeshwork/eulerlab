"""US equity costs, and the routing that decides a trade is charged them.

The bug worth guarding is not an arithmetic one. It is that `asset_class="us"`
used to fall through to the Indian intraday schedule and get billed STT, stamp
duty and GST — the same class of error the Delta model was written to fix,
arriving from the other side. Most of these tests check routing rather than
rates for that reason.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from eulerlab.costs import us_equity
from eulerlab.costs.schedule import Side
from eulerlab.intraday import bracket

PRICED_DAY = dt.date(2026, 6, 15)
"""Inside the sweep window, and after the 2026-04-04 rate step."""


def test_the_cap_binds_at_every_size_this_engine_trades() -> None:
    """The single number that decides whether US intraday works here.

    A typical position is around $500,000 of notional. Uncapped that is $1,250
    of brokerage a leg; capped it is $25. A fiftyfold difference, and the
    difference between every US signal losing and every US signal being cheap
    to run.
    """
    fee = us_equity.equity_fee(
        price=Decimal(500), quantity=Decimal(1000), side=Side.BUY, day=PRICED_DAY
    )
    assert fee.capped
    assert fee.brokerage == us_equity.BROKERAGE_CAP


def test_small_trades_pay_the_percentage() -> None:
    """Below the cap the rate applies, so cost scales with size and then stops."""
    fee = us_equity.equity_fee(
        price=Decimal(100), quantity=Decimal(10), side=Side.BUY, day=PRICED_DAY
    )
    assert not fee.capped
    assert fee.brokerage == Decimal(1000) * us_equity.BROKERAGE_RATE


def test_gst_is_charged_on_top_of_the_cap() -> None:
    """The cap is quoted excluding GST, so 18% lands on the capped figure."""
    fee = us_equity.equity_fee(
        price=Decimal(500), quantity=Decimal(1000), side=Side.BUY, day=PRICED_DAY
    )
    assert fee.gst == us_equity.BROKERAGE_CAP * us_equity.GST_RATE
    assert fee.total == us_equity.BROKERAGE_CAP * (Decimal(1) + us_equity.GST_RATE)


def test_buys_pay_brokerage_but_no_regulatory_fees() -> None:
    """Both pass-throughs are assessed on sales; the broker charges both legs.

    An earlier version asserted a buy was free, which was true of the clearing
    cost and false of the bill. Alpaca is the data source here, not the broker
    the account trades through.
    """
    fee = us_equity.equity_fee(
        price=Decimal(500), quantity=Decimal(200), side=Side.BUY, day=PRICED_DAY
    )
    assert fee.sec_fee == Decimal(0)
    assert fee.taf == Decimal(0)
    assert fee.brokerage == us_equity.BROKERAGE_CAP
    assert fee.total == fee.brokerage + fee.gst


def test_both_legs_pay_the_same_brokerage_and_nothing_else() -> None:
    """Only the 0.25% is charged, by decision — see the module docstring.

    The regulatory fees stay modelled and unused. They are worth $2.09 against
    $500 of brokerage on this trade: leaving them out is 0.6% light on a number
    that decides results by a factor of three.
    """
    fee = us_equity.equity_fee(
        price=Decimal(500), quantity=Decimal(200), side=Side.SELL, day=PRICED_DAY
    )
    assert fee.sec_fee == Decimal(0)
    assert fee.taf == Decimal(0)
    assert fee.brokerage == us_equity.BROKERAGE_CAP
    assert fee.total == fee.brokerage + fee.gst


def test_the_cap_is_absolute_however_large_the_trade() -> None:
    """$10,000,000 of notional pays the same $25 as $10,000 does."""
    fee = us_equity.equity_fee(
        price=Decimal(10), quantity=Decimal(1000000), side=Side.SELL, day=PRICED_DAY
    )
    assert fee.brokerage == us_equity.BROKERAGE_CAP


def test_us_is_cheaper_than_delta_at_the_size_this_engine_trades() -> None:
    """This module has now claimed three different things, in order.

    Regulatory fees only: 0.003%, "US is nearly free". Then 0.25% uncapped:
    0.5%, "US is four times Delta and nothing survives". Then the $25 cap:
    0.012% on a $500,000 position, a tenth of Delta.

    Only the last is right, and the lesson is that a fee model missing its cap
    is not conservative, it is wrong — here by a factor of fifty.
    """
    from eulerlab.costs.delta_exchange import round_trip_rate as delta_rate

    us_rate = us_equity.round_trip_rate(price=Decimal(500), quantity=Decimal(1000), day=PRICED_DAY)
    # Reversed once the cap was applied. At the size this engine trades, a US
    # round trip is a *tenth* of Delta's, not four times it.
    assert us_rate < delta_rate()


def test_bracket_routes_us_away_from_the_indian_schedule() -> None:
    """The regression this module exists for.

    An Indian intraday sell of $100,000 notional carries STT at 0.025% alone —
    about $25 — plus SEBI turnover, stamp duty and GST. The US bill is under
    $3. If the branch is ever removed, this gap is what catches it.
    """
    day = dt.date(2026, 6, 15)

    # The shape, not a threshold. India's charges are percentage-based all the
    # way up; the US brokerage stops at $25. So the two are within sight of
    # each other on a small trade and diverge without limit on a large one, and
    # a routing bug would show as the gap failing to widen.
    small_us = bracket._cost(500.0, 200, Side.SELL, day, "us")
    small_in = bracket._cost(500.0, 200, Side.SELL, day, "equity")
    big_us = bracket._cost(500.0, 4000, Side.SELL, day, "us")
    big_in = bracket._cost(500.0, 4000, Side.SELL, day, "equity")

    assert small_us > 0
    assert small_us < small_in
    assert big_us / big_in < small_us / small_in / 10


def test_bracket_charges_us_buys_the_broker_fee() -> None:
    """A buy pays no SEC or FINRA fee and still costs 0.25%."""
    day = dt.date(2026, 6, 15)
    cost = bracket._cost(500.0, 200, Side.BUY, day, "us")
    assert cost == pytest.approx(25 * 1.18)


def test_currency_conversion_is_not_charged_per_trade() -> None:
    """It is a cost on moving capital, not on trading.

    A strategy that funds an account once and trades it a hundred times pays
    the markup twice, not two hundred times. Charging it per fill would inflate
    an active strategy's costs by its own turnover.
    """
    fee = us_equity.equity_fee(
        price=Decimal(500), quantity=Decimal(1000), side=Side.BUY, day=PRICED_DAY
    )
    lowest_markup = us_equity.FX_MARKUP_RANGE[0] * fee.notional
    assert fee.total < lowest_markup


def test_the_rate_steps_on_its_effective_date() -> None:
    """Fiscal 2026 opened at zero and restarted at $20.60 on 2026-04-04.

    The first draft of this module hardcoded $27.80 — the fiscal 2025 rate —
    which overcharges every 2026 backtest by a third and charges a January one
    for a fee that did not exist. Verified against FINRA Information Notice
    03/17/26.
    """
    assert us_equity.sec_rate(dt.date(2026, 4, 3)) == Decimal(0)
    assert us_equity.sec_rate(dt.date(2026, 4, 4)) == Decimal("0.0000206")
    assert us_equity.sec_rate(dt.date(2026, 8, 20)) == Decimal("0.0000206")


def test_the_rate_schedule_still_works_though_nothing_charges_it() -> None:
    """Kept because it was verified against the regulator and is costly to redo.

    If the pass-throughs are ever switched back on, this is the part that has
    to still be right.
    """
    assert us_equity.sec_rate(dt.date(2026, 4, 3)) == Decimal(0)
    assert us_equity.sec_rate(dt.date(2026, 4, 4)) == Decimal("0.0000206")


def test_dates_before_the_schedule_are_refused() -> None:
    """Rather than priced with a rate this module has not verified.

    A backtest silently charging 2019 at the 2026 rate emits a number that
    looks like every other number here, and nothing downstream can tell it
    apart.
    """
    with pytest.raises(us_equity.RateUnavailable):
        us_equity.sec_rate(dt.date(2019, 1, 1))
