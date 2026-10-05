"""Chain analytics, checked against hand-computable cases.

Written from the mathematics rather than from any implementation: max pain is
a sum of intrinsic payouts, the put-call ratio is a division, and gamma
exposure is gamma times open interest. Each case below is small enough to work
out on paper, which is the only way to tell a correct implementation from a
plausible one.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from eulerlab.master.derivatives import ContractType, Right
from eulerlab.options.analytics import atm_strike, max_pain, put_call_ratio
from eulerlab.options.chain import Chain, Quote

DAY = date(2026, 10, 1)
EXPIRY = date(2026, 10, 27)


def _quote(strike: int, right: Right, *, oi: float = 0.0, volume: float = 0.0) -> Quote:
    return Quote(
        underlying="NIFTY",
        expiry=EXPIRY,
        contract_type=ContractType.OPTION,
        price=100.0,
        strike=Decimal(strike),
        right=right,
        volume=volume,
        open_interest=oi,
    )


def _chain(calls: dict[int, float], puts: dict[int, float], **kw: float) -> Chain:
    chain = Chain(underlying="NIFTY", expiry=EXPIRY, day=DAY)
    for strike, oi in calls.items():
        chain.calls[Decimal(strike)] = _quote(strike, Right.CALL, oi=oi, volume=kw.get("cv", 0.0))
    for strike, oi in puts.items():
        chain.puts[Decimal(strike)] = _quote(strike, Right.PUT, oi=oi, volume=kw.get("pv", 0.0))
    return chain


# --- max pain ---------------------------------------------------------------


def test_max_pain_is_where_writers_owe_least() -> None:
    """All the open interest sits in one call strike, so settling at or below
    it costs writers nothing."""
    chain = _chain(calls={100: 1000.0, 110: 0.0}, puts={100: 0.0, 110: 0.0})
    result = max_pain(chain)
    assert result
    # At 100 the call is at the money and pays nothing; at 110 it owes 10 x 1000.
    assert result.strike == 100.0
    assert result.payout == 0.0


def test_max_pain_balances_calls_against_puts() -> None:
    """Equal OI either side: the minimum sits between them, hand-checkable.

    Settling at 100 costs the put writers 10 x 100 = 1,000.
    Settling at 110 costs the call writers 10 x 100 = 1,000.
    Both are 1,000, and every other listed strike is worse, so the minimum is
    one of the two.
    """
    chain = _chain(calls={100: 100.0, 110: 100.0}, puts={100: 100.0, 110: 100.0})
    result = max_pain(chain)
    assert result
    assert result.strike in (100.0, 110.0)
    assert result.payout == pytest.approx(1000.0)


def test_max_pain_reports_the_whole_curve() -> None:
    """The minimum alone hides whether the curve is sharp or flat, and a flat
    one makes the single number close to meaningless."""
    chain = _chain(calls={100: 10.0, 110: 20.0, 120: 30.0}, puts={100: 5.0})
    result = max_pain(chain)
    assert result
    assert len(result.curve) == 3
    assert min(point[1] for point in result.curve) == result.payout


def test_max_pain_of_an_empty_chain_is_none() -> None:
    assert max_pain(Chain(underlying="NIFTY", expiry=EXPIRY, day=DAY)) is None


# --- put-call ratio ---------------------------------------------------------


def test_put_call_ratio_by_open_interest() -> None:
    chain = _chain(calls={100: 200.0}, puts={100: 300.0})
    ratio = put_call_ratio(chain)
    assert ratio.by_open_interest == pytest.approx(1.5)
    assert ratio.call_open_interest == 200.0
    assert ratio.put_open_interest == 300.0


def test_open_interest_and_volume_ratios_stay_separate() -> None:
    """They answer different questions: positions held against positions
    traded today. Quoting one as 'the PCR' makes a quiet day with heavy
    existing positioning read as a busy one."""
    chain = _chain(calls={100: 1000.0}, puts={100: 100.0}, cv=10.0, pv=90.0)
    ratio = put_call_ratio(chain)
    assert ratio.by_open_interest == pytest.approx(0.1)
    assert ratio.by_volume == pytest.approx(9.0)


def test_no_calls_gives_none_not_infinity() -> None:
    """A division nobody can perform is not a very large number."""
    chain = _chain(calls={}, puts={100: 50.0})
    ratio = put_call_ratio(chain)
    assert ratio.by_open_interest is None
    assert ratio.put_open_interest == 50.0


# --- at the money -----------------------------------------------------------


def test_atm_is_the_nearest_listed_strike() -> None:
    assert atm_strike([Decimal(100), Decimal(110), Decimal(120)], 108.0) == 110.0


def test_atm_without_a_forward_is_none() -> None:
    assert atm_strike([Decimal(100)], 0.0) is None
    assert atm_strike([], 100.0) is None
