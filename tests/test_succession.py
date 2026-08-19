"""Rename, merger and demerger are three different things.

Collapsing them into one alias map was nearly shipped in Sprint 1. These tests
pin the distinction that would have made it wrong.
"""

from __future__ import annotations

from datetime import date
from fractions import Fraction

import pytest

from eulerlab.master.succession import (
    KNOWN_SUCCESSIONS,
    Succession,
    SuccessionKind,
)


def test_a_rename_continues_the_price_series() -> None:
    zomato = Succession(
        predecessor="ZOMATO",
        successor="ETERNAL",
        kind=SuccessionKind.RENAME,
        effective=date(2025, 7, 1),
    )
    assert zomato.continues_price_series


def test_a_merger_does_not_continue_the_price_series() -> None:
    """The whole point. HDFC Ltd and HDFC Bank were two separate companies.

    Fetching HDFCBANK to fill a gap labelled HDFC substitutes a different
    company's prices, and nothing downstream would flag it.
    """
    hdfc = next(s for s in KNOWN_SUCCESSIONS if s.predecessor == "HDFC")
    assert hdfc.kind is SuccessionKind.MERGER
    assert not hdfc.continues_price_series


def test_hdfc_merger_terms_match_the_announcement() -> None:
    hdfc = next(s for s in KNOWN_SUCCESSIONS if s.predecessor == "HDFC")
    assert hdfc.successor == "HDFCBANK"
    assert hdfc.effective == date(2023, 7, 1)
    assert hdfc.ratio == Fraction(42, 25)


def test_a_position_is_carried_across_a_merger_at_the_ratio() -> None:
    """100 HDFC shares became 168 HDFC Bank shares."""
    hdfc = next(s for s in KNOWN_SUCCESSIONS if s.predecessor == "HDFC")
    assert hdfc.convert_quantity(100) == pytest.approx(168.0)


def test_idfc_merger_terms_match_the_announcement() -> None:
    idfc = next(s for s in KNOWN_SUCCESSIONS if s.predecessor == "IDFC")
    assert idfc.successor == "IDFCFIRSTB"
    assert idfc.effective == date(2024, 10, 1)
    assert idfc.convert_quantity(100) == pytest.approx(155.0)


def test_a_rename_carries_quantity_unchanged() -> None:
    rename = Succession("A", "B", SuccessionKind.RENAME, date(2024, 1, 1))
    assert rename.convert_quantity(100) == 100


def test_a_merger_without_a_ratio_is_rejected() -> None:
    """Without a ratio a position cannot be carried, so it must not be recorded."""
    with pytest.raises(ValueError, match="needs a ratio"):
        Succession("A", "B", SuccessionKind.MERGER, date(2024, 1, 1))


def test_a_rename_with_a_ratio_is_rejected() -> None:
    with pytest.raises(ValueError, match="exchanges nothing"):
        Succession("A", "B", SuccessionKind.RENAME, date(2024, 1, 1), ratio=Fraction(2))


def test_every_known_succession_cites_a_source() -> None:
    # Corporate-action terms are facts about the world; the project's truth
    # rules require a citation for each.
    for s in KNOWN_SUCCESSIONS:
        assert s.source, f"{s.predecessor} has no source"


def test_demergers_also_require_a_ratio() -> None:
    with pytest.raises(ValueError, match="needs a ratio"):
        Succession("PEL", "PPLPHARMA", SuccessionKind.DEMERGER, date(2022, 10, 19))


# --- cancellation: a share class extinguished within the same company ---


def test_a_cancellation_ends_the_price_series() -> None:
    """Tata Motors DVR was not a rename to TATAMOTORS.

    DVR shares traded at a persistent discount to ordinary, so the two series
    are not continuous. Aliasing them would splice a discounted series onto a
    full-price one.
    """
    dvr = next(s for s in KNOWN_SUCCESSIONS if s.predecessor == "TATAMTRDVR")
    assert dvr.kind is SuccessionKind.CANCELLATION
    assert not dvr.continues_price_series


def test_dvr_conversion_ratio_matches_the_announcement() -> None:
    dvr = next(s for s in KNOWN_SUCCESSIONS if s.predecessor == "TATAMTRDVR")
    assert dvr.effective == date(2024, 9, 1)
    assert dvr.convert_quantity(1000) == pytest.approx(700.0)  # 7 ordinary per 10 DVR


def test_a_cancellation_requires_a_ratio() -> None:
    with pytest.raises(ValueError, match="needs a ratio"):
        Succession("X", "Y", SuccessionKind.CANCELLATION, date(2024, 1, 1))


def test_mindtree_and_tv18_and_pel_terms() -> None:
    by = {s.predecessor: s for s in KNOWN_SUCCESSIONS}
    assert by["MINDTREE"].convert_quantity(100) == pytest.approx(73.0)
    assert by["TV18BRDCST"].convert_quantity(172) == pytest.approx(100.0)
    assert by["PEL"].convert_quantity(500) == pytest.approx(500.0)  # 1-for-1


def test_no_succession_is_recorded_without_a_source() -> None:
    for s in KNOWN_SUCCESSIONS:
        assert len(s.source) > 20, f"{s.predecessor} source is too thin to verify"


# --- delisting with no successor, and known events with unknown terms ---


def test_an_insolvency_delisting_has_no_successor() -> None:
    """JPASSOCIAT was delisted in CIRP. Holders received nothing."""
    jp = next(s for s in KNOWN_SUCCESSIONS if s.predecessor == "JPASSOCIAT")
    assert jp.kind is SuccessionKind.DELISTING
    assert jp.successor == ""
    assert jp.convert_quantity(1000) == 0.0


def test_a_delisting_may_not_carry_a_ratio() -> None:
    with pytest.raises(ValueError, match="no successor to exchange into"):
        Succession("X", "", SuccessionKind.DELISTING, date(2024, 1, 1), ratio=Fraction(1))


def test_a_known_merger_with_unknown_terms_is_recorded_not_dropped() -> None:
    """'Merged into X, ratio unknown' and 'no idea what happened' differ.

    DHANI merged into Indiabulls Ltd on a known date, but the per-share ratio
    was not published in the sources checked. Recording the event keeps the
    instrument from being mistaken for a live listing.
    """
    dhani = next(s for s in KNOWN_SUCCESSIONS if s.predecessor == "DHANI")
    assert dhani.kind is SuccessionKind.MERGER
    assert dhani.successor == "IBULLSLTD"
    assert dhani.terms_pending
    assert dhani.ratio is None


def test_converting_across_unknown_terms_refuses_rather_than_guessing() -> None:
    """Returning the original quantity would understate the position silently."""
    dhani = next(s for s in KNOWN_SUCCESSIONS if s.predecessor == "DHANI")
    with pytest.raises(ValueError, match="terms unknown"):
        dhani.convert_quantity(100)


def test_a_merger_still_needs_a_ratio_unless_terms_are_pending() -> None:
    with pytest.raises(ValueError, match="needs a ratio"):
        Succession("A", "B", SuccessionKind.MERGER, date(2024, 1, 1))
    ok = Succession("A", "B", SuccessionKind.MERGER, date(2024, 1, 1), terms_pending=True)
    assert ok.ratio is None
