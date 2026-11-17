"""`make relock-moved` relocks only deployments whose code merely moved (ADR-219)."""

from __future__ import annotations

from tools.relock_moved import decide


def test_an_unchanged_lock_is_left_alone() -> None:
    assert decide("abc", "abc", "abc") == "same"


def test_a_lock_that_matched_the_code_before_the_move_is_relocked() -> None:
    assert decide("old", "old", "new") == "relock"


def test_a_lock_that_had_already_drifted_is_left_for_review() -> None:
    assert decide("older", "old", "new") == "review"


def test_a_strategy_whose_source_cannot_be_read_is_never_relocked() -> None:
    assert decide("old", "old", "") == "review"
    assert decide("old", "", "new") == "review"
