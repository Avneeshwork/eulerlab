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
