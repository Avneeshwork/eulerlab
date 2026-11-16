"""The idea key: one key per idea, whatever its numbers (ADR-209)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from eulerlab.intraday import rule_engine as engine
from eulerlab.research import lang, novelty

FADE = {
    "kind": "intraday",
    "side": "against",
    "direction_of": {"signal": "gap"},
    "when": [
        {"signal": "results_morning"},
        {"signal": "gap", "op": ">=", "value": 0.03, "absolute": True},
    ],
    "rank_by": {"signal": "gap", "absolute": True, "order": "desc"},
}


def _key(body: Mapping[str, Any]) -> str:
    return novelty.rule_key(engine.RuleSpec.model_validate(body))


def test_numbers_order_and_ranking_do_not_make_a_new_idea() -> None:
    base = _key(FADE)
    tuned = {
        **FADE,
        "when": [
            {"signal": "gap", "op": ">", "value": 0.05, "absolute": True},
            {"signal": "results_morning"},
        ],
        "rank_by": {"signal": "value_ratio", "lag": 1, "order": "asc"},
    }
    assert _key(tuned) == base


def test_side_direction_and_fields_do_make_a_new_idea() -> None:
    base = _key(FADE)
    assert _key({**FADE, "side": "with"}) != base
    fall = {
        **FADE,
        "when": [{"signal": "results_morning"}, {"signal": "gap", "op": "<=", "value": -0.03}],
    }
    assert _key(fall) != base
    no_abs = {
        **FADE,
        "when": [{"signal": "results_morning"}, {"signal": "gap", "op": ">=", "value": 0.03}],
    }
    assert _key(no_abs) != base
    more = {
        **FADE,
        "when": [*FADE["when"], {"signal": "value_ratio", "lag": 1, "op": ">=", "value": 2.0}],
    }
    assert _key(more) != base


def test_lag_window_and_hold_are_numbers_too() -> None:
    swing = {
        "kind": "swing",
        "hold": 5,
        "side": "long",
        "when": [{"signal": "ret", "lag": 1, "n": 5, "op": "<=", "value": -0.08}],
        "rank_by": {"signal": "ret", "lag": 1, "n": 5, "order": "asc"},
    }
    other = {
        **swing,
        "hold": 20,
        "when": [{"signal": "ret", "lag": 2, "n": 20, "op": "<", "value": -0.12}],
    }
    assert _key(swing) == _key(other)
    assert _key({**swing, "kind": "intraday", "hold": 0}) != _key(swing)


def test_a_card_in_the_old_language_matches_its_v2_form() -> None:
    rule = engine.RuleSpec.model_validate(FADE)
    assert novelty.rule_key(lang.from_rule(rule)) == novelty.rule_key(rule)


def test_a_cross_section_rule_is_its_score_and_rank_only_reorders() -> None:
    def spec(score: str, top: int = 10) -> lang.Spec:
        return lang.Spec(shape="cross_section", kind="intraday", side="long", score=score, top=top)

    assert novelty.rule_key(spec("rank(delay(ret(5), 1))")) == novelty.rule_key(
        spec("delay(ret(20), 2)", top=5)
    )
    assert novelty.rule_key(spec("neg(delay(ret(5), 1))")) != novelty.rule_key(
        spec("delay(ret(5), 1)")
    )


def test_lab_formulas_other_windows_and_exact_reverses_are_repeats() -> None:
    seen = novelty.Seen()
    seen.add_feature("formula:neg(ts_std(ret(1), 63))", "lab")
    assert seen.feature("formula:neg(ts_std(ret(1), 126))") == "lab"
    assert seen.feature("formula:ts_std(ret(1), 63)") == "lab"  # the same IC, upside down
    assert seen.feature("formula:ts_std(ret(1), 21)") is None  # high volatility: another bet
    assert seen.feature("formula:neg(ts_mean(ret(1), 63))") is None
    assert novelty.formula_key("reversal_1m") == novelty.formula_key("formula:neg(ret(5))")


def test_seen_reads_cards_reference_rules_screens_and_memory(tmp_path: Path) -> None:
    card = {"id": "H-0001", "engine": {**FADE, "side": "with"}}
    (tmp_path / "H-0001.yaml").write_text(yaml.safe_dump(card))
    ranked = {
        "id": "H-0002",
        "configurations": [{"shape": "rank_and_hold", "feature": "momentum_12_1"}],
    }
    (tmp_path / "H-0002.yaml").write_text(yaml.safe_dump(ranked))
    swing = {
        "kind": "swing",
        "hold": 10,
        "side": "long",
        "when": [{"signal": "promoter_buy", "op": ">", "value": 0.0}],
        "rank_by": {"signal": "promoter_buy"},
    }
    seen = novelty.seen(
        tmp_path,
        screens=[{"id": "abc", "spec": swing}, {"id": "old"}],
        features=["formula:div(close, ts_max(close, 126))"],
    )
    assert seen.rule(engine.RuleSpec.model_validate({**FADE, "side": "with"})) == "H-0001"
    assert seen.rule(engine.reference_specs()["H-0168"]) == "H-0168"
    assert seen.rule(engine.RuleSpec.model_validate({**swing, "hold": 30})) == "screen abc"
    assert seen.feature("formula:div(close, ts_max(close, 252))") == "the idea lab's memory"
    assert seen.feature("momentum_12_1") == "H-0002"
