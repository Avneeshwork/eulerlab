"""Black-76 pricing and the inversion back to volatility."""

from __future__ import annotations

import pytest

from eulerlab.master.derivatives import Right
from eulerlab.options.iv import (
    MAX_VOL,
    black76_price,
    implied_vol,
    years_to_expiry,
)

F, K, T, DF = 20000.0, 20000.0, 0.25, 0.99


# --- the round trip, which is the real test ---


@pytest.mark.parametrize("vol", [0.05, 0.12, 0.20, 0.45, 1.0])
@pytest.mark.parametrize("right", [Right.CALL, Right.PUT])
def test_price_then_invert_recovers_the_volatility(vol: float, right: Right) -> None:
    price = black76_price(forward=F, strike=K, years=T, vol=vol, discount=DF, right=right)
    recovered = implied_vol(price=price, forward=F, strike=K, years=T, discount=DF, right=right)
    assert recovered is not None
    assert recovered == pytest.approx(vol, abs=1e-4)


@pytest.mark.parametrize("strike", [16000.0, 19000.0, 20000.0, 21000.0, 25000.0])
def test_the_round_trip_holds_away_from_the_money(strike: float) -> None:
    """Deep out-of-the-money is where a Newton solver diverges, which is why
    this uses bisection."""
    price = black76_price(
        forward=F, strike=strike, years=T, vol=0.18, discount=DF, right=Right.CALL
    )
    recovered = implied_vol(
        price=price, forward=F, strike=strike, years=T, discount=DF, right=Right.CALL
    )
    assert recovered is not None
    assert recovered == pytest.approx(0.18, abs=1e-3)


# --- put-call parity must hold in the pricer itself ---


def test_the_pricer_satisfies_put_call_parity() -> None:
    """If this fails, every parity finding downstream is the pricer's fault."""
    call = black76_price(forward=F, strike=19500.0, years=T, vol=0.2, discount=DF, right=Right.CALL)
    put = black76_price(forward=F, strike=19500.0, years=T, vol=0.2, discount=DF, right=Right.PUT)
    assert call - put == pytest.approx(DF * (F - 19500.0), abs=1e-6)


# --- refusing to answer is a feature ---


def test_a_price_below_intrinsic_has_no_implied_vol() -> None:
    """No volatility can produce it. Clamping to a boundary would hide exactly
    the mispriced contract this sprint is looking for."""
    intrinsic = DF * (F - 18000.0)
    assert (
        implied_vol(
            price=intrinsic * 0.5,
            forward=F,
            strike=18000.0,
            years=T,
            discount=DF,
            right=Right.CALL,
        )
        is None
    )


def test_a_price_above_the_maximum_has_no_implied_vol() -> None:
    ceiling = black76_price(
        forward=F, strike=K, years=T, vol=MAX_VOL, discount=DF, right=Right.CALL
    )
    assert (
        implied_vol(
            price=ceiling * 1.5, forward=F, strike=K, years=T, discount=DF, right=Right.CALL
        )
        is None
    )


def test_a_zero_price_has_no_implied_vol() -> None:
    assert (
        implied_vol(price=0.0, forward=F, strike=K, years=T, discount=DF, right=Right.CALL) is None
    )


def test_an_expired_option_has_no_implied_vol() -> None:
    assert (
        implied_vol(price=100.0, forward=F, strike=K, years=0.0, discount=DF, right=Right.CALL)
        is None
    )


# --- pricing edge cases ---


def test_at_expiry_the_price_is_the_discounted_intrinsic() -> None:
    price = black76_price(
        forward=F, strike=18000.0, years=0.0, vol=0.2, discount=DF, right=Right.CALL
    )
    assert price == pytest.approx(DF * 2000.0)


def test_a_higher_strike_call_is_never_more_expensive() -> None:
    """The monotonicity the arbitrage checks look for, verified in the model
    so a violation in real data cannot be blamed on the pricer."""
    prices = [
        black76_price(forward=F, strike=k, years=T, vol=0.2, discount=DF, right=Right.CALL)
        for k in (18000.0, 19000.0, 20000.0, 21000.0, 22000.0)
    ]
    assert prices == sorted(prices, reverse=True)


def test_more_volatility_is_never_cheaper() -> None:
    prices = [
        black76_price(forward=F, strike=K, years=T, vol=v, discount=DF, right=Right.CALL)
        for v in (0.05, 0.1, 0.2, 0.4)
    ]
    assert prices == sorted(prices)


# --- the day-count convention, a common silent disagreement ---


def test_time_is_measured_in_calendar_days() -> None:
    """Option value decays over calendar time - a weekend costs theta. Using
    trading days would bias every IV by roughly 30%."""
    assert years_to_expiry(365) == pytest.approx(1.0)
    assert years_to_expiry(30) == pytest.approx(30 / 365)


def test_a_negative_day_count_is_clamped_not_negative() -> None:
    assert years_to_expiry(-5) == 0.0
