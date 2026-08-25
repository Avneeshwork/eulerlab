"""US equity execution costs, for the Alpaca-landed side of the library.

Written because a `us` sweep otherwise fell through to `Segment.EQUITY_INTRADAY`
and was charged **STT, SEBI turnover fees, stamp duty and GST on brokerage** —
an Indian bill for a trade on Nasdaq. That is the same mistake the Delta module
was written to fix, arriving from the other direction, and it flatters or
punishes at roughly ten basis points a round trip depending on nothing real.

### Sourced, not assumed

Alpaca charges **no commission** on US equities. What remains are the two
regulatory pass-throughs every US broker collects on the **sell side only**:

| | rate | applies to | source |
|---|---|---|---|
| SEC Section 31 fee | **$0.00** per million through 2026-04-03 | sells | FINRA Information Notice 03/17/26 |
| SEC Section 31 fee | **$20.60** per million from 2026-04-04 | sells | same |
| FINRA Trading Activity Fee | $0.000166 per share, capped $8.30 | sells | FINRA TAF guidance |
| Commission | $0 | — | Alpaca |

Both are sell-side by construction — Section 31 is assessed on the proceeds of
a sale, and the TAF on covered sales — so a round trip pays each exactly once.
The combined bill on a $100,000 round trip is about **$2**, against roughly
**$118** for the same notional on Delta. That gap is not a detail: the crypto
result in this repository is 88% fees, and the same signal on US equity is
charged a fiftieth as much.

### The rate changes, so it is a function of the date, not a constant

The first draft of this module hardcoded **$27.80** per million, which is a real
Section 31 rate — for fiscal 2025. The fiscal 2026 rate is $20.60, and for the
first half of 2026 it was **zero**: the SEC sets the rate to $0.00 once the
year's collections are met and restarts it when the next appropriation lands.
A flat constant would therefore have overcharged every 2026 backtest by a third
and every January-March one infinitely.

`_cost` already receives the trade date, so the rate is looked up from it. The
table below is a schedule of published rates with their effective dates, not a
current value — a window spanning 2026-04-04 is charged correctly on both
sides of it. Rates before fiscal 2026 are deliberately absent rather than
guessed; a date earlier than the table asks for a rate this module has not
verified, and it says so instead of extrapolating.

### What is deliberately absent

**Spread and slippage.** Fills here come from minute bars, and a bar's high and
low are not a book — modelling half a spread on top would put a made-up number
beside a measured one and make the total look more precise than its worst
component. The NSE and Delta models make the same omission, so the three remain
comparable to each other.

**Borrow on shorts, and payment for order flow.** The first applies to
positions this engine does not hold overnight; the second is a rebate the
broker receives, not a cost the trader pays.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from eulerlab.costs.schedule import Side

SEC_SCHEDULE: tuple[tuple[date, Decimal], ...] = (
    # (effective date, rate per unit notional). Sell side only, and read as
    # "this rate applies from this date until the next row".
    #
    # Verified 2026-08-25 against FINRA Information Notice 03/17/26, which
    # states the rate rose from $0.00 to $20.60 per million on 2026-04-04.
    # The SEC's own advisory page returns 403 to automated fetches, so the
    # regulator's notice republishing the order is the primary source used.
    (date(2025, 10, 1), Decimal("0")),  # fiscal 2026 opened at zero
    (date(2026, 4, 4), Decimal("0.0000206")),  # $20.60 per million
)
"""Published Section 31 rates and the dates they took effect.

A schedule rather than a constant because the rate genuinely moves, including
to zero: the SEC stops collecting once the year's target is met. See the module
docstring for what the first draft of this got wrong."""

SEC_SCHEDULE_FROM = SEC_SCHEDULE[0][0]
"""Earliest date this module will price. Before it, `sec_rate` refuses."""

TAF_PER_SHARE = Decimal("0.000166")
"""FINRA Trading Activity Fee, per share sold."""

TAF_CAP = Decimal("8.30")
"""Per-trade ceiling on the TAF. Binds above ~50,000 shares."""

COMMISSION = Decimal("0")
"""Alpaca charges none on US equities."""


class RateUnavailable(LookupError):
    """Asked for a Section 31 rate on a date the schedule does not cover.

    Raised rather than falling back to the nearest known rate. A backtest that
    silently prices 2019 with the 2026 schedule produces a number that looks
    like every other number this platform emits, and nothing downstream can
    tell it apart."""


def sec_rate(day: date) -> Decimal:
    """The Section 31 rate in force on a given date.

    Walks the schedule backwards to the first row that had taken effect. The
    zero row is a real rate, not a missing one — for the first half of fiscal
    2026 sales genuinely cost nothing under Section 31.
    """
    if day < SEC_SCHEDULE_FROM:
        raise RateUnavailable(
            f"no verified Section 31 rate for {day.isoformat()}; "
            f"schedule begins {SEC_SCHEDULE_FROM.isoformat()}"
        )
    rate = SEC_SCHEDULE[0][1]
    for effective, value in SEC_SCHEDULE:
        if day >= effective:
            rate = value
    return rate


@dataclass(frozen=True)
class Fee:
    """One leg's bill, itemised.

    Kept itemised rather than summed because the interesting question about a
    US result is usually which component binds — the TAF cap turns the fee into
    a flat charge on large size, and a total alone hides that.
    """

    notional: Decimal
    sec_fee: Decimal
    taf: Decimal
    commission: Decimal = COMMISSION

    @property
    def total(self) -> Decimal:
        return self.sec_fee + self.taf + self.commission


def equity_fee(*, price: Decimal, quantity: Decimal, side: Side, day: date) -> Fee:
    """Cost of one US equity leg on a given date.

    Buys are free of both pass-throughs, so this returns a zero bill for them
    rather than half of one. That is not an approximation — Section 31 and the
    TAF are assessed on sales.

    `day` is required rather than defaulted to today: the Section 31 rate has
    moved twice inside fiscal 2026 alone, and a default would quietly price a
    2025 backtest at the current rate.
    """
    notional = price * abs(quantity)
    if side is not Side.SELL:
        return Fee(notional=notional, sec_fee=Decimal("0"), taf=Decimal("0"))

    sec_fee = notional * sec_rate(day)
    taf = min(abs(quantity) * TAF_PER_SHARE, TAF_CAP)
    return Fee(notional=notional, sec_fee=sec_fee, taf=taf)


def round_trip_rate(*, price: Decimal, quantity: Decimal, day: date) -> Decimal:
    """All-in cost of a complete round trip, as a share of notional.

    Size-dependent, unlike the Delta equivalent: the TAF is per share and
    capped, so the rate falls as size rises rather than staying flat. On a
    $100,000 position in a $500 stock at the fiscal-2026 rate it is about
    **0.002%** — a fiftieth of Delta's 0.118%, and the reason a signal that
    cannot pay for itself in crypto may still be worth measuring here.
    """
    notional = price * abs(quantity)
    if notional <= 0:
        return Decimal("0")
    buy = equity_fee(price=price, quantity=quantity, side=Side.BUY, day=day)
    sell = equity_fee(price=price, quantity=quantity, side=Side.SELL, day=day)
    return (buy.total + sell.total) / notional
