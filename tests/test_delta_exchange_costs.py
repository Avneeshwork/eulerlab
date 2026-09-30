"""Delta Exchange India fees.

Crypto has run gross of costs since it landed (S-028). These tests pin the
published schedule so the numbers cannot drift from the source they were read
from, and pin the one arithmetic mistake that would not look wrong.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from eulerlab.costs import delta_exchange as dx
from eulerlab.costs.schedule import Side


def test_the_published_futures_rates() -> None:
    """Fetched 2026-08-22 from delta.exchange/fees and the support article,
    which agree on futures."""
    assert Decimal("0.0002") == dx.MAKER_RATE
    assert Decimal("0.0005") == dx.TAKER_RATE
    assert Decimal("0.18") == dx.GST_RATE


def test_gst_applies_to_the_fee_not_the_notional() -> None:
    """The distinction between 0.059% and 18.05%.

    Applied to the notional it would be a rate no exchange charges and no
    single trade would obviously reveal — the position simply looks unviable
    and the cause looks like the strategy.
    """
    fee = dx.futures_fee(price=Decimal("60000"), quantity=Decimal("1"))
    assert fee.trading_fee == Decimal("30.0000")
    assert fee.gst == Decimal("5.400000")
    assert fee.total == Decimal("35.400000")
    assert fee.effective_rate == pytest.approx(Decimal("0.00059"))


def test_a_taker_round_trip_is_the_number_to_clear() -> None:
    """0.118% of notional, charged whether the trade wins or loses."""
    assert dx.round_trip_rate() == pytest.approx(Decimal("0.00118"))


def test_making_both_legs_is_cheaper_but_has_to_be_argued_for() -> None:
    both = dx.round_trip_rate(maker_in=True, maker_out=True)
    assert both == pytest.approx(Decimal("0.000472"))
    assert both < dx.round_trip_rate()


def test_taker_is_the_default_because_maker_is_a_claim() -> None:
    """Assuming the maker rate assumes a limit order was never crossed, which
    is a claim about queue position this repository's engines cannot support."""
    assert dx.futures_fee(price=Decimal("100"), quantity=Decimal("1")).trading_fee == (
        Decimal("100") * dx.TAKER_RATE
    )


def test_spot_buying_is_free_and_selling_is_not() -> None:
    buy = dx.spot_fee(price=Decimal("1000"), quantity=Decimal("1"), side=Side.BUY)
    sell = dx.spot_fee(price=Decimal("1000"), quantity=Decimal("1"), side=Side.SELL)
    assert buy.total == 0
    assert sell.trading_fee == Decimal("1.000")
    assert sell.gst == Decimal("0.18000")


def test_a_zero_notional_does_not_divide_by_zero() -> None:
    fee = dx.futures_fee(price=Decimal("0"), quantity=Decimal("1"))
    assert fee.effective_rate == 0
