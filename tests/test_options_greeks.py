"""Black-76 Greeks, pinned against identities rather than against a table.

A Greek is the kind of number that is wrong silently: a sign error on theta or
a missing discount factor produces a plausible figure that sits in a portfolio
total for months. So these check relationships that must hold for *any* inputs
— parity, symmetry, the numerical derivative of the price — which a copied
reference value cannot.
"""

from __future__ import annotations

import math

import pytest

from eulerlab.master.derivatives import Right
from eulerlab.options.iv import black76_price, greeks

FORWARD = 22_500.0
YEARS = 30.0 / 365.0
VOL = 0.14
DISCOUNT = 0.995


def _price(strike: float, right: Right, *, vol: float = VOL, years: float = YEARS) -> float:
    return black76_price(
        forward=FORWARD, strike=strike, years=years, vol=vol, discount=DISCOUNT, right=right
    )


def _greeks(strike: float, right: Right, *, vol: float = VOL, years: float = YEARS):  # type: ignore[no-untyped-def]
    return greeks(
        forward=FORWARD, strike=strike, years=years, vol=vol, discount=DISCOUNT, right=right
    )


@pytest.mark.parametrize("strike", [20_000.0, 22_500.0, 25_000.0])
def test_delta_obeys_put_call_parity(strike: float) -> None:
    """C - P = DF*(F - K), so differentiating in F gives dC - dP = DF."""
    call, put = _greeks(strike, Right.CALL), _greeks(strike, Right.PUT)
    assert call and put
    assert call.delta - put.delta == pytest.approx(DISCOUNT, abs=1e-9)


@pytest.mark.parametrize("strike", [20_000.0, 22_500.0, 25_000.0])
def test_gamma_and_vega_are_the_same_for_both_rights(strike: float) -> None:
    """Parity is linear in the forward and carries no vol, so its second
    derivative and its vol sensitivity both vanish."""
    call, put = _greeks(strike, Right.CALL), _greeks(strike, Right.PUT)
    assert call and put
    assert call.gamma == pytest.approx(put.gamma, rel=1e-12)
    assert call.vega == pytest.approx(put.vega, rel=1e-12)


@pytest.mark.parametrize("right", [Right.CALL, Right.PUT])
def test_delta_matches_a_numerical_derivative(right: Right) -> None:
    """The definition, checked against the closed form."""
    strike, bump = 23_000.0, 0.01
    up = black76_price(
        forward=FORWARD + bump, strike=strike, years=YEARS, vol=VOL, discount=DISCOUNT, right=right
    )
    down = black76_price(
        forward=FORWARD - bump, strike=strike, years=YEARS, vol=VOL, discount=DISCOUNT, right=right
    )
    numerical = (up - down) / (2 * bump)
    analytic = _greeks(strike, right)
    assert analytic
    assert analytic.delta == pytest.approx(numerical, rel=1e-5)


def test_vega_matches_a_numerical_derivative() -> None:
    strike, bump = 23_000.0, 1e-5
    up = _price(strike, Right.CALL, vol=VOL + bump)
    down = _price(strike, Right.CALL, vol=VOL - bump)
    analytic = _greeks(strike, Right.CALL)
    assert analytic
    assert analytic.vega == pytest.approx((up - down) / (2 * bump), rel=1e-4)


def test_gamma_matches_a_numerical_second_derivative() -> None:
    strike, bump = 23_000.0, 1.0
    up = black76_price(
        forward=FORWARD + bump,
        strike=strike,
        years=YEARS,
        vol=VOL,
        discount=DISCOUNT,
        right=Right.CALL,
    )
    mid = _price(strike, Right.CALL)
    down = black76_price(
        forward=FORWARD - bump,
        strike=strike,
        years=YEARS,
        vol=VOL,
        discount=DISCOUNT,
        right=Right.CALL,
    )
    analytic = _greeks(strike, Right.CALL)
    assert analytic
    assert analytic.gamma == pytest.approx((up - 2 * mid + down) / (bump * bump), rel=1e-3)


def test_theta_is_negative_for_a_long_at_the_money_option() -> None:
    """The one sign everybody checks, and the one worth pinning."""
    for right in (Right.CALL, Right.PUT):
        result = _greeks(FORWARD, right)
        assert result
        assert result.theta < 0, f"{right} should decay"


def test_theta_matches_the_change_in_value_over_time() -> None:
    """Theta is per year, so a day of decay is theta/365."""
    strike = 22_500.0
    now = _price(strike, Right.CALL)
    tomorrow = _price(strike, Right.CALL, years=YEARS - 1.0 / 365.0)
    analytic = _greeks(strike, Right.CALL)
    assert analytic
    assert (tomorrow - now) == pytest.approx(analytic.theta / 365.0, rel=0.02)


def test_at_the_money_delta_is_about_half() -> None:
    result = _greeks(FORWARD, Right.CALL)
    assert result
    assert 0.5 * DISCOUNT < result.delta < 0.56


def test_gamma_peaks_at_the_money() -> None:
    at = _greeks(FORWARD, Right.CALL)
    away = _greeks(FORWARD * 1.25, Right.CALL)
    assert at and away
    assert at.gamma > away.gamma


def test_undefined_rather_than_zero_at_expiry() -> None:
    """Zero would be averaged into a portfolio total as 'no exposure'."""
    assert (
        greeks(forward=FORWARD, strike=FORWARD, years=0.0, vol=VOL, discount=1.0, right=Right.CALL)
        is None
    )
    assert (
        greeks(
            forward=FORWARD, strike=FORWARD, years=YEARS, vol=0.0, discount=1.0, right=Right.CALL
        )
        is None
    )


def test_vega_is_per_unit_vol_not_per_percent() -> None:
    """A vega already divided by 100 is one that gets divided twice."""
    result = _greeks(FORWARD, Right.CALL)
    assert result
    expected = DISCOUNT * FORWARD * math.sqrt(YEARS) / math.sqrt(2 * math.pi)
    assert result.vega == pytest.approx(expected, rel=0.02)
