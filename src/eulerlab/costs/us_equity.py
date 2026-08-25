"""US equity execution costs, as an Indian investor actually pays them.

Written because a `us` sweep otherwise fell through to `Segment.EQUITY_INTRADAY`
and was charged **STT, SEBI turnover fees, stamp duty and GST on brokerage** —
an Indian bill for a trade on Nasdaq. That is the same mistake the Delta module
was written to fix, arriving from the other direction, and it flatters or
punishes at roughly ten basis points a round trip depending on nothing real.

### Sourced, not assumed

Alpaca charges **no commission** on US equities. What remains are the two
regulatory pass-throughs every US broker collects on the **sell side only**:

| | rate | charged? | source |
|---|---|---|---|
| **INDmoney brokerage** | **0.25% per leg, capped at $25 per transaction** | **yes** | operator, from INDmoney's schedule |
| **GST on brokerage** | **18% of the brokerage** | **yes** | the cap is quoted excluding GST |
| SEC Section 31 fee | $20.60 per million of sales | no | FINRA Information Notice 03/17/26 |
| FINRA Trading Activity Fee | $0.000166 per share sold, capped $8.30 | no | FINRA TAF guidance |

### Only the brokerage is charged

Brokerage is the cost model here, by the operator's decision, and the two
regulatory pass-throughs are kept for reference rather than added.

The decision costs almost nothing in accuracy, which is why it is a reasonable
one: on a $100,000 round trip the SEC and FINRA fees come to about **$2.09**
against **$500** of brokerage — six tenths of one percent of the bill. A model
that is 0.6% light on a figure that decides results by a factor of three is
light in a place that does not matter.

The constants and their sources stay in this module because they were verified
against the regulator and because the rate schedule is the kind of fact that is
expensive to re-derive. `sec_rate()` still works and is still tested; nothing
calls it from the fee path.

### The cap is the whole story, and it took two corrections to get right

Alpaca is the **data** source here; it is not who this account trades through.
The trades are placed through INDmoney.

The rate is 0.25% a leg — but capped at **$25 per transaction**, and the cap is
what binds at any size this engine trades. A typical position here is around
$500,000 of notional: 0.25% of that is $1,250, and the cap cuts it to $25. A
**fiftyfold** reduction, on every leg.

The effect on the arithmetic is total. Uncapped, a round trip costs 0.5% of
notional and no intraday signal in this library survives it — the friction on
`orb_breakout` came to 309% of its gross edge. Capped, the same round trip
costs $50 on $500,000, which is **0.02%** — a sixth of Delta Exchange's 0.118%
and genuinely cheap.

So the cap is not a detail of the fee schedule. It is the difference between
"US intraday cannot work" and "US intraday is the cheapest venue we have", and
this module has now stated both, in that order, before being told the cap
existed. A fee model without its cap is not a conservative fee model; it is a
wrong one, and it was wrong by a factor of fifty.

GST at 18% applies on top of the brokerage, because the cap is quoted excluding
it — the same treatment `delta_exchange.py` gives the same tax.

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

### Currency conversion is a cost on capital, not on trades

INDmoney quotes 0.5%-1.2% for INR→USD conversion, charged by the remitting
bank rather than by the platform. It is **not** modelled per trade, and that is
a modelling decision rather than an omission.

Conversion is paid when money crosses the border, not when a position is
opened. A strategy that funds an account once and then trades it a hundred
times pays the markup twice — in and out — not two hundred times. Charging it
per fill would inflate an active strategy's costs by the number of trades it
makes, which would punish turnover for a reason that has nothing to do with
turnover.

The honest consequence: a result from this module is net of broker and
regulatory charges but gross of the round-trip currency conversion, which on a
₹10 lakh account is roughly ₹5,000-12,000 each way regardless of how the
strategy performs. See A-035.

### Two brokers, and the choice is worth a real amount

`BROKER` selects the schedule. Both are modelled from the broker's own pricing
page, and they are genuinely different animals:

- **INDmoney** — 0.25% a leg capped at $25, plus 18% GST. Flat $29.50 a leg at
  any size above $10,000 of notional. Indian platform, INR funding, LRS route.
- **Firstrade** — **$0 commission** online for stocks and ETFs. Pays only the
  SEC Section 31 fee and the FINRA TAF, both sell-side. About **$2.09** on a
  $100,000 sell and **nothing at all** on a buy.

At the size this engine trades that is roughly $59 a round trip against $2, so
Firstrade is about **thirty times cheaper**. Whether that matters depends
entirely on how much friction the strategy was carrying to begin with — for
these signals it is worth a few percent of gross, not the difference between
working and not. The uncapped 0.25% *was* that difference; the choice between
two cheap brokers is not.

What this module does not model, and what should decide the question in
practice: Firstrade is a US broker, so the account is held abroad and the
funding, tax reporting and LRS paperwork differ from INDmoney's. Those are real
costs in time and risk, and none of them is a per-trade fee.

### TCS is not a cost

20% TCS applies to LRS remittances above ₹10 lakh in a financial year. It is
**creditable against income tax** when the return is filed, so it blocks
capital rather than consuming it. Modelling it as a transaction cost would
confuse a timing effect on cash with a charge on trading — the same reasoning
that keeps India's VDA tax out of the Delta model (A-027).

### What is deliberately absent

**Spread and slippage.** Fills here come from minute bars, and a bar's high and
low are not a book — modelling half a spread on top would put a made-up number
beside a measured one and make the total look more precise than its worst
component. The NSE and Delta models make the same omission, so the three remain
comparable to each other. At 0.25% a leg the broker charge dwarfs a realistic
spread anyway.

**Borrow on shorts, and payment for order flow.** The first applies to
positions this engine does not hold overnight; the second is a rebate the
broker receives, not a cost the trader pays.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

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

BROKERAGE_RATE = Decimal("0.0025")
"""INDmoney: 0.25% of trade value, each leg, before the cap below."""

BROKERAGE_CAP = Decimal("25")
"""$25 per transaction, quoted excluding GST.

The binding constraint at every size this engine trades, and the single number
that decides whether US intraday works here at all. On a $500,000 position it
turns $1,250 of brokerage into $25."""

GST_RATE = Decimal("0.18")
"""18% on the brokerage, since the cap is quoted before it. Same treatment as
`delta_exchange.py` gives the same tax."""


class Broker(StrEnum):
    """Who the trade is placed through. Changes the fee, not the fill."""

    INDMONEY = "indmoney"
    FIRSTRADE = "firstrade"


BROKER = Broker(os.environ.get("EULERLAB_US_BROKER", Broker.INDMONEY.value))
"""The broker every US cost is charged at, from `EULERLAB_US_BROKER`.

Defaults to INDmoney because that is the account that exists. Set to
`firstrade` to price the same strategies on zero commission — the comparison is
a one-line change rather than a fork of the cost model, so a result can always
be re-read against the other schedule."""

FX_MARKUP_RANGE = (Decimal("0.005"), Decimal("0.012"))
"""INR->USD conversion, 0.5%-1.2%, charged by the remitting bank.

Recorded here so the number is not lost, and deliberately **not** applied per
trade — it is a cost on moving capital across the border, not on trading. See
the module docstring."""


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
    brokerage: Decimal = Decimal("0")
    gst: Decimal = Decimal("0")

    @property
    def capped(self) -> bool:
        """Whether the $25 cap bound on this leg.

        Worth asking of any given trade: below about $10,000 of notional the
        percentage applies and the cost scales, above it the cost is flat. Two
        strategies with the same edge and different position sizes are charged
        very differently, and nothing else in the fee makes that visible."""
        return self.brokerage >= BROKERAGE_CAP

    @property
    def total(self) -> Decimal:
        return self.sec_fee + self.taf + self.brokerage + self.gst


def equity_fee(
    *,
    price: Decimal,
    quantity: Decimal,
    side: Side,
    day: date,
    broker: Broker | None = None,
) -> Fee:
    """Cost of one US equity leg on a given date.

    On INDmoney both legs pay the same capped 0.25%. On Firstrade a buy is free
    and a sell pays only the two regulatory pass-throughs, which are sell-side
    by construction.
    """
    # Brokerage on both legs, and nothing else. The SEC and FINRA fees are
    # modelled in this file and deliberately not added — see the docstring.
    # `day` is still required so the signature does not have to change if they
    # are ever switched back on, and so a caller cannot forget which year a
    # trade happened in.
    notional = price * abs(quantity)

    if (broker or BROKER) is Broker.FIRSTRADE:
        # Zero commission online. What remains are the two sell-side
        # pass-throughs every US broker collects, so a buy is genuinely free.
        if side is not Side.SELL:
            return Fee(notional=notional, sec_fee=Decimal("0"), taf=Decimal("0"))
        return Fee(
            notional=notional,
            sec_fee=notional * sec_rate(day),
            taf=min(abs(quantity) * TAF_PER_SHARE, TAF_CAP),
        )

    brokerage = min(notional * BROKERAGE_RATE, BROKERAGE_CAP)
    return Fee(
        notional=notional,
        sec_fee=Decimal("0"),
        taf=Decimal("0"),
        brokerage=brokerage,
        gst=brokerage * GST_RATE,
    )


def round_trip_rate(
    *, price: Decimal, quantity: Decimal, day: date, broker: Broker | None = None
) -> Decimal:
    """All-in cost of a complete round trip, as a share of notional.

    **Size-dependent, and that is the point.** Below roughly $10,000 of notional
    the 0.25% applies and a round trip costs 0.59% including GST. Above it the
    $25 cap binds and the rate falls with size: on a $500,000 position a round
    trip is $59, or **0.012%** — a tenth of Delta Exchange's 0.118%.

    A strategy trading large positions is charged almost nothing here. One
    trading small positions is charged more than it would pay on crypto. No
    single number describes this venue.

    An earlier version of this docstring said 0.002% and called US the cheap
    venue. That was the cost of *clearing* a US trade, not of placing one
    through the broker this account actually uses.
    """
    notional = price * abs(quantity)
    if notional <= 0:
        return Decimal("0")
    buy = equity_fee(price=price, quantity=quantity, side=Side.BUY, day=day, broker=broker)
    sell = equity_fee(price=price, quantity=quantity, side=Side.SELL, day=day, broker=broker)
    return (buy.total + sell.total) / notional
