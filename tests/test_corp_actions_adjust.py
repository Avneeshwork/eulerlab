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


# --- rights issues: research note 010, NSE's formula as P/TERP ---


def _rights(
    isin: str, ex_date: date, new: int, held: int, premium: float, face_value: float | None = 10.0
) -> CorporateAction:
    return CorporateAction(
        isin=isin,
        symbol="X",
        ex_date=ex_date,
        components=(
            ParsedComponent(
                Kind.RIGHTS, "Rights", ratio_new=new, ratio_held=held, rights_premium=premium
            ),
        ),
        raw_subject=f"Rights {new}:{held} @ Premium Rs {premium}",
        face_value=face_value,
    )


def test_a_rights_multiplier_matches_the_worked_terp_example() -> None:
    """1:1 at issue price 50 with cum price 100.

    TERP = (1*100 + 1*50)/2 = 75, so the factor is 100/75. NSE would state
    this as 0.75; ours is the reciprocal by convention (note 010).
    """
    component = ParsedComponent(
        Kind.RIGHTS, "Rights", ratio_new=1, ratio_held=1, rights_premium=40.0
    )
    # issue price = face value 10 + premium 40 = 50
    assert component.rights_multiplier(cum_price=100.0, face_value=10.0) == pytest.approx(100 / 75)


def test_the_reliance_2020_rights_issue_price_is_face_value_plus_premium() -> None:
    """Reliance's 2020 issue was 1:15 at Rs 1,257; the feed says faceVal 10,
    premium 1247. Validating the rule the multiplier depends on."""
    component = ParsedComponent(
        Kind.RIGHTS, "Rights", ratio_new=1, ratio_held=15, rights_premium=1247.0
    )
    cum = 1500.0
    terp = (15 * cum + 1 * 1257.0) / 16
    assert component.rights_multiplier(cum_price=cum, face_value=10.0) == pytest.approx(cum / terp)


def test_a_rights_issue_dilutes_less_than_a_bonus_of_the_same_ratio() -> None:
    """The economic point of the whole formula: a 1:1 bonus is free and halves
    the price, a 1:1 rights issue is paid for and dilutes far less."""
    bonus = ParsedComponent(Kind.BONUS, "Bonus", ratio_new=1, ratio_held=1)
    rights = ParsedComponent(Kind.RIGHTS, "Rights", ratio_new=1, ratio_held=1, rights_premium=80.0)
    rights_factor = rights.rights_multiplier(cum_price=100.0, face_value=10.0)
    assert rights_factor is not None
    assert bonus.bonus_split_multiplier == 2.0
    assert 1.0 < rights_factor < 2.0


def test_rights_priced_above_market_produce_no_adjustment() -> None:
    """Nobody subscribes at a premium to market, so there is no benefit and
    NSE makes no adjustment. A factor here would move prices the wrong way."""
    component = ParsedComponent(
        Kind.RIGHTS, "Rights", ratio_new=1, ratio_held=1, rights_premium=200.0
    )
    assert component.rights_multiplier(cum_price=100.0, face_value=10.0) is None


def test_rights_with_no_face_value_cannot_be_priced() -> None:
    """Issue price is face value + premium; without face value there is no
    issue price, and guessing one would misprice the dilution."""
    component = ParsedComponent(
        Kind.RIGHTS, "Rights", ratio_new=1, ratio_held=1, rights_premium=40.0
    )
    assert component.rights_multiplier(cum_price=100.0, face_value=None) is None


def test_an_at_par_rights_issue_uses_face_value_as_the_issue_price() -> None:
    """ "At Par" parses to premium 0.0, so issue price is face value alone."""
    component = ParsedComponent(
        Kind.RIGHTS, "Rights", ratio_new=1, ratio_held=1, rights_premium=0.0
    )
    terp = (1 * 100.0 + 1 * 10.0) / 2
    assert component.rights_multiplier(cum_price=100.0, face_value=10.0) == pytest.approx(
        100 / terp
    )


def test_a_bonus_multiplier_is_not_produced_for_a_rights_component() -> None:
    """The two must never be confused - a rights issue read as a bonus would
    over-dilute badly."""
    component = ParsedComponent(
        Kind.RIGHTS, "Rights", ratio_new=1, ratio_held=1, rights_premium=40.0
    )
    assert component.bonus_split_multiplier is None


def test_rights_are_omitted_when_no_close_price_lookup_is_given() -> None:
    """The price store stays buildable without market data; it simply has no
    rights in it, which is why the lookup is an explicit argument."""
    store = build_price_factor_store([_rights(ISIN, date(2020, 6, 1), 1, 1, 40.0)])
    assert len(store) == 0


def test_rights_are_included_when_a_close_price_lookup_is_given() -> None:
    store = build_price_factor_store(
        [_rights(ISIN, date(2020, 6, 1), 1, 1, 40.0)], lambda isin, d: 100.0
    )
    factor = factor_as_of(store, as_of=FAR_FUTURE, isin=ISIN, price_date=date(2020, 1, 1))
    assert factor == pytest.approx(100 / 75)


def test_rights_appear_in_the_total_return_store_too() -> None:
    """A rights issue changes the share count, so it belongs in both series."""
    store = build_total_return_factor_store(
        [_rights(ISIN, date(2020, 6, 1), 1, 1, 40.0)], lambda isin, d: 100.0
    )
    factor = factor_as_of(store, as_of=FAR_FUTURE, isin=ISIN, price_date=date(2020, 1, 1))
    assert factor == pytest.approx(100 / 75)


def test_a_rights_issue_is_still_behind_the_firewall() -> None:
    store = build_price_factor_store(
        [_rights(ISIN, date(2020, 6, 1), 1, 1, 40.0)], lambda isin, d: 100.0
    )
    as_of = session_close("2020-05-31")
    assert factor_as_of(store, as_of=as_of, isin=ISIN, price_date=date(2020, 1, 1)) == 1.0
