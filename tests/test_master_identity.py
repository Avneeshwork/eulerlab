"""Which strings may be trusted as join keys.

Every case here comes from a real observation against our own bhavcopy history,
recorded in docs/RESEARCH/006-instrument-identity.md.
"""

from __future__ import annotations

import pytest

from eulerlab.master.identity import InstrumentId, NotAnIsin, is_equity_isin


def test_zomato_and_eternal_are_the_same_instrument() -> None:
    """The rename that broke three datasets. Same ISIN, so same internal id."""
    assert InstrumentId.from_isin("INE758T01015") == InstrumentId.from_isin("INE758T01015")


def test_a_face_value_reissue_keeps_the_same_instrument() -> None:
    """139 of 149 observed ISIN changes were this: same issuer, reissued tail.

    SILVERTUC went INE625X01018 -> INE625X01026 between 2023 and 2026. Treating
    those as two different companies would split one price history in two.
    """
    before = InstrumentId.from_isin("INE625X01018")
    after = InstrumentId.from_isin("INE625X01026")
    assert before == after


def test_different_issuers_are_different_instruments() -> None:
    assert InstrumentId.from_isin("INE758T01015") != InstrumentId.from_isin("INE625X01018")


@pytest.mark.parametrize(
    "isin", ["", "   ", "GARBAGE", "US0378331005", "INE758T0101", "INE758T010155"]
)
def test_malformed_isins_are_rejected(isin: str) -> None:
    with pytest.raises(NotAnIsin):
        InstrumentId.from_isin(isin)


def test_isins_are_normalised() -> None:
    assert InstrumentId.from_isin("  ine758t01015  ") == InstrumentId.from_isin("INE758T01015")


def test_equity_and_fund_isins_are_distinguished() -> None:
    # The 10 genuinely-different-security cases were all INF fund units, where
    # a new ISIN really does mean a new instrument rather than a reissue.
    assert is_equity_isin("INE758T01015")
    assert not is_equity_isin("INF179KC1FA4")
    assert not is_equity_isin("nonsense")


# --- fund units must not be merged by issuer prefix ---


def test_etfs_from_one_fund_house_stay_separate_instruments() -> None:
    """INF209KB19 covers ABSLPSE, BSLNIFTY and SILVER on the same day.

    Keying those on the issuer prefix merged three unrelated ETFs into one
    instrument whose ticker appeared to flap, inflating the rename count from a
    few hundred to 7,304. 75 prefixes had this collision; all were INF.
    """
    a = InstrumentId.from_isin("INF209KB19Z4")  # ABSLPSE
    b = InstrumentId.from_isin("INF209KB19D1")  # BSLNIFTY
    c = InstrumentId.from_isin("INF209KB19F6")  # SILVER
    assert len({a, b, c}) == 3


def test_equity_still_merges_a_face_value_reissue() -> None:
    """The INE rule is unchanged: same issuer, reissued tail, one instrument."""
    assert InstrumentId.from_isin("INE625X01018") == InstrumentId.from_isin("INE625X01026")


def test_a_fund_reissue_is_a_different_instrument() -> None:
    # Deliberate asymmetry: for funds we cannot tell a reissue from a new
    # product, so we do not guess. Over-splitting is the safer error.
    assert InstrumentId.from_isin("INF179KC1FA4") != InstrumentId.from_isin("INF179KC1HT0")
