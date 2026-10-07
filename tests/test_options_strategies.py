"""Payoffs of research 070's strategies on a hand-built two-expiry market."""

from __future__ import annotations

from datetime import date

import pytest

from eulerlab.options import strategies as st

E1, E2 = date(2024, 1, 25), date(2024, 2, 29)


def _day(d: date, spot: float, **kw: object) -> st.Day:
    return st.Day(
        d,
        spot,
        dict(kw.get("fut", {})),  # type: ignore[call-overload]
        dict(kw.get("calls", {})),  # type: ignore[call-overload]
        dict(kw.get("puts", {})),  # type: ignore[call-overload]
    )


def test_strangle_keeps_the_premium_when_nifty_stays_inside() -> None:
    days = [
        _day(E1, 20_000),
        _day(date(2024, 1, 29), 20_000, calls={(E2, 20_400.0): 100.0}, puts={(E2, 19_600.0): 90.0}),
        _day(E2, 20_100),
    ]
    result = st.short_strangle(days, [E1, E2], leg=1, capital=300_000)
    (period,) = result.periods
    units = 300_000 / (st.STRANGLE_MARGIN * 20_000)  # 100 units
    assert period.pnl == pytest.approx(190 * units - period.costs)
    assert period.costs > 0


def test_strangle_pays_intrinsic_when_nifty_breaks_out() -> None:
    days = [
        _day(E1, 20_000),
        _day(date(2024, 1, 29), 20_000, calls={(E2, 20_400.0): 100.0}, puts={(E2, 19_600.0): 90.0}),
        _day(E2, 21_000),
    ]
    (period,) = st.short_strangle(days, [E1, E2], leg=1, capital=300_000).periods
    assert period.pnl == pytest.approx((190 - 600) * 100 - period.costs)


def test_covered_call_monthly_caps_the_upside_at_the_strike() -> None:
    entry = _day(date(2024, 1, 29), 20_000, fut={E2: 20_050.0}, calls={(E2, 19_000.0): 1_150.0})
    days = [_day(E1, 20_000), entry, _day(E2, 22_000)]
    (period,) = st.covered_call_monthly(days, [E1, E2], capital=2_000_000).periods
    units = 100.0
    # future +1,950; call sold 1,150 and paid 3,000 at expiry: net +100 a unit
    assert period.pnl == pytest.approx(100 * units - period.costs)


def test_a_leg_that_did_not_trade_is_skipped_not_guessed() -> None:
    days = [
        _day(E1, 20_000),
        _day(date(2024, 1, 29), 20_000, calls={(E2, 20_400.0): 100.0}),
        _day(E2, 20_000),
    ]
    result = st.short_strangle(days, [E1, E2], leg=1, capital=300_000)
    assert not result.periods
    assert result.skipped
