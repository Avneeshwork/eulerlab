"""Subject-string parsing, against real phrasings observed in the live feed.

Every string quoted here without a comment saying "synthetic" was seen in the
2015-2026 pull on 2026-08-19 - this is a regression suite against the messy
reality of NSE's free text, not against a tidy imagined format.
"""

from __future__ import annotations

from datetime import date

from eulerlab.corp_actions.parse import Kind, parse_rows, parse_subject


def _kinds(subject: str) -> list[Kind]:
    return [c.kind for c in parse_subject(subject)]


# --- bonus ---


def test_a_simple_bonus_ratio_parses() -> None:
    c = parse_subject("Bonus 1:2")[0]
    assert c.kind is Kind.BONUS
    assert (c.ratio_new, c.ratio_held) == (1, 2)
    assert c.bonus_split_multiplier == 1.5


def test_a_large_bonus_ratio_is_not_assumed_backwards() -> None:
    """ "10:1" is ten new shares per one held, not the reverse - the first
    number printed is always the issued side."""
    c = parse_subject("Bonus 10:1")[0]
    assert (c.ratio_new, c.ratio_held) == (10, 1)
    assert c.bonus_split_multiplier == 11.0


def test_a_tiny_bonus_ratio_parses() -> None:
    c = parse_subject("Bonus 1 : 1250")[0]
    assert (c.ratio_new, c.ratio_held) == (1, 1250)


def test_bonus_with_space_before_colon_on_second_number() -> None:
    c = parse_subject("Bonus 1: 1")[0]
    assert (c.ratio_new, c.ratio_held) == (1, 1)


def test_a_compound_bonus_and_face_value_split_yields_two_components() -> None:
    kinds = _kinds("Bonus 1:1 / Face Value Split From Rs 10/- Per Share To Rs 2/- Per Share")
    assert kinds == [Kind.BONUS, Kind.SPLIT]


# --- split (face value change) ---


def test_a_face_value_split_parses_old_and_new_value() -> None:
    c = parse_subject(
        "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share"
    )[0]
    assert c.kind is Kind.SPLIT
    assert (c.face_value_from, c.face_value_to) == (10.0, 2.0)
    assert c.bonus_split_multiplier == 5.0


def test_a_split_down_to_re_one_parses() -> None:
    c = parse_subject(
        "Face Value Split (Sub-Division): From Rs 10/- Per Share To Re 1/- Per Share"
    )[0]
    assert (c.face_value_from, c.face_value_to) == (10.0, 1.0)


def test_a_terse_split_with_no_per_share_wording_parses() -> None:
    c = parse_subject("Face Value Split Rs 10 To Rs 1")[0]
    assert (c.face_value_from, c.face_value_to) == (10.0, 1.0)


# --- rights ---


def test_a_rights_ratio_with_premium_parses() -> None:
    c = parse_subject("Rights 3:10 @ Premium Rs 440/- Per Share")[0]
    assert c.kind is Kind.RIGHTS
    assert (c.ratio_new, c.ratio_held) == (3, 10)
    assert c.rights_premium == 440.0


def test_a_rights_issue_at_par_has_zero_premium() -> None:
    c = parse_subject("Rights : 24:10 At Par")[0]
    assert c.rights_premium == 0.0


def test_a_rights_ratio_with_colon_before_numbers_parses() -> None:
    """ "Rights : 24:10" - the label carries its own colon before the ratio."""
    c = parse_subject("Rights : 24:10 At Par")[0]
    assert (c.ratio_new, c.ratio_held) == (24, 10)


def test_a_rights_ratio_with_space_inside_it_parses() -> None:
    c = parse_subject("Rights 5: 116 At Premium Rs 244/- Per Share")[0]
    assert (c.ratio_new, c.ratio_held) == (5, 116)


# --- dividend ---


def test_a_plain_dividend_amount_parses() -> None:
    c = parse_subject("Interim Dividend - Rs 4/- Per Share")[0]
    assert c.kind is Kind.DIVIDEND
    assert c.dividend_amount == 4.0


def test_a_sub_rupee_dividend_using_re_parses() -> None:
    c = parse_subject("Interim Dividend - Re 0.60/- Per Share (Purpose Revised)")[0]
    assert c.dividend_amount == 0.60


def test_a_dividend_with_no_space_after_rs_dot_parses() -> None:
    c = parse_subject("Interim Dividend Rs.6/- Per Share (Purpose Revised)")[0]
    assert c.dividend_amount == 6.0


def test_a_dividend_with_a_dash_before_the_amount_parses() -> None:
    """ "Rs- 70/-" - real observed typo, dash where a space belongs."""
    c = parse_subject("Annual General Meeting/Dividend Rs- 70/- Per Share")[1]
    assert c.dividend_amount == 70.0


def test_a_dividend_with_no_currency_prefix_falls_back_to_per_share() -> None:
    c = parse_subject("Dividend - 1.40 Per Share")[0]
    assert c.dividend_amount == 1.40


def test_a_double_decimal_point_typo_is_corrected_not_dropped() -> None:
    """ "62..50" appeared in the live feed. One reading is sane; use it."""
    c = parse_subject("Annual General Meeting/Dividend - Rs 62..50/- Per Share")[1]
    assert c.dividend_amount == 62.50


def test_a_dividend_with_no_amount_at_all_is_unparsed_not_zero() -> None:
    """ "Interest Payment" carries no number. Zero would be a lie about the
    source, not a fallback."""
    c = parse_subject("Interest Payment")[0]
    assert c.kind is Kind.UNPARSED
    assert c.dividend_amount is None


def test_a_meeting_and_dividend_glued_without_a_space_still_splits() -> None:
    """ "Meeting/Dividend" - no spaces around the slash, unlike most subjects."""
    kinds = _kinds("Annual General Meeting/Dividend - Rs 2.80/- Per Share")
    assert kinds == [Kind.MEETING, Kind.DIVIDEND]


# --- classification only, no numbers needed ---


def test_a_buyback_is_recognised() -> None:
    assert _kinds("Buyback Of Shares")[0] is Kind.BUYBACK


def test_a_demerger_is_recognised_but_not_priced_here() -> None:
    """Ratios for demergers come from Sprint 3's succession model, not this
    feed - see the module docstring."""
    c = parse_subject("Demerger")[0]
    assert c.kind is Kind.DEMERGER
    assert c.bonus_split_multiplier is None


def test_an_annual_general_meeting_alone_is_a_meeting() -> None:
    assert _kinds("Annual General Meeting")[0] is Kind.MEETING


def test_a_distribution_with_no_amount_is_unparsed_not_guessed_at() -> None:
    """Real observed text. "Distribution" is a price-relevant keyword with no
    extractable number here, so UNPARSED is honest; OTHER would silently
    drop it."""
    c = parse_subject("For Distribution Of Chennai Super Kings Cricket Limited Shares")[0]
    assert c.kind is Kind.UNPARSED


def test_genuinely_unrecognised_text_is_other() -> None:
    c = parse_subject("Scheme Of Amalgamation")[0]
    assert c.kind is Kind.OTHER


# --- row-level parsing ---


def test_a_row_missing_isin_is_skipped_and_counted() -> None:
    rows: list[dict[str, object]] = [
        {"isin": "", "symbol": "X", "exDate": "05-Jan-2015", "subject": "Bonus 1:1"}
    ]
    actions, skipped = parse_rows(rows)
    assert actions == []
    assert skipped == 1


def test_a_row_with_a_dash_for_exdate_is_skipped() -> None:
    rows: list[dict[str, object]] = [
        {"isin": "INE000A01001", "symbol": "X", "exDate": "-", "subject": "Bonus 1:1"}
    ]
    actions, skipped = parse_rows(rows)
    assert actions == []
    assert skipped == 1


def test_a_well_formed_row_parses_end_to_end() -> None:
    rows: list[dict[str, object]] = [
        {
            "isin": "INE233A01035",
            "symbol": "GODREJIND",
            "exDate": "05-Jan-2015",
            "subject": "Bonus 1 : 1250",
        }
    ]
    actions, skipped = parse_rows(rows)
    assert skipped == 0
    assert len(actions) == 1
    action = actions[0]
    assert action.isin == "INE233A01035"
    assert action.ex_date == date(2015, 1, 5)
    assert action.components[0].kind is Kind.BONUS


def test_unparsed_components_are_visible_on_the_action() -> None:
    rows: list[dict[str, object]] = [
        {
            "isin": "INE000A01001",
            "symbol": "X",
            "exDate": "05-Jan-2015",
            "subject": "Interest Payment",
        }
    ]
    actions, _ = parse_rows(rows)
    assert len(actions[0].unparsed) == 1
