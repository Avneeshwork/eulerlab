"""`make check-adjust` — the acceptance gate itself must fail when it should.

A gate that cannot go red is decoration. Each test here feeds the checks a
deliberately wrong action and asserts the check catches it.
"""

from __future__ import annotations

from datetime import date

from eulerlab.corp_actions.check import (
    check_actions_parse,
    check_bonus_ratios_independently,
    check_determinism,
    check_firewall_holds,
    check_rights_against_terp,
    check_split_ratios_independently,
)
from eulerlab.corp_actions.parse import CorporateAction, Kind, ParsedComponent


def _action(component: ParsedComponent, *, face_value: float | None = 10.0) -> CorporateAction:
    return CorporateAction(
        isin="INE000A01001",
        symbol="X",
        ex_date=date(2020, 6, 1),
        components=(component,),
        raw_subject=component.raw,
        face_value=face_value,
    )


# --- the gate goes green on correct input ---


def test_a_correct_bonus_passes() -> None:
    action = _action(ParsedComponent(Kind.BONUS, "Bonus 1:2", ratio_new=1, ratio_held=2))
    assert check_bonus_ratios_independently([action]).status == "PASS"


def test_a_correct_split_passes() -> None:
    action = _action(
        ParsedComponent(
            Kind.SPLIT, "Face Value Split Rs 10 To Rs 2", face_value_from=10.0, face_value_to=2.0
        )
    )
    assert check_split_ratios_independently([action]).status == "PASS"


def test_a_correct_rights_passes() -> None:
    action = _action(
        ParsedComponent(
            Kind.RIGHTS,
            "Rights 1:1 @ Premium Rs 40",
            ratio_new=1,
            ratio_held=1,
            rights_premium=40.0,
        )
    )
    assert check_rights_against_terp([action]).status == "PASS"


# --- the gate goes red on wrong input, which is the part that matters ---


def test_a_bonus_ratio_read_backwards_is_caught() -> None:
    """The subject says 1:2 but the parsed ratio is 2:1. Re-deriving from the
    raw text is what catches this; comparing the code to itself would not."""
    action = _action(ParsedComponent(Kind.BONUS, "Bonus 1:2", ratio_new=2, ratio_held=1))
    result = check_bonus_ratios_independently([action])
    assert result.failed


def test_a_split_that_increases_face_value_is_caught() -> None:
    """A split reduces face value. The reverse means the two values were
    swapped, which would multiply prices instead of dividing them."""
    action = _action(
        ParsedComponent(
            Kind.SPLIT, "Face Value Split Rs 2 To Rs 10", face_value_from=2.0, face_value_to=10.0
        )
    )
    result = check_split_ratios_independently([action])
    assert result.failed
    assert "backwards" in result.detail


def test_rights_dilution_is_bounded_above_by_the_equivalent_free_bonus() -> None:
    """The invariant the gate guards, stated as the property it actually is.

    `P/TERP` is maximised at issue price zero, where it equals the bonus
    factor exactly — free shares *are* a bonus. So a paid rights issue can
    never dilute more than the same ratio given away, which means the gate's
    over-dilution branch is unreachable while the formula is correct. It stays
    in as a tripwire for a future change to that formula.
    """
    free = ParsedComponent(Kind.RIGHTS, "Rights 1:1", ratio_new=1, ratio_held=1, rights_premium=0.0)
    paid = ParsedComponent(
        Kind.RIGHTS, "Rights 1:1", ratio_new=1, ratio_held=1, rights_premium=500.0
    )
    at_zero = free.rights_multiplier(cum_price=1000.0, face_value=0.0)
    discounted = paid.rights_multiplier(cum_price=1000.0, face_value=0.0)

    assert at_zero == 2.0  # identical to a 1:1 bonus
    assert discounted is not None
    assert discounted < at_zero

    for component in (free, paid):
        assert check_rights_against_terp([_action(component, face_value=0.0)]).status == "PASS"


def test_no_actions_at_all_is_a_failure_not_a_pass() -> None:
    """An empty dataset must not report green - that is how a broken ingest
    slips through a gate."""
    assert check_actions_parse([], 0).failed


def test_skipped_rows_are_a_failure() -> None:
    action = _action(ParsedComponent(Kind.BONUS, "Bonus 1:1", ratio_new=1, ratio_held=1))
    assert check_actions_parse([action], 5).failed


# --- structural checks ---


def test_the_firewall_check_passes_on_a_normal_action() -> None:
    action = _action(ParsedComponent(Kind.BONUS, "Bonus 1:1", ratio_new=1, ratio_held=1))
    assert check_firewall_holds([action]).status == "PASS"


def test_determinism_passes_on_the_same_input() -> None:
    action = _action(ParsedComponent(Kind.BONUS, "Bonus 1:1", ratio_new=1, ratio_held=1))
    assert check_determinism([action]).status == "PASS"
