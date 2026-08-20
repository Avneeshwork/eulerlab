"""The critic rejects before a trial is spent — and is advisory, not a gate."""

from __future__ import annotations

from pathlib import Path

import yaml

from eulerlab.research import critic


def _card(tmp_path: Path, **overrides: object) -> Path:
    spec: dict[str, object] = {
        "id": "H-0099",
        "title": "t",
        "status": "registered",
        "claim": "c",
        "configurations": [
            {"feature": "momentum_12_1", "top_n": 30},
            {"feature": "reversal_1m", "top_n": 30},
        ],
        "red_flags": ["Sprint 13 measured a +0.95 IC correlation in this cluster."],
    }
    spec.update(overrides)
    path = tmp_path / "H-0099.yaml"
    path.write_text(yaml.safe_dump(spec), encoding="utf-8")
    return path


def test_a_sound_card_has_no_blockers(tmp_path: Path) -> None:
    review = critic.review(_card(tmp_path), available_years=11.4)
    assert review.worth_testing


def test_an_unbuildable_card_is_blocked(tmp_path: Path) -> None:
    """A trial spent on something that cannot run is pure waste."""
    path = _card(tmp_path, configurations=[{"feature": "nope"}, {"feature": "also_nope"}])
    assert not critic.review(path, available_years=11.4).worth_testing


def test_a_single_configuration_is_blocked(tmp_path: Path) -> None:
    path = _card(tmp_path, configurations=[{"feature": "momentum_12_1", "top_n": 30}])
    review = critic.review(path, available_years=11.4)
    assert not review.worth_testing
    assert any("PBO" in o.detail for o in review.blockers)


def test_no_history_makes_a_trial_unaffordable(tmp_path: Path) -> None:
    assert not critic.review(_card(tmp_path), available_years=0.1).worth_testing


def test_configurations_from_one_measured_cluster_are_flagged(tmp_path: Path) -> None:
    """Sprint 13 measured these moving together at +0.86 to +0.95. PBO will
    read them as separate choices when they are not."""
    path = _card(
        tmp_path,
        configurations=[
            {"feature": "low_volatility", "top_n": 30},
            {"feature": "max_drawdown", "top_n": 30},
        ],
    )
    review = critic.review(path, available_years=11.4)
    assert any(o.rule == "one finding, not several" for o in review.objections)


def test_unrelated_features_are_not_flagged_as_a_cluster(tmp_path: Path) -> None:
    path = _card(
        tmp_path,
        configurations=[
            {"feature": "momentum_12_1", "top_n": 30},
            {"feature": "turnover_liquidity", "top_n": 30},
        ],
    )
    review = critic.review(path, available_years=11.4)
    assert not any(o.rule == "one finding, not several" for o in review.objections)


def test_a_card_that_disowns_its_own_evidence_is_flagged(tmp_path: Path) -> None:
    """Testing anyway means proceeding on a case the card itself retracts."""
    path = _card(
        tmp_path,
        red_flags=["The supporting t-statistic cannot be cited; it came from raw prices."],
    )
    review = critic.review(path, available_years=11.4)
    assert any(o.rule == "own evidence disowned" for o in review.objections)


def test_a_draft_card_is_noted_as_not_registered(tmp_path: Path) -> None:
    review = critic.review(_card(tmp_path, status="draft"), available_years=11.4)
    assert any(o.rule == "not registered" for o in review.objections)


def test_the_bar_after_this_trial_is_always_reported(tmp_path: Path) -> None:
    """The cost of testing is stated whether or not anything else is wrong."""
    review = critic.review(_card(tmp_path), available_years=11.4)
    assert any(o.rule == "bar after this trial" for o in review.objections)


def test_the_critic_never_kills_anything(tmp_path: Path) -> None:
    """It is advisory. Making it binding would give an automated component
    veto power over research direction on the strength of heuristics."""
    review = critic.review(
        _card(tmp_path, configurations=[{"feature": "nope"}]), available_years=0.01
    )
    assert review.blockers
    assert not hasattr(review, "kill")
    assert "cannot refuse" in review.render()


def test_the_real_card_reviews_without_error() -> None:
    review = critic.review(Path("hypotheses/H-0002.yaml"), available_years=11.4)
    assert review.hypothesis == "H-0002"
