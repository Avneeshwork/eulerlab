"""Why MAD and not standard deviation — demonstrated, not asserted.

The claim in `robust.py` is that standard deviation is broken by the very
outlier it is meant to find. That claim is checked here against numbers rather
than left as a comment, because it is the whole reason this sprint exists.
"""

from __future__ import annotations

import math
import statistics

import pytest

from eulerlab.quality.robust import (
    MAD_TO_SIGMA,
    median,
    robust_scale,
    robust_z,
    spikes,
)

CLEAN = [0.01, -0.008, 0.012, -0.005, 0.009, -0.011, 0.007, 0.004, -0.003, 0.006]


# --- the demonstration ---


def test_a_three_sigma_rule_cannot_fire_at_all_on_a_small_sample() -> None:
    """The sharpest form of the problem, and it is arithmetic, not statistics.

    For a sample of n points the largest achievable z-score is (n-1)/sqrt(n).
    At n=10 that is 2.85, so a "flag anything beyond 3 sigma" rule is
    *mathematically incapable* of firing however corrupt the data is. Ten
    observations of 1% and one of 60% still yields nothing.
    """
    ten = [*CLEAN[:9], 0.60]
    sd_z = abs(0.60 - statistics.fmean(ten)) / statistics.stdev(ten)

    assert sd_z < 3.0
    assert sd_z <= (len(ten) - 1) / math.sqrt(len(ten))
    # The robust score has no such ceiling.
    assert robust_z(0.60, robust_scale(ten)) > 30.0


def test_the_robust_score_is_invariant_to_sample_size() -> None:
    """The property that makes MAD trustworthy across series of any length.

    The same 60% outlier scores the same however much clean data surrounds
    it, because the median and MAD do not move. A z-score from standard
    deviation grows with n for the identical outlier, so the same corruption
    reads as a different severity depending only on how long the history is.
    """
    scores = [robust_z(0.60, robust_scale([*CLEAN * mult, 0.60])) for mult in (1, 5, 25)]
    assert max(scores) - min(scores) < 0.5

    sd_scores = [
        abs(0.60 - statistics.fmean(s)) / statistics.stdev(s)
        for s in ([*CLEAN * mult, 0.60] for mult in (1, 5, 25))
    ]
    assert sd_scores[-1] > sd_scores[0] * 4


def test_mad_barely_moves_when_an_outlier_is_added() -> None:
    """The property that makes the above work: a 50% breakdown point."""
    before = robust_scale(CLEAN).mad
    after = robust_scale([*CLEAN, 0.60]).mad
    assert abs(after - before) < 0.002


def test_standard_deviation_moves_enormously_on_the_same_data() -> None:
    """The contrast, stated as a number rather than an adjective."""
    before = statistics.stdev(CLEAN)
    after = statistics.stdev([*CLEAN, 0.60])
    assert after > before * 5


# --- the primitives ---


def test_median_of_an_odd_series_is_the_middle_value() -> None:
    assert median([3.0, 1.0, 2.0]) == 2.0


def test_median_of_an_even_series_averages_the_middle_two() -> None:
    assert median([1.0, 2.0, 3.0, 4.0]) == 2.5


def test_median_of_an_empty_series_is_an_error_not_zero() -> None:
    """Zero would silently become a centre that no data supports."""
    with pytest.raises(ValueError, match="empty"):
        median([])


def test_the_scale_factor_makes_mad_read_like_a_sigma() -> None:
    scale = robust_scale(CLEAN)
    assert scale.sigma_equivalent == pytest.approx(scale.mad * MAD_TO_SIGMA)


# --- the degenerate case, which is where naive code divides by zero ---


def test_a_flat_series_has_zero_spread_and_is_reported_as_such() -> None:
    scale = robust_scale([5.0] * 10)
    assert scale.degenerate


def test_a_value_differing_from_a_flat_series_scores_infinite() -> None:
    """With every other point identical, any deviation is unbounded evidence.
    Returning a finite number here would understate it; crashing would be
    worse."""
    scale = robust_scale([5.0] * 10)
    assert robust_z(6.0, scale) == math.inf


def test_the_value_of_a_flat_series_is_not_itself_an_anomaly() -> None:
    scale = robust_scale([5.0] * 10)
    assert robust_z(5.0, scale) == 0.0


# --- spike detection ---


def test_a_planted_spike_is_found_at_its_index() -> None:
    values = [*CLEAN, 0.60]
    found = spikes(values)
    assert [i for i, _, _ in found] == [len(values) - 1]


def test_clean_data_produces_no_spikes() -> None:
    assert spikes(CLEAN) == []


def test_two_points_cannot_produce_a_spike() -> None:
    """Any two points sit exactly one robust sigma apart, so a spike test on
    them is meaningless. Returning nothing is right; returning a flag would be
    noise on every new instrument."""
    assert spikes([1.0, 99.0]) == []


def test_spikes_are_returned_in_index_order() -> None:
    """Determinism is a project-wide rule."""
    values = [*CLEAN, 0.60, *CLEAN, -0.75]
    found = spikes(values)
    assert [i for i, _, _ in found] == sorted(i for i, _, _ in found)


# --- the limitation of MAD, found by a test that flooded the report ---


def test_a_bimodal_series_produces_no_spikes_rather_than_flagging_everything() -> None:
    """MAD's failure mode, and why it must be handled explicitly.

    It is the *imbalance* that does it, which is easy to get wrong. A
    perfectly balanced alternating series of 20 points has median 0 and MAD
    0.08 — fine. Make it 19 points, so one value occurs ten times and the
    other nine, and the median becomes the majority value; now more than half
    the deviations are exactly 0, so their median is 0 and MAD is 0. Every
    differing point then scores infinity.

    Left unhandled this flagged nine of nineteen rows in an otherwise ordinary
    series, which is worse than useless. Per-point spike detection is
    meaningless here, so nothing is returned; the flatness itself is reported
    once by the stale-price check.
    """
    balanced = [0.08, -0.08] * 10
    assert not robust_scale(balanced).degenerate

    imbalanced = [*([0.08, -0.08] * 9), 0.08]
    assert len(imbalanced) == 19
    assert robust_scale(imbalanced).degenerate
    assert spikes(imbalanced) == []


def test_a_mostly_flat_series_is_also_degenerate() -> None:
    """The realistic version: an illiquid scrip that closes unchanged most
    days but occasionally ticks."""
    mostly_flat = [0.0] * 15 + [0.02, -0.01, 0.03]
    assert robust_scale(mostly_flat).degenerate
    assert spikes(mostly_flat) == []
