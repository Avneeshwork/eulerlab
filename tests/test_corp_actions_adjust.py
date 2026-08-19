"""The adjustment factor engine: back-adjustment math, and the firewall that
must not let an action leak into a date before it happened.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from eulerlab.bitemporal.provenance import session_close
from eulerlab.corp_actions.adjust import (
    adjusted_price,
    build_price_factor_store,
    build_total_return_factor_store,
    factor_as_of,
)
from eulerlab.corp_actions.parse import CorporateAction, Kind, ParsedComponent

IST = ZoneInfo("Asia/Kolkata")
ISIN = "INE000A01001"

FAR_FUTURE = datetime(2030, 1, 1, tzinfo=IST)


def _bonus(isin: str, ex_date: date, new: int, held: int) -> CorporateAction:
    return CorporateAction(
        isin=isin,
        symbol="X",
        ex_date=ex_date,
        components=(ParsedComponent(Kind.BONUS, "Bonus", ratio_new=new, ratio_held=held),),
        raw_subject=f"Bonus {new}:{held}",
    )


def _split(isin: str, ex_date: date, from_fv: float, to_fv: float) -> CorporateAction:
    return CorporateAction(
        isin=isin,
        symbol="X",
        ex_date=ex_date,
        components=(
            ParsedComponent(Kind.SPLIT, "Split", face_value_from=from_fv, face_value_to=to_fv),
        ),
        raw_subject="Face Value Split",
    )


def _dividend(isin: str, ex_date: date, amount: float) -> CorporateAction:
    return CorporateAction(
        isin=isin,
        symbol="X",
        ex_date=ex_date,
        components=(ParsedComponent(Kind.DIVIDEND, "Dividend", dividend_amount=amount),),
        raw_subject=f"Dividend Rs {amount}",
    )


# --- bonus/split factor math ---


def test_a_1_1_bonus_doubles_the_adjustment_factor_before_it() -> None:
    store = build_price_factor_store([_bonus(ISIN, date(2020, 6, 1), 1, 1)])
    factor = factor_as_of(store, as_of=FAR_FUTURE, isin=ISIN, price_date=date(2020, 5, 1))
    assert factor == 2.0


def test_a_10_to_2_face_value_split_multiplies_by_5() -> None:
    store = build_price_factor_store([_split(ISIN, date(2021, 3, 1), 10.0, 2.0)])
    factor = factor_as_of(store, as_of=FAR_FUTURE, isin=ISIN, price_date=date(2021, 1, 1))
    assert factor == 5.0


def test_adjusted_price_is_the_raw_price_divided_by_the_factor() -> None:
    store = build_price_factor_store([_bonus(ISIN, date(2020, 6, 1), 1, 1)])
    price = adjusted_price(200.0, store, as_of=FAR_FUTURE, isin=ISIN, price_date=date(2020, 5, 1))
    assert price == 100.0


def test_a_price_on_the_action_own_ex_date_is_not_adjusted_by_itself() -> None:
    """The ex-date's own price is already post-action; it must not divide
    itself, or every ex-date price would be halved twice over."""
    store = build_price_factor_store([_bonus(ISIN, date(2020, 6, 1), 1, 1)])
    factor = factor_as_of(store, as_of=FAR_FUTURE, isin=ISIN, price_date=date(2020, 6, 1))
    assert factor == 1.0


def test_a_price_after_the_action_is_unaffected() -> None:
    store = build_price_factor_store([_bonus(ISIN, date(2020, 6, 1), 1, 1)])
    factor = factor_as_of(store, as_of=FAR_FUTURE, isin=ISIN, price_date=date(2020, 7, 1))
    assert factor == 1.0


def test_two_actions_compound_multiplicatively() -> None:
    """A 1:1 bonus then later a 10-to-2 split: a price before both carries
    both factors, 2 * 5 = 10."""
    actions = [_bonus(ISIN, date(2020, 6, 1), 1, 1), _split(ISIN, date(2021, 3, 1), 10.0, 2.0)]
    store = build_price_factor_store(actions)
    factor = factor_as_of(store, as_of=FAR_FUTURE, isin=ISIN, price_date=date(2020, 1, 1))
    assert factor == 10.0


def test_a_price_between_two_actions_carries_only_the_later_one() -> None:
    actions = [_bonus(ISIN, date(2020, 6, 1), 1, 1), _split(ISIN, date(2021, 3, 1), 10.0, 2.0)]
    store = build_price_factor_store(actions)
    factor = factor_as_of(store, as_of=FAR_FUTURE, isin=ISIN, price_date=date(2020, 9, 1))
    assert factor == 5.0


def test_a_different_isin_is_unaffected() -> None:
    store = build_price_factor_store([_bonus(ISIN, date(2020, 6, 1), 1, 1)])
    factor = factor_as_of(store, as_of=FAR_FUTURE, isin="INE999Z99999", price_date=date(2020, 1, 1))
    assert factor == 1.0


def test_a_demerger_component_contributes_no_price_factor() -> None:
    """Demerger ratios come from Sprint 3's succession model, never this
    engine - see the module docstring."""
    action = CorporateAction(
        isin=ISIN,
        symbol="X",
        ex_date=date(2020, 6, 1),
        components=(ParsedComponent(Kind.DEMERGER, "Demerger"),),
        raw_subject="Demerger",
    )
    store = build_price_factor_store([action])
    assert len(store) == 0


# --- the firewall: the whole point of Sprint 4 wired into Sprint 5 ---


def test_a_bonus_not_yet_knowable_at_as_of_does_not_adjust_the_price() -> None:
    """The headline guarantee. Querying the day before an action's own ex-date
    must see no effect from it at all."""
    action = _bonus(ISIN, date(2020, 6, 1), 1, 1)
    store = build_price_factor_store([action])
    as_of = session_close("2020-05-31")
    factor = factor_as_of(store, as_of=as_of, isin=ISIN, price_date=date(2020, 1, 1))
    assert factor == 1.0


def test_the_bonus_becomes_knowable_exactly_on_its_own_ex_date() -> None:
    action = _bonus(ISIN, date(2020, 6, 1), 1, 1)
    store = build_price_factor_store([action])
    as_of = session_close("2020-06-01")
    factor = factor_as_of(store, as_of=as_of, isin=ISIN, price_date=date(2020, 1, 1))
    assert factor == 2.0


def test_as_of_is_required_and_keyword_only() -> None:
    store = build_price_factor_store([_bonus(ISIN, date(2020, 6, 1), 1, 1)])
    with pytest.raises(TypeError):
        factor_as_of(store, FAR_FUTURE, isin=ISIN, price_date=date(2020, 1, 1))  # type: ignore[call-arg]


# --- total return: dividends need a close-price lookup ---


def test_a_dividend_reduces_the_pre_ex_date_price_via_reinvestment_factor() -> None:
    """Rs 5 dividend on a stock whose prior close was Rs 100: the TR factor
    is 1/(1-5/100) = 1/0.95, so a pre-ex-date price of 100 becomes ~105.26
    in TR-adjusted terms - the reinvested cash is folded back in."""
    action = _dividend(ISIN, date(2020, 6, 1), 5.0)

    def lookup(isin: str, d: date) -> float | None:
        return 100.0 if isin == ISIN and d == date(2020, 6, 1) else None

    store = build_total_return_factor_store([action], lookup)
    factor = factor_as_of(store, as_of=FAR_FUTURE, isin=ISIN, price_date=date(2020, 1, 1))
    assert factor == pytest.approx(1.0 / 0.95)


def test_a_dividend_with_no_lookup_result_contributes_nothing() -> None:
    """Missing close data must not be guessed - the dividend is silently
    absent from the factor rather than inventing a base price."""
    action = _dividend(ISIN, date(2020, 6, 1), 5.0)
    store = build_total_return_factor_store([action], lambda isin, d: None)
    assert len(store) == 0


def test_a_dividend_larger_than_the_close_is_rejected_not_inverted() -> None:
    """A dividend >= the prior close would make the factor negative or
    divide-by-zero - nonsense that should be dropped, not silently produced."""
    action = _dividend(ISIN, date(2020, 6, 1), 150.0)
    store = build_total_return_factor_store([action], lambda isin, d: 100.0)
    assert len(store) == 0


def test_total_return_includes_bonus_and_dividend_together() -> None:
    actions = [_bonus(ISIN, date(2020, 6, 1), 1, 1), _dividend(ISIN, date(2020, 9, 1), 5.0)]
    store = build_total_return_factor_store(actions, lambda isin, d: 100.0)
    factor = factor_as_of(store, as_of=FAR_FUTURE, isin=ISIN, price_date=date(2020, 1, 1))
    assert factor == pytest.approx(2.0 * (1.0 / 0.95))
