"""Which forward and discount the option chain screen prices with (T-4345)."""

from __future__ import annotations

from eulerlab.api.server import _chain_forward
from eulerlab.master.derivatives import Right
from eulerlab.options.iv import greeks


def test_a_fitted_discount_above_one_uses_the_unit_discount_forward() -> None:
    forward, discount, source = _chain_forward((23050.0, 1.0004), 23100.0, 23060.0)
    assert (forward, discount) == (23060.0, 1.0)
    assert "discount at 1" in source


def test_a_plausible_fit_is_used_as_it_is() -> None:
    assert _chain_forward((23050.0, 0.9993), None, 23040.0) == (
        23050.0,
        0.9993,
        "fitted from put-call parity",
    )


def test_no_fit_falls_back_to_the_future_then_to_nothing() -> None:
    assert _chain_forward(None, 23100.0)[:2] == (23100.0, 1.0)
    assert _chain_forward(None, None)[0] is None
    # A fit above 1 with no unit forward is not used either.
    assert _chain_forward((23050.0, 1.002), 23100.0, None)[:2] == (23100.0, 1.0)


def test_a_deep_call_delta_cannot_pass_one_once_the_discount_is_one() -> None:
    """The 22,200 call that showed delta 1.001: deep in the money, 4 days out."""
    _, discount, _ = _chain_forward((23050.0, 1.001), None, 23053.0)
    g = greeks(
        forward=23053.0,
        strike=22200.0,
        years=4 / 365,
        vol=0.046,
        discount=discount,
        right=Right.CALL,
    )
    assert g is not None and g.delta <= 1.0


def test_the_unit_discount_forward_is_the_median_of_c_minus_p_plus_k() -> None:
    from types import SimpleNamespace

    from eulerlab.options.arbitrage import implied_forward_at_unit_discount

    def leg(price: float) -> SimpleNamespace:
        return SimpleNamespace(price=price)

    rows = [(24800, 215.0), (24900, 115.0), (25000, 14.0), (25100, -86.0), (25200, -187.0)]
    chain = SimpleNamespace(
        paired=lambda traded_only=True: [(k, leg(d), leg(0.0)) for k, d in rows]
    )
    assert implied_forward_at_unit_discount(chain) == 25014.0  # type: ignore[arg-type]
