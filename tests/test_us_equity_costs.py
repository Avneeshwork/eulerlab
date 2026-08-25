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


def test_buys_pay_nothing() -> None:
    """Both US pass-throughs are assessed on sales, so a buy is genuinely free."""
    fee = us_equity.equity_fee(
        price=Decimal("500"), quantity=Decimal("200"), side=Side.BUY, day=PRICED_DAY
    )
    assert fee.total == Decimal("0")
    assert fee.sec_fee == Decimal("0")
    assert fee.taf == Decimal("0")


def test_sells_pay_sec_and_taf() -> None:
    fee = us_equity.equity_fee(
        price=Decimal("500"), quantity=Decimal("200"), side=Side.SELL, day=PRICED_DAY
    )
    # $100,000 notional at the fiscal-2026 rate of $20.60 per million.
    assert fee.sec_fee == Decimal("100000") * us_equity.sec_rate(PRICED_DAY)
    assert fee.taf == Decimal("200") * us_equity.TAF_PER_SHARE
    assert fee.commission == Decimal("0")


def test_taf_is_capped() -> None:
    """The cap binds on large size, which is why the fee is itemised."""
    fee = us_equity.equity_fee(
        price=Decimal("10"), quantity=Decimal("1000000"), side=Side.SELL, day=PRICED_DAY
    )
    assert fee.taf == us_equity.TAF_CAP


def test_round_trip_is_far_cheaper_than_delta() -> None:
    """The comparison that reframes every crypto result in this repository.

    Not a tolerance check on a magic number: the point is the order of
    magnitude. US friction is basis points of a basis point; Delta's is over a
    tenth of a percent.
    """
    from eulerlab.costs.delta_exchange import round_trip_rate as delta_rate

    us_rate = us_equity.round_trip_rate(
        price=Decimal("500"), quantity=Decimal("200"), day=PRICED_DAY
    )
    assert us_rate < delta_rate() / 20


def test_bracket_routes_us_away_from_the_indian_schedule() -> None:
    """The regression this module exists for.

    An Indian intraday sell of $100,000 notional carries STT at 0.025% alone —
    about $25 — plus SEBI turnover, stamp duty and GST. The US bill is under
    $3. If the branch is ever removed, this gap is what catches it.
    """
    day = dt.date(2026, 6, 15)
    us_cost = bracket._cost(500.0, 200, Side.SELL, day, "us")
    india_cost = bracket._cost(500.0, 200, Side.SELL, day, "equity")
    assert us_cost < india_cost / 5
    assert us_cost > 0


def test_bracket_charges_us_buys_nothing() -> None:
    day = dt.date(2026, 6, 15)
    assert bracket._cost(500.0, 200, Side.BUY, day, "us") == 0.0


def test_the_rate_steps_on_its_effective_date() -> None:
    """Fiscal 2026 opened at zero and restarted at $20.60 on 2026-04-04.

    The first draft of this module hardcoded $27.80 — the fiscal 2025 rate —
    which overcharges every 2026 backtest by a third and charges a January one
    for a fee that did not exist. Verified against FINRA Information Notice
    03/17/26.
    """
    assert us_equity.sec_rate(dt.date(2026, 4, 3)) == Decimal("0")
    assert us_equity.sec_rate(dt.date(2026, 4, 4)) == Decimal("0.0000206")
    assert us_equity.sec_rate(dt.date(2026, 8, 20)) == Decimal("0.0000206")


def test_a_zero_rate_still_charges_the_taf() -> None:
    """Zero Section 31 is a real rate, not a missing one — the TAF is separate."""
    fee = us_equity.equity_fee(
        price=Decimal("500"),
        quantity=Decimal("200"),
        side=Side.SELL,
        day=dt.date(2026, 2, 1),
    )
    assert fee.sec_fee == Decimal("0")
    assert fee.taf > Decimal("0")


def test_dates_before_the_schedule_are_refused() -> None:
    """Rather than priced with a rate this module has not verified.

    A backtest silently charging 2019 at the 2026 rate emits a number that
    looks like every other number here, and nothing downstream can tell it
    apart.
    """
    with pytest.raises(us_equity.RateUnavailable):
        us_equity.sec_rate(dt.date(2019, 1, 1))
