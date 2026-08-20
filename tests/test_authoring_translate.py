"""Turning a description into a strategy — and refusing what does not validate.

Nothing here calls a language model. The model is a source of *text*, and what
matters is what happens to that text afterwards, which is entirely local. Every
test below feeds a hand-written reply of the kind models actually produce.
"""

from __future__ import annotations

import pytest

from eulerlab.authoring.sandbox import EXAMPLE, UnsafeStrategy
from eulerlab.authoring.translate import (
    COMPOSED_SYSTEM,
    from_code,
    from_spec,
    library_summary,
    parse_composed,
)
from eulerlab.backtest.strategies import RankAndHold
from eulerlab.features.library import BY_NAME


def test_a_clean_spec_parses() -> None:
    spec, warnings = parse_composed(
        '{"feature": "momentum_12_1", "top_n": 25, "rebalance": 42, "min_turnover": 0}'
    )
    assert spec == {
        "feature": "momentum_12_1",
        "top_n": 25,
        "rebalance": 42,
        "min_turnover": 0.0,
    }
    assert warnings == []


def test_a_markdown_fence_is_tolerated() -> None:
    """Models add fences despite being told not to. Rejecting a reply that is
    correct apart from three backticks makes the feature feel broken for a
    cosmetic reason."""
    spec, _ = parse_composed('```json\n{"feature": "reversal_1m", "top_n": 10}\n```')
    assert spec["feature"] == "reversal_1m"


def test_a_leading_pleasantry_is_tolerated() -> None:
    spec, _ = parse_composed('Sure! Here is the spec:\n{"feature": "small_size", "top_n": 20}')
    assert spec["feature"] == "small_size"


def test_a_hallucinated_feature_is_refused_by_name() -> None:
    """The failure mode that matters. A model inventing `momentum_9_2` must not
    be silently mapped to something similar."""
    with pytest.raises(UnsafeStrategy, match="does not exist"):
        parse_composed('{"feature": "momentum_9_2", "top_n": 30}')


def test_the_refusal_lists_what_does_exist() -> None:
    with pytest.raises(UnsafeStrategy, match="momentum_12_1"):
        parse_composed('{"feature": "sharpe_momentum", "top_n": 30}')


def test_absurd_numbers_are_clamped_and_reported() -> None:
    """Clamped rather than rejected — the feature choice is the substance, and
    a silly top_n should not throw away a usable draft. But it is reported, so
    nobody thinks they got what they asked for."""
    spec, warnings = parse_composed('{"feature": "low_volatility", "top_n": 5000, "rebalance": 1}')
    assert spec["top_n"] == 100
    assert spec["rebalance"] == 5
    assert len(warnings) == 2


def test_prose_instead_of_json_is_refused() -> None:
    with pytest.raises(UnsafeStrategy, match="did not return a JSON object"):
        parse_composed("I think momentum would work well here.")


def test_broken_json_is_refused_with_the_parse_error() -> None:
    with pytest.raises(UnsafeStrategy, match="did not parse"):
        parse_composed('{"feature": "momentum_12_1", "top_n": }')


# --- the no-model paths -----------------------------------------------------


def test_a_spec_becomes_a_rank_and_hold() -> None:
    draft = from_spec("low_volatility", top_n=15, rebalance=63)
    built = draft.build()
    assert isinstance(built, RankAndHold)
    assert "low_volatility" in draft.label()


def test_an_unknown_feature_is_refused_without_a_model() -> None:
    with pytest.raises(UnsafeStrategy, match="unknown feature"):
        from_spec("not_a_feature")


def test_pasted_code_gets_the_same_validation_as_generated_code() -> None:
    """Who wrote it changes nothing about what it may reach."""
    assert from_code(EXAMPLE).build()
    with pytest.raises(UnsafeStrategy):
        from_code("import os\ndef weights(view):\n    return {}")


# --- the prompt is built from the real library ------------------------------


def test_the_prompt_lists_every_real_feature_and_no_others() -> None:
    """A prompt with a stale library invites exactly the hallucination the
    validator then rejects, which wastes the operator's time."""
    summary = library_summary()
    for name in BY_NAME:
        assert name in summary
    assert summary.count("\n") + 1 == len(BY_NAME)


def test_the_prompt_states_the_orientation_rule() -> None:
    """`low_volatility` is negated volatility. A model that misses this picks
    the most volatile names while believing it picked the calmest."""
    assert "HIGHER IS BETTER" in COMPOSED_SYSTEM
    assert "low_volatility" in COMPOSED_SYSTEM


def test_the_prompt_says_the_book_is_long_only() -> None:
    assert "cannot short" in COMPOSED_SYSTEM
