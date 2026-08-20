"""Purged, embargoed, combinatorial cross-validation.

The property that matters is negative: after purging, no training day's label
window may reach into the test set. It is asserted directly rather than
assumed from the construction, because a purge of the wrong width looks
rigorous and leaks anyway.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from eulerlab.validation.cpcv import blocks, cpcv_splits, leakage_check, split

DAYS = [date(2020, 1, 1) + timedelta(days=i) for i in range(120)]


# --- blocks ---


def test_blocks_are_contiguous_and_cover_everything() -> None:
    """Contiguous, not interleaved: a block must be a stretch of calendar time
    or purging and embargo mean nothing."""
    result = blocks(DAYS, 6)
    assert sum(len(b) for b in result) == len(DAYS)
    flat = [d for b in result for d in b]
    assert flat == DAYS


def test_uneven_lengths_are_spread_not_dumped_on_the_last_block() -> None:
    result = blocks(DAYS[:100], 7)
    sizes = [len(b) for b in result]
    assert max(sizes) - min(sizes) <= 1


def test_too_few_blocks_is_an_error() -> None:
    with pytest.raises(ValueError, match="at least 2 blocks"):
        blocks(DAYS, 1)


def test_more_blocks_than_days_is_an_error() -> None:
    with pytest.raises(ValueError, match="cannot be split"):
        blocks(DAYS[:3], 6)


# --- purging: the property, asserted ---


def test_no_training_day_leaks_into_the_test_set() -> None:
    """The guarantee purging exists for, checked on every path."""
    for s in cpcv_splits(DAYS, n_blocks=6, test_block_count=2, horizon=10, embargo=3):
        assert leakage_check(s, DAYS, horizon=10) is None


def test_removing_the_purge_reintroduces_the_leak() -> None:
    """Proves the check can fail, and that purging is what prevents it."""
    all_blocks = blocks(DAYS, 6)
    unpurged = split(DAYS, [all_blocks[2]], horizon=0, embargo=0)
    assert leakage_check(unpurged, DAYS, horizon=10) is not None


def test_purging_removes_exactly_the_horizon_before_a_test_block() -> None:
    all_blocks = blocks(DAYS, 6)
    s = split(DAYS, [all_blocks[3]], horizon=7, embargo=0)
    assert s.purged == 7


def test_embargo_removes_days_after_the_test_block() -> None:
    all_blocks = blocks(DAYS, 6)
    s = split(DAYS, [all_blocks[2]], horizon=0, embargo=4)
    assert s.embargoed == 4


def test_a_test_block_at_the_start_has_nothing_to_purge() -> None:
    """No prior days exist, so purged=0 is correct rather than a bug."""
    all_blocks = blocks(DAYS, 6)
    s = split(DAYS, [all_blocks[0]], horizon=10, embargo=0)
    assert s.purged == 0


def test_a_test_block_at_the_end_has_nothing_to_embargo() -> None:
    all_blocks = blocks(DAYS, 6)
    s = split(DAYS, [all_blocks[-1]], horizon=0, embargo=10)
    assert s.embargoed == 0


# --- the bug that made the check itself wrong ---


def test_the_leakage_check_measures_the_real_calendar() -> None:
    """The check's first version derived its ordering from train+test days -
    the timeline *after* purging removed the gap. Two dates 42 trading days
    apart appeared adjacent, and it reported leakage on 14 of 15 correctly
    purged paths. A label window is measured in elapsed sessions, so it can
    only be checked against the real calendar.
    """
    all_blocks = blocks(DAYS, 6)
    s = split(DAYS, [all_blocks[3]], horizon=10, embargo=0)
    # Correctly purged, so clean against the real timeline...
    assert leakage_check(s, DAYS, horizon=10) is None
    # ...and the filtered timeline is genuinely shorter, which is what fooled
    # the original implementation.
    assert len(s.train_days) + len(s.test_days) < len(DAYS)


# --- combinatorics ---


def test_six_choose_two_produces_fifteen_paths() -> None:
    """Many paths from one history is what makes PBO estimable at all."""
    assert len(list(cpcv_splits(DAYS, n_blocks=6, test_block_count=2))) == 15


def test_every_path_has_both_train_and_test_data() -> None:
    for s in cpcv_splits(DAYS, n_blocks=6, test_block_count=2, horizon=5, embargo=2):
        assert s.n_train > 0
        assert s.n_test > 0


def test_train_and_test_never_overlap() -> None:
    for s in cpcv_splits(DAYS, n_blocks=6, test_block_count=2, horizon=5, embargo=2):
        assert not (set(s.train_days) & set(s.test_days))
