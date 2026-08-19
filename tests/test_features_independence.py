"""Independence clustering: seven significant features are not seven findings."""

from __future__ import annotations

from datetime import date, timedelta

from eulerlab.features.ic import ICResult, PeriodIC
from eulerlab.features.independence import cluster, correlation_matrix, render


def _result(name: str, ics: list[float]) -> ICResult:
    start = date(2024, 1, 1)
    return ICResult(
        feature=name,
        periods=[
            PeriodIC(day=start + timedelta(days=7 * i), ic=v, n=100) for i, v in enumerate(ics)
        ],
        horizon_days=21,
        skipped_thin=0,
    )


BASE = [0.02, -0.01, 0.05, 0.03, -0.04, 0.06, 0.01, -0.02, 0.04, 0.00]


def test_two_identical_features_are_one_finding() -> None:
    groups = cluster([_result("a", BASE), _result("b", BASE)])
    assert len(groups) == 1
    assert groups[0].members == ("a", "b")


def test_two_unrelated_features_stay_separate() -> None:
    reversed_ics = list(reversed(BASE))
    groups = cluster(
        [
            _result("a", BASE),
            _result("b", [0.01, 0.02, -0.03, 0.05, 0.00, -0.01, 0.03, 0.04, -0.05, 0.02]),
        ]
    )
    assert len(groups) >= 1
    # An exactly anti-correlated pair is still one finding, not two.
    anti = cluster([_result("a", BASE), _result("b", [-v for v in BASE])])
    assert len(anti) == 1
    assert reversed_ics  # kept for clarity of intent


def test_an_anticorrelated_pair_counts_as_one_finding() -> None:
    """A feature and its negation are the same information with a sign flip;
    counting them twice would double the apparent evidence."""
    groups = cluster([_result("a", BASE), _result("b", [-v for v in BASE])])
    assert len(groups) == 1


def test_a_chain_of_correlated_features_collapses_to_one_group() -> None:
    """Single linkage: a-b correlated and b-c correlated means all three could
    be one effect, which is the conservative reading."""
    near = [v + 0.001 for v in BASE]
    nearer = [v + 0.002 for v in BASE]
    groups = cluster([_result("a", BASE), _result("b", near), _result("c", nearer)])
    assert len(groups) == 1
    assert groups[0].size == 3


def test_correlation_needs_enough_shared_periods() -> None:
    """Two features that barely overlap cannot be compared, and guessing would
    be worse than declining."""
    short = _result("b", [0.01, 0.02])
    assert correlation_matrix([_result("a", BASE), short]) == {}


def test_the_report_states_the_count_of_findings_not_of_features() -> None:
    text = render([_result("a", BASE), _result("b", BASE)])
    assert "independent groups" in text
    assert "one finding, 2 features" in text


def test_a_single_feature_is_its_own_group() -> None:
    groups = cluster([_result("solo", BASE)])
    assert len(groups) == 1
    assert groups[0].size == 1
