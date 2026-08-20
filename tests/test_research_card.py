"""Hypothesis cards: a pre-registration, or nothing.

The validator's job is to refuse cards that technically comply and actually
commit to nothing. These tests are mostly about it saying no.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from eulerlab.research import card


def _good(**overrides: object) -> card.Card:
    base = {
        "id": "H-0099",
        "title": "A testable claim",
        "claim": (
            "Ranking NSE equities by trailing three-month dispersion and holding the "
            "lowest decile equal-weighted earns a positive risk-adjusted return net of costs."
        ),
        "configurations": [
            {"feature": "low_volatility", "top_n": 30, "rebalance": 21},
            {"feature": "low_volatility", "top_n": 50, "rebalance": 21},
        ],
        "red_flags": [
            "Sprint 13 measured this cluster at IC correlation +0.86 to +0.95, so these "
            "configurations are closer to one finding than several.",
            "The supporting t-statistic came from raw prices on a 3-year panel (T-1317) "
            "and must not be cited as evidence until recomputed.",
            "Low-volatility books concentrate in large liquid names, the cohort that "
            "returned only 4.6% annualised in the buy-and-hold control.",
        ],
        "holdout_starts": date(2025, 1, 1),
        "source_url": "https://example.org/paper",
        "source_fetched": "2026-08-19",
    }
    base.update(overrides)
    return card.Card(**base)  # type: ignore[arg-type]


def test_a_complete_card_validates() -> None:
    assert card.validate(_good()).ok


# --- the refusals ---


def test_hedges_are_rejected_as_red_flags() -> None:
    """ "Markets can change" complies with the letter and does nothing. The
    point of writing objections down is that they are the ones you would
    rationalise away later."""
    bad = _good(
        red_flags=["Markets can change.", "Past performance is no guarantee.", "Results may vary."]
    )
    problems = card.validate(bad).problems
    assert len(problems) >= 3
    assert all("hedge" in p for p in problems)


def test_a_short_unspecific_red_flag_is_rejected() -> None:
    bad = _good(red_flags=["It might be crowded.", "Could be noisy.", "Might not hold."])
    assert not card.validate(bad).ok


def test_a_red_flag_naming_a_real_finding_is_accepted() -> None:
    """The check must not reject genuine objections, only empty ones."""
    ok = _good(
        red_flags=[
            "Sprint 10 found the top 30 holding SPYL on Rs 49,839 of daily turnover, "
            "where the assumed fill price is fiction.",
            "The regime split showed Sharpe 0.49 against 1.48 across halves of the "
            "same history, so a full-sample number hides the variation.",
            "Every statutory cost rate comes from a secondary source (A-016) and "
            "impact is not modelled at all.",
        ]
    )
    assert card.validate(ok).ok


def test_too_few_red_flags_is_rejected() -> None:
    assert not card.validate(
        _good(red_flags=["Sprint 13 measured a +0.95 IC correlation in this cluster."])
    ).ok


def test_a_single_configuration_is_rejected() -> None:
    """PBO measures whether *choosing* between configurations picks noise. With
    one there is nothing to choose."""
    bad = _good(configurations=[{"feature": "low_volatility", "top_n": 30, "rebalance": 21}])
    assert any("PBO" in p for p in card.validate(bad).problems)


def test_a_card_without_a_source_is_rejected() -> None:
    """CLAUDE.md forbids inventing a source, and an uncited card poisons the
    one artefact the gate depends on."""
    assert any("source" in p for p in card.validate(_good(source_url="")).problems)


def test_a_vague_claim_is_rejected() -> None:
    assert any("falsifiable" in p for p in card.validate(_good(claim="Momentum works.")).problems)


def test_a_malformed_id_is_rejected() -> None:
    assert any("H-0001" in p for p in card.validate(_good(id="momentum-thing")).problems)


# --- persistence ---


def test_an_invalid_card_is_never_written(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a valid pre-registration"):
        card.write(_good(red_flags=["Markets change."]), tmp_path)
    assert not list(tmp_path.glob("*.yaml"))


def test_a_card_is_never_overwritten(tmp_path: Path) -> None:
    """A pre-registration that can be rewritten after its evidence exists is
    not a pre-registration."""
    card.write(_good(), tmp_path)
    with pytest.raises(FileExistsError, match="never rewritten"):
        card.write(_good(), tmp_path)


def test_ids_are_not_recycled(tmp_path: Path) -> None:
    """The trial ledger refers to ids; reusing one would silently merge two
    different claims in the audit trail."""
    card.write(_good(id="H-0001"), tmp_path)
    card.write(_good(id="H-0002"), tmp_path)
    assert card.next_id(tmp_path) == "H-0003"


def test_the_written_card_round_trips_as_yaml(tmp_path: Path) -> None:
    import yaml

    path = card.write(_good(), tmp_path)
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert loaded["status"] == "draft"
    assert loaded["holdout"]["status"] == "unread"
    assert len(loaded["red_flags"]) == 3


def test_a_new_card_is_a_draft_and_therefore_inert() -> None:
    """The gate acts on registered hypotheses. A draft cannot be validated by
    accident."""
    assert _good().status == "draft"
