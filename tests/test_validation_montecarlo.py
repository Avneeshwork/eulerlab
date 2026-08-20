"""Monte Carlo resampling, and the property most implementations get wrong.

The headline test is `test_shuffling_cannot_change_the_sharpe`. Mean and
standard deviation are invariant under reordering, so any tool reporting a
"Monte Carlo Sharpe distribution" from shuffling alone is reporting zero
information. Asserting it here means this module can never quietly acquire that
bug.
"""

from __future__ import annotations

import random

import pytest

from eulerlab.validation.montecarlo import max_drawdown, run
from eulerlab.validation.statistics import sharpe_stats


def _returns(n: int = 500, seed: int = 7) -> list[float]:
    rng = random.Random(seed)
    return [rng.gauss(0.0004, 0.011) for _ in range(n)]


def test_shuffling_cannot_change_the_sharpe() -> None:
    """The reason shuffle and bootstrap are separate tests."""
    original = _returns()
    shuffled = original[:]
    random.Random(1).shuffle(shuffled)
    assert sharpe_stats(original).sharpe == pytest.approx(sharpe_stats(shuffled).sharpe)


def test_shuffling_does_change_the_drawdown() -> None:
    """And the reason shuffling is worth doing at all: drawdown is entirely a
    property of the order losses arrive in."""
    original = _returns()
    observed = max_drawdown(original)

    paths = []
    for seed in range(30):
        shuffled = original[:]
        random.Random(seed).shuffle(shuffled)
        paths.append(max_drawdown(shuffled))

    assert len(set(paths)) > 1, "shuffling produced identical paths"
    assert min(paths) < observed, "no reordering was worse than the realised one"


def test_a_monotonic_series_has_no_drawdown() -> None:
    assert max_drawdown([0.01] * 50) == 0.0


def test_drawdown_is_negative_and_bounded() -> None:
    result = max_drawdown([-0.5, -0.5])
    assert -1.0 < result < 0.0


def test_the_result_is_deterministic() -> None:
    """CLAUDE.md requires byte-identical output from identical input. An
    unseeded Monte Carlo would make every battery re-run disagree slightly with
    the last, which is indistinguishable from a real change."""
    a = run(_returns(), simulations=80)
    b = run(_returns(), simulations=80)
    assert a.drawdown == b.drawdown
    assert a.sharpe == b.sharpe


def test_a_different_seed_gives_a_different_answer() -> None:
    a = run(_returns(), simulations=80, seed=1)
    b = run(_returns(), simulations=80, seed=2)
    assert a.drawdown.p50 != b.drawdown.p50


def test_percentiles_are_ordered() -> None:
    result = run(_returns(), simulations=200)
    assert result.drawdown.worst <= result.drawdown.p05 <= result.drawdown.p50
    assert result.drawdown.p50 <= result.drawdown.p95
    assert result.sharpe.p05 <= result.sharpe.p50 <= result.sharpe.p95


def test_the_observed_sharpe_sits_near_the_bootstrap_median() -> None:
    """A sanity check on the bootstrap: resampling the same distribution should
    centre on the statistic it was drawn from."""
    result = run(_returns(n=800), simulations=300)
    assert abs(result.sharpe.p50 - result.observed_sharpe) < 0.35


def test_a_no_edge_series_is_reported_as_possibly_zero() -> None:
    rng = random.Random(3)
    flat = [rng.gauss(0.0, 0.01) for _ in range(600)]
    assert run(flat, simulations=300).sharpe_could_be_zero


def test_too_few_returns_is_refused() -> None:
    with pytest.raises(ValueError, match="too few"):
        run([0.01] * 10)


def test_the_report_states_the_exchangeability_caveat() -> None:
    """Shuffling breaks up volatility clustering, which is what produces the
    worst real drawdowns. A report that omits this overstates its own power."""
    text = run(_returns(), simulations=60).render()
    assert "exchangeable" in text
    assert "LOWER bound" in text


def test_the_report_distinguishes_the_two_tests() -> None:
    text = run(_returns(), simulations=60).render()
    assert "PATH risk only" in text
    assert "confidence" in text


def test_drawdowns_are_stored_as_fractions_not_percentages() -> None:
    """The regression behind two bugs at once.

    Storing drawdowns pre-multiplied by 100 made `render` apply `:.1%` to an
    already-scaled number (it printed -2258.9%), and made the
    shallower-than-median comparison test a fraction against a percentage, so
    it always took the wrong branch.
    """
    result = run(_returns(), simulations=60)
    assert -1.0 < result.drawdown.p50 <= 0.0
    assert result.drawdown.observed == result.observed_drawdown


def test_the_verdict_matches_the_numbers_it_quotes() -> None:
    """Whichever branch the report takes, it must agree with the comparison."""
    result = run(_returns(), simulations=200)
    text = result.render()
    if result.observed_drawdown > result.drawdown.p50:
        assert "SHALLOWER" in text
    else:
        assert "at or worse than" in text


def test_no_percentage_is_printed_beyond_one_hundred() -> None:
    import re

    for value in re.findall(r"-?(\d+(?:\.\d+)?)%", run(_returns(), simulations=60).render()):
        assert float(value) <= 100.0, f"{value}% is impossible for a drawdown"
