"""Point-in-time corporate-action adjustment, and the bug that had none.

The original panel tried to bake adjustment in at write time, calling
`factor_as_of(as_of=<the row's own day>, price_date=<the same day>)`. Those
conditions are mutually exclusive — a factor exists only for actions knowable
by `as_of` and applies only to prices dated *before* the action — so the
divisor was always 1.0. The panel was raw while claiming to be adjusted, and
nothing failed.

These tests pin both halves: that the adjustment now actually happens, and
that it is *point in time* rather than using future knowledge.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from eulerlab.bitemporal.store import BitemporalStore, Record
from eulerlab.corp_actions.adjust import factor_as_of
from eulerlab.features.panel import PanelRow, UnadjustablePanel, assert_adjustable

IST = ZoneInfo("Asia/Kolkata")


def _store(ex_date: date, factor: float, key: str = "INE000A010") -> BitemporalStore:
    store = BitemporalStore()
    when = datetime.combine(ex_date, datetime.min.time(), tzinfo=IST).replace(hour=15, minute=30)
    store.append(Record(when, when, key, factor))
    return store


# --- the bug, pinned so it cannot come back ---


def test_the_old_same_day_call_can_never_apply_a_factor() -> None:
    """Reproduces the original defect exactly. `as_of` and `price_date` set to
    the same day means the action must be both knowable by then and after
    then, which nothing satisfies."""
    store = _store(date(2018, 5, 31), 2.0)
    for day in (date(2018, 1, 15), date(2018, 5, 31), date(2019, 1, 15)):
        as_of = datetime.combine(day, datetime.max.time(), tzinfo=IST)
        assert factor_as_of(store, as_of=as_of, isin="INE000A010", price_date=day) == 1.0


def test_a_prior_price_is_adjusted_when_seen_from_after_the_action() -> None:
    """The behaviour that was missing: standing after the bonus, January's
    price must be halved to be comparable."""
    store = _store(date(2018, 5, 31), 2.0)
    as_of = datetime(2018, 8, 1, tzinfo=IST)
    assert factor_as_of(store, as_of=as_of, isin="INE000A010", price_date=date(2018, 1, 15)) == 2.0


# --- point in time: no peeking at future actions ---


def test_a_strategy_before_the_ex_date_does_not_see_the_adjustment() -> None:
    """The reason adjustment cannot be baked into a static panel. A decision
    on 15 January must not be made on prices adjusted for a bonus that goes ex
    in May — that is knowledge of the future."""
    store = _store(date(2018, 5, 31), 2.0)
    as_of = datetime(2018, 1, 15, 23, 59, tzinfo=IST)
    assert factor_as_of(store, as_of=as_of, isin="INE000A010", price_date=date(2017, 6, 1)) == 1.0


def test_the_same_price_adjusts_differently_depending_on_when_you_stand() -> None:
    """Which is exactly why one static number per row cannot be correct."""
    store = _store(date(2018, 5, 31), 2.0)
    price_date = date(2018, 1, 15)
    before = factor_as_of(
        store, as_of=datetime(2018, 2, 1, tzinfo=IST), isin="INE000A010", price_date=price_date
    )
    after = factor_as_of(
        store, as_of=datetime(2018, 8, 1, tzinfo=IST), isin="INE000A010", price_date=price_date
    )
    assert before == 1.0
    assert after == 2.0


def test_two_actions_compound_when_both_are_knowable() -> None:
    store = _store(date(2018, 5, 31), 2.0)
    when = datetime(2019, 3, 1, 15, 30, tzinfo=IST)
    store.append(Record(when, when, "INE000A010", 5.0))
    assert factor_as_of(
        store,
        as_of=datetime(2020, 1, 1, tzinfo=IST),
        isin="INE000A010",
        price_date=date(2018, 1, 1),
    ) == pytest.approx(10.0)


# --- the guard against a silent no-op ---


def _rows(isin: str) -> list[PanelRow]:
    return [
        PanelRow(
            day=date(2024, 1, 1) + timedelta(days=i),
            symbol="ACME",
            close=100.0,
            volume=1.0,
            turnover=1.0,
            isin=isin,
        )
        for i in range(10)
    ]


def test_a_panel_without_an_instrument_key_is_refused() -> None:
    """Silently skipping adjustment is how the original bug survived. A panel
    that cannot be adjusted must say so rather than quietly return raw prices."""
    with pytest.raises(UnadjustablePanel, match="no instrument key"):
        assert_adjustable(_rows(""))


def test_a_panel_with_keys_is_accepted() -> None:
    assert_adjustable(_rows("INE000A010"))  # must not raise


def test_an_empty_panel_is_not_an_error() -> None:
    """Nothing to adjust is different from unable to adjust."""
    assert_adjustable([])  # must not raise
