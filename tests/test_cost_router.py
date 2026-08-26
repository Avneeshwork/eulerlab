"""One router, because three implementations diverged and the gaps cost money.

`bracket._cost` knew crypto, US and NSE-intraday. `vector._costs_for` knew US
and NSE-*delivery* and had no crypto branch at all. Each was correct where it
was written, and a venue handled in one engine and mishandled in the other
produced a plausible figure either way — an Indian bill on a US trade is about
ten basis points, which reads as a cost rather than as a bug.
"""

from __future__ import annotations

import datetime as dt

import pytest

from eulerlab.backtest import vector
from eulerlab.costs.router import UnknownVenue, Venue, fill_cost, is_costed
from eulerlab.costs.schedule import Side
from eulerlab.intraday import bracket

DAY = dt.date(2026, 6, 15)


def test_every_venue_charges_something_different() -> None:
    """The whole point: the venue decides the bill.

    If two of these ever agree exactly, one of them has stopped routing.
    """
    charges = {
        venue: fill_cost(venue=venue, price=500.0, quantity=200, side=Side.SELL, day=DAY)
        for venue in ("equity", "us", "crypto")
    }
    assert len(set(charges.values())) == 3, charges


def test_an_unknown_venue_refuses_rather_than_guessing() -> None:
    """Every wrong-cost bug here came from a default that looked like an answer."""
    with pytest.raises(UnknownVenue):
        fill_cost(venue="futures", price=100.0, quantity=1, side=Side.BUY, day=DAY)


def test_uncosted_venues_are_named_not_missing() -> None:
    """A gross-of-costs run says so; it does not fall out of an absent branch."""
    assert not is_costed("mutual_fund")
    assert is_costed("equity")
    assert Venue.MUTUAL_FUND in {v for v in Venue if not is_costed(v.value)}
    assert fill_cost(venue="mutual_fund", price=100.0, quantity=10, side=Side.BUY, day=DAY) == 0.0


def test_the_daily_engine_actually_routes() -> None:
    """The regression that made the first US fix worthless.

    A US branch was added to `vector._costs_for` and **never once executed**:
    none of its three callers passed `asset_class`, so every daily run — US
    included — was charged Indian delivery costs while the code above said
    otherwise. The argument is required now, and this checks the routing it
    enables.
    """
    us = vector._costs_for(DAY, 500.0, 200, Side.SELL, None, "us")
    india = vector._costs_for(DAY, 500.0, 200, Side.SELL, None, "equity")
    assert us != india
    assert us == pytest.approx(25 * 1.18)


def test_both_engines_agree_on_a_venue_they_share() -> None:
    """Intraday and daily differ only where they should: the NSE segment.

    US and crypto have no segments, so the two engines must charge them
    identically. NSE legitimately differs — intraday and delivery pay different
    STT — and that difference is the only one allowed.
    """
    for venue in ("us", "crypto"):
        intraday = bracket._cost(500.0, 200, Side.SELL, DAY, venue)
        daily = vector._costs_for(DAY, 500.0, 200, Side.SELL, None, venue)
        assert intraday == pytest.approx(daily), venue

    nse_intraday = bracket._cost(500.0, 200, Side.SELL, DAY, "equity")
    nse_daily = vector._costs_for(DAY, 500.0, 200, Side.SELL, None, "equity")
    assert nse_intraday != nse_daily


def test_zero_quantity_costs_nothing() -> None:
    assert fill_cost(venue="us", price=500.0, quantity=0, side=Side.BUY, day=DAY) == 0.0
