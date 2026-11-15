"""What one fill costs, on the venue it would actually trade on.

The single answer to that question. There were three, in different files, with
different signatures and different coverage, and the gaps between them have
produced more wrong numbers than anything else in this repository:

- `bracket._cost` knew crypto, US and NSE-intraday.
- `vector._costs_for` knew US and NSE-**delivery**, and had no crypto branch.
- `server.COSTED_CLASSES` decided separately whether to charge at all.

Each was reasonable where it was written. Together they meant a venue could be
handled in one engine and silently mishandled in the other, and the resulting
figure was always plausible — an Indian bill on a US trade is about ten basis
points, which looks like a cost rather than like a bug.

### Why the asset class is required and untyped defaults are not allowed

`asset_class` defaulted to `"equity"` in both engines. That default billed
crypto Indian STT, then US Indian STT, then — after both were fixed at the leaf
— every *winning* exit Indian STT, because two of six call sites had quietly
kept it. Then a fix that added US routing to the daily engine did nothing at
all, because none of the three callers passed the argument through.

So there is no default here, and `UNCOSTED` is spelled out rather than implied:
a class this router does not know raises instead of guessing, and a class that
is deliberately gross-of-costs says so by name.

### What each venue pays

| class | charge | source |
|---|---|---|
| `equity` | STT, SEBI turnover, stamp duty, GST, Zerodha brokerage capped at ₹20 | `costs/model.py` |
| `us` | INDmoney 0.25% a leg capped at $25, plus 18% GST | `costs/us_equity.py` |
| `crypto` | Delta 0.05% taker plus 18% GST | `costs/delta_exchange.py` |
| `fx` | the measured bid-ask spread, carried per bar | `features/alt_panel.py` |
| `mutual_fund` | nothing modelled — gross, and labelled so | — |

Spread and slippage are absent from all of them, which makes every net figure
better than a real fill would be. That is consistent across venues, so they stay
comparable to each other, and it is recorded in A-030.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date
from decimal import Decimal
from enum import StrEnum

from eulerlab.costs.schedule import Segment, Side


class Venue(StrEnum):
    """Where a trade is charged. The asset class, named as what it decides."""

    NSE = "equity"
    US = "us"
    CRYPTO = "crypto"
    FX = "fx"
    MUTUAL_FUND = "mutual_fund"


UNCOSTED: frozenset[Venue] = frozenset({Venue.MUTUAL_FUND})
"""Venues deliberately run gross of costs.

Named rather than falling out of a missing branch. `costs/schedule.py` covers
Indian exchange-traded segments only, and running a fund redemption through
`EQUITY_DELIVERY` would apply STT and stamp duty to something that touches
neither — a confidently wrong number rather than an obviously missing one.

FX is **not** here: its cost is the bid-ask spread, which is measured in the
landed data and charged from what was observed rather than invented."""


class UnknownVenue(LookupError):
    """A class this router has no schedule for.

    Raised rather than defaulted. Every wrong-cost bug in this repository came
    from a default that looked like an answer.
    """


def fill_cost(
    *,
    venue: str,
    price: float,
    quantity: int,
    side: Side,
    day: date,
    segment: Segment,
    fund_unit: bool = False,
) -> float:
    """The charge for one fill. Zero for venues that are deliberately uncosted.

    `segment` applies to NSE only and distinguishes an intraday trade from a
    delivery one — the two pay different STT and the difference is large. It is
    ignored elsewhere, because no other venue here has segments. So is
    `fund_unit`, which marks an NSE ETF unit (a different STT from a share).
    """
    if quantity <= 0:
        return 0.0

    try:
        known = Venue(venue)
    except ValueError as exc:
        msg = f"no cost schedule for asset class {venue!r}"
        raise UnknownVenue(msg) from exc

    if known in UNCOSTED:
        return 0.0

    if known is Venue.CRYPTO:
        from eulerlab.costs.delta_exchange import futures_fee

        fee = futures_fee(price=Decimal(str(price)), quantity=Decimal(str(quantity)))
        return float(fee.total)

    if known is Venue.US:
        from eulerlab.costs.us_equity import equity_fee

        return float(
            equity_fee(
                price=Decimal(str(price)),
                quantity=Decimal(str(quantity)),
                side=side,
                day=day,
            ).total
        )

    if known is Venue.FX:
        # The spread is charged where it is measured — on the `PanelRow` the
        # daily engine already carries — not re-derived from a price here.
        # Returning zero would double-count in the other direction: the engine
        # would charge nothing and the panel would charge nothing twice.
        return 0.0

    from eulerlab.costs.model import cost_of_trade

    charge = float(
        cost_of_trade(
            trade_date=day,
            segment=segment,
            side=side,
            price=Decimal(str(round(price, 2))),
            quantity=quantity,
            fund_unit=fund_unit,
        ).total
    )
    if _DP.get() and segment is Segment.EQUITY_DELIVERY and side is Side.SELL:
        charge += DP_CHARGE_INR
    return charge


# ASSUMPTION: A-156 — Rs 20 + 18% GST per scrip per delivery sell day (Angel One's DP charge).
DP_CHARGE_INR = 23.60
"""The depository charge a broker takes on each delivery sell (HISTORY #94, ADR-203)."""
_DP: ContextVar[bool] = ContextVar("dp_charges", default=False)


@contextmanager
def dp_charges() -> Iterator[None]:
    """Charge `DP_CHARGE_INR` on every NSE delivery sell inside the block (ADR-203).

    Research runs only: the paper and live books do not use it, so their
    replays are unchanged until the cost model adds it for everyone (T-4633).
    A fill split across days pays it once per sell fill, slightly more than a
    broker charging once per scrip per day."""
    token = _DP.set(True)
    try:
        yield
    finally:
        _DP.reset(token)


def is_costed(venue: str) -> bool:
    """Whether a venue's runs are net of costs. Drives the `cost_mode` label."""
    try:
        return Venue(venue) not in UNCOSTED
    except ValueError:
        return False
