"""Delta Exchange India fees, for crypto derivatives.

Crypto has run **gross of costs** in this repository since it landed (S-028),
because no cost model covered it and inventing a fee schedule produces a
confidently wrong number rather than an obviously missing one. This closes that
gap for one venue, from its published schedule.

### Sourced, not assumed

Fetched 2026-08-22 from two Delta Exchange pages that agree on futures:

- https://www.delta.exchange/fees
- https://www.delta.exchange/support/solutions/articles/80001177864-fees-on-options-and-futures-trading

| | rate |
|---|---|
| Futures / perpetuals, maker | 0.02% of notional |
| Futures / perpetuals, taker | 0.05% of notional |
| GST | 18% **on the fee**, not on the notional |
| Spot, buy | 0% |
| Spot, sell | 0.1% |
| Settlement | the taker rate, on contracts open at settlement |

**Options are deliberately not modelled.** The two pages disagree — the fee
page says 0.03% with a cap written as "10% 3.5% of Option Premium", evidently
stale text, while the support article says 0.010% of notional capped at 3.5% of
premium. Modelling a number two official pages contradict each other on would
be worse than declining to.

### What is not included, and why that matters more than what is

India taxes virtual digital assets at 30% on gains with a 1% TDS under section
194S. **Neither is modelled here.** Tax is not a transaction cost — it applies
to realised gains at assessment, not per trade, and modelling it inside a
backtest would confuse a levy on outcome with a cost of execution. Whether 194S
TDS reaches derivatives at all is a regulatory question this module does not
answer and must not appear to.

Funding on perpetuals is also absent. It is paid every eight hours by whichever
side is long or short at the mark, and an intraday strategy flat by the close
may pay none of it — but one that straddles a funding stamp pays all of it. See
A-0xx in ASSUMPTIONS.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from eulerlab.costs.schedule import Side

MAKER_RATE = Decimal("0.0002")
"""0.02% of notional. Published 2026-08-22."""

TAKER_RATE = Decimal("0.0005")
"""0.05% of notional. Published 2026-08-22."""

SPOT_BUY_RATE = Decimal("0")
SPOT_SELL_RATE = Decimal("0.001")

GST_RATE = Decimal("0.18")
"""18%, applied to the fee rather than to the notional.

The distinction is the whole difference between 0.059% and 18.05%, and getting
it the wrong way round would not look obviously wrong on a single trade.
"""


@dataclass(frozen=True)
class Fee:
    """One side of one trade, itemised.

    Itemised rather than a single number because the GST is a separate line on
    a real contract note, and a backtest that cannot reproduce the breakdown
    cannot be reconciled against one.
    """

    notional: Decimal
    trading_fee: Decimal
    gst: Decimal

    @property
    def total(self) -> Decimal:
        return self.trading_fee + self.gst

    @property
    def effective_rate(self) -> Decimal:
        """All-in cost as a share of notional. 0.059% for a futures taker."""
        return self.total / self.notional if self.notional else Decimal(0)


def futures_fee(*, price: Decimal, quantity: Decimal, maker: bool = False) -> Fee:
    """Cost of one futures or perpetual leg.

    `maker` defaults to False because a backtest that assumes it earns the
    maker rate is assuming its limit orders were never crossed — a claim about
    queue position that this repository's engines cannot support. Taker is the
    honest default; maker has to be argued for.
    """
    notional = price * quantity
    rate = MAKER_RATE if maker else TAKER_RATE
    trading_fee = notional * rate
    return Fee(notional=notional, trading_fee=trading_fee, gst=trading_fee * GST_RATE)


def spot_fee(*, price: Decimal, quantity: Decimal, side: Side) -> Fee:
    """Cost of one spot leg. Buying is free; selling is not."""
    notional = price * quantity
    rate = SPOT_SELL_RATE if side is Side.SELL else SPOT_BUY_RATE
    trading_fee = notional * rate
    return Fee(notional=notional, trading_fee=trading_fee, gst=trading_fee * GST_RATE)


def round_trip_rate(*, maker_in: bool = False, maker_out: bool = False) -> Decimal:
    """All-in cost of a complete futures round trip, as a share of notional.

    Taker in and taker out is **0.118%** — the number an intraday strategy
    actually has to clear, and it is charged whether the trade wins or loses.
    For scale: Mesfin's MNQ study found no intraday signal family whose gross
    edge exceeded its 2-point friction, and 0.118% of a $60,000 BTC position is
    $71 a round trip.
    """
    entry = (MAKER_RATE if maker_in else TAKER_RATE) * (Decimal(1) + GST_RATE)
    exit_ = (MAKER_RATE if maker_out else TAKER_RATE) * (Decimal(1) + GST_RATE)
    return entry + exit_
