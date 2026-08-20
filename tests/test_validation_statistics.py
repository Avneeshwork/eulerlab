"""Deflated Sharpe, PBO and MinBTL: how impressed should we be, given N tries?"""

from __future__ import annotations

import math
import random

import pytest

from eulerlab.validation.statistics import (
    deflated_sharpe,
    expected_max_sharpe,
    min_backtest_length,
    probability_of_backtest_overfitting,
    sharpe_stats,
)


def _noise(n: int = 2500, seed: int = 0) -> list[float]:
    rng = random.Random(seed)
    return [rng.gauss(0, 0.01) for _ in range(n)]


# --- the core idea: more tries, higher bar ---


def test_the_expected_best_of_n_noise_strategies_rises_with_n() -> None:
    """With enough attempts an impressive Sharpe is the *expected* outcome of
    pure noise. This is the benchmark a real strategy must beat."""
    values = [expected_max_sharpe(n) for n in (2, 10, 100, 1000)]
    assert values == sorted(values)
    assert values[-1] > 3.0


def test_a_single_trial_needs_no_correction() -> None:
    assert expected_max_sharpe(1) == 0.0


def test_more_trials_demand_more_history() -> None:
    """If the required history exceeds what exists, no analysis of that
    history can support the claim."""
    assert min_backtest_length(1000) > min_backtest_length(10) > 0


def test_a_higher_target_sharpe_needs_less_history() -> None:
    assert min_backtest_length(100, target_sharpe=2.0) < min_backtest_length(100, target_sharpe=0.5)


# --- deflation ---


def test_noise_survives_one_trial_but_not_many() -> None:
    """The whole point. The same return stream is plausible if you looked
    once and is obviously nothing if you looked a hundred times."""
    stats = sharpe_stats(_noise())
    assert deflated_sharpe(stats, n_trials=1) > deflated_sharpe(stats, n_trials=100)


def test_the_deflated_sharpe_falls_as_trials_rise() -> None:
    stats = sharpe_stats([0.001 + r for r in _noise()])
    values = [deflated_sharpe(stats, n_trials=n) for n in (1, 5, 50, 500)]
    assert values == sorted(values, reverse=True)


def test_a_flat_return_stream_has_no_deflated_sharpe() -> None:
    assert deflated_sharpe(sharpe_stats([0.0] * 100), n_trials=1) == 0.0


def test_too_few_observations_produce_nothing() -> None:
    assert deflated_sharpe(sharpe_stats([0.01, 0.02]), n_trials=1) == 0.0


def test_negative_skew_is_penalised() -> None:
    """Deflation is harsher for negatively skewed, fat-tailed streams - which
    is what most trading strategies produce, so ignoring the moments
    understates the correction in the flattering direction."""
    base = _noise(1000)
    skewed = [*base]
    skewed[100] = -0.20  # one big loss
    plain = sharpe_stats([abs(r) * 0.0 + r for r in base])
    assert sharpe_stats(skewed).skew < plain.skew


def test_moments_are_computed() -> None:
    stats = sharpe_stats(_noise())
    assert stats.n == 2500
    assert math.isfinite(stats.skew)
    assert math.isfinite(stats.kurtosis)


# --- PBO ---


def test_a_selection_that_always_picks_the_worst_scores_pbo_one() -> None:
    """PBO indicts the act of choosing, not any single configuration."""
    in_sample = [[3.0, 2.0, 1.0]] * 10
    out_of_sample = [[1.0, 2.0, 3.0]] * 10  # the in-sample winner is worst OOS
    result = probability_of_backtest_overfitting(in_sample, out_of_sample)
    assert result.pbo == 1.0
    assert "noise" in result.verdict


def test_a_selection_that_always_picks_the_best_scores_pbo_zero() -> None:
    in_sample = [[3.0, 2.0, 1.0]] * 10
    out_of_sample = [[3.0, 2.0, 1.0]] * 10
    result = probability_of_backtest_overfitting(in_sample, out_of_sample)
    assert result.pbo == 0.0
    assert "low" in result.verdict


def test_too_few_paths_is_reported_rather_than_estimated() -> None:
    result = probability_of_backtest_overfitting([[2.0, 1.0]], [[1.0, 2.0]])
    assert "too few paths" in result.verdict


def test_mismatched_inputs_are_an_error() -> None:
    with pytest.raises(ValueError, match="same splits"):
        probability_of_backtest_overfitting([[1.0, 2.0]], [[1.0, 2.0], [1.0, 2.0]])


def test_a_single_configuration_cannot_be_overfit_by_selection() -> None:
    """With nothing to choose between, there is no selection to indict."""
    result = probability_of_backtest_overfitting([[1.0]] * 5, [[1.0]] * 5)
    assert result.n_paths == 0
