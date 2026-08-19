"""Adjustment factors: making a raw price series comparable across a split,
bonus or dividend, without ever leaking one into a date before it happened.

A raw price series has real discontinuities in it that are not returns. A
1:1 bonus halves the price overnight; a stock that goes ex-dividend drops by
roughly the dividend amount. Neither is a loss to whoever held the position.
The adjustment factor removes the discontinuity so the series reads as a
continuous record of what an investor experienced.

**The mechanism is back-adjustment**: prices *before* an action are divided
by that action's multiplier, so the whole pre-action history is rescaled into
post-action units. This is standard practice (it is what "adjusted close"
means in any equity dataset) and it is not itself a lookahead risk — dividing
old prices by a later-known factor does not tell a backtest an action is
coming, it only makes today's price comparable to yesterday's.

**Two series, kept separate, never merged**:

- *Price-adjusted* — share-count changes only: bonuses, splits, and rights.
  Answers "what would this instrument's price series look like if the share
  count had never changed?"
- *Total-return* — price-adjusted, plus dividends reinvested at the close
  before the ex-date. Answers "what return did a holder actually earn?"

Bonus and split are pure ratio arithmetic. Rights are not: a rights issue is
a *purchase* at a set price, so the dilution depends how far below market that
price sits, and computing it needs the cum-date close. That is why the
price-adjusted builder takes an optional close-price lookup — without one it
still produces bonuses and splits, and simply has no rights in it.

Conflating them is the classic mistake: a price-adjusted-only series
understates return by omitting dividends, and a naive total-return
calculation that ignores splits produces nonsense jumps. `CLAUDE.md`'s
`Strategy` interface is meant to see one or the other explicitly, never a
blend.

**Every factor is built through `eulerlab.bitemporal.store`**, Sprint 4's
firewall, so `factor_as_of` cannot return a factor that includes an action not
yet knowable at `as_of`. See ADR-016 for why `knowledge_time` is
conservatively each action's own ex-date: the feed carries no announcement
date (`caBroadcastDate` was null on all 25,644 rows probed), so nothing
earlier can honestly be claimed.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, datetime

from eulerlab.bitemporal.provenance import session_close
from eulerlab.bitemporal.store import BitemporalStore, Record
from eulerlab.corp_actions.parse import CorporateAction, Kind

ClosePriceLookup = Callable[[str, date], float | None]
"""isin, trade_date -> the previous close on that date, or None if unknown."""


def _action_event_time(action: CorporateAction) -> datetime:
    return session_close(action.ex_date.isoformat())


def _fold(
    action: CorporateAction,
    *,
    close_price_lookup: ClosePriceLookup | None,
    include_dividends: bool,
) -> float | None:
    """Combine one action's components into a single multiplier, or None.

    One row can bundle several actions on the same ex-date ("Bonus 1:1 / Face
    Value Split ..."), so the components multiply together. Returns None when
    nothing in the row produced a usable factor, so the caller can skip it
    rather than store a meaningless 1.0.
    """
    multiplier = 1.0
    found = False

    # The cum price is shared by rights and dividends and costs a lookup, so
    # it is fetched at most once per action rather than once per component.
    cum_price: float | None = None
    looked_up = False

    def cum() -> float | None:
        nonlocal cum_price, looked_up
        if not looked_up:
            looked_up = True
            cum_price = (
                close_price_lookup(action.isin, action.ex_date) if close_price_lookup else None
            )
        return cum_price

    for component in action.components:
        if component.kind in (Kind.BONUS, Kind.SPLIT):
            m = component.bonus_split_multiplier
            if m is not None:
                multiplier *= m
                found = True

        elif component.kind is Kind.RIGHTS and close_price_lookup is not None:
            price = cum()
            if price is not None:
                m = component.rights_multiplier(cum_price=price, face_value=action.face_value)
                if m is not None:
                    multiplier *= m
                    found = True

        elif include_dividends and component.kind is Kind.DIVIDEND:
            amount = component.dividend_amount
            price = cum()
            if amount is not None and price is not None and price > amount:
                multiplier *= 1.0 / (1.0 - amount / price)
                found = True

    return multiplier if found else None


def build_price_factor_store(
    actions: Sequence[CorporateAction], close_price_lookup: ClosePriceLookup | None = None
) -> BitemporalStore:
    """Bonuses, splits, and — when a close-price lookup is supplied — rights.

    Bonus and split need no market data at all, just ratio arithmetic, so the
    lookup is optional and this store can be built cheaply without touching
    price history. A rights issue is different: it is a *purchase* at a set
    price, so its dilution depends how far below market that price sits, and
    it cannot be computed from the ratio alone (research note 010). Omitting
    the lookup silently omits rights, which is why it is an explicit argument
    rather than a hidden default.
    """
    store = BitemporalStore()
    for action in actions:
        multiplier = _fold(action, close_price_lookup=close_price_lookup, include_dividends=False)
        if multiplier is not None:
            when = _action_event_time(action)
            store.append(Record(when, when, action.isin, multiplier))
    return store


def build_total_return_factor_store(
    actions: Sequence[CorporateAction], close_price_lookup: ClosePriceLookup
) -> BitemporalStore:
    """Everything in the price factor, plus dividends reinvested at the close
    before the ex-date.

    A dividend's multiplier is `1 / (1 - dividend / prev_close)`: back-adjusted
    prices before the ex-date are divided by it, which is the same as scaling
    them down by the fraction of value that left as cash — exactly what
    reinvesting it at the close would have captured.

    A dividend whose `prev_close` cannot be looked up (missing bhavcopy row,
    delisted by then, or the amount itself failed to parse) contributes
    nothing rather than guessing — an omitted dividend understates return by a
    few percent at most; a guessed `prev_close` could invert the sign of a
    return around that date.
    """
    store = BitemporalStore()
    for action in actions:
        multiplier = _fold(action, close_price_lookup=close_price_lookup, include_dividends=True)
        if multiplier is not None:
            when = _action_event_time(action)
            store.append(Record(when, when, action.isin, multiplier))
    return store


def factor_as_of(store: BitemporalStore, *, as_of: datetime, isin: str, price_date: date) -> float:
    """The cumulative multiplier to divide a raw price at `price_date` by.

    `as_of` is required and keyword-only, matching Sprint 4's read API — a
    factor computed without it would be exactly the same class of bug the
    bitemporal store exists to prevent, just one layer up.

    Only actions whose event_time is *after* `price_date` apply: an action's
    own ex-date price is already the post-action price, so it divides
    everything strictly before it, never itself.
    """
    price_dt = session_close(price_date.isoformat())
    factor = 1.0
    for record in store.query(as_of=as_of, key=isin):
        if record.event_time > price_dt:
            factor *= record.value
    return factor


def adjusted_price(
    raw_price: float, store: BitemporalStore, *, as_of: datetime, isin: str, price_date: date
) -> float:
    """`raw_price` rescaled into the units implied by every action knowable
    at `as_of` that happened after `price_date`."""
    return raw_price / factor_as_of(store, as_of=as_of, isin=isin, price_date=price_date)
