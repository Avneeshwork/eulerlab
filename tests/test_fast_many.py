"""Many rules across cores, and the slow engine as referee (#167, ADR-195)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from eulerlab.intraday import rule_engine as engine
from eulerlab.research import fast_eval, lang
from test_research_autopilot import GAP_FADE, _gappy

RULES: list[engine.Rule] = [
    engine.RuleSpec.model_validate(GAP_FADE),
    engine.RuleSpec.model_validate({**GAP_FADE, "kind": "swing", "hold": 3, "side": "with"}),
    engine.RuleSpec.model_validate(
        {**GAP_FADE, "when": [{"signal": "gap", "op": ">=", "value": 0.03, "absolute": True}]}
    ),
    lang.Spec(shape="cross_section", kind="intraday", score="neg(gap)", top=2),
    lang.Spec(shape="event", kind="swing", hold=4, when="gt(gap, 0.02)", score="gap"),
]


def _fast() -> fast_eval.FastEngine:
    data = _gappy()
    return fast_eval.FastEngine(data, fast_eval.Store(engine.Engine(data)))


def _bytes(found: list[tuple[dict[str, Any], dict[Any, float]]]) -> str:
    return json.dumps([[s, {str(k): v for k, v in d.items()}] for s, d in found], default=str)


def test_many_processes_give_the_same_bytes_as_one() -> None:
    specs = RULES * 3
    one = fast_eval.screen_many(specs, _fast(), workers=1)
    many = fast_eval.screen_many(specs, _fast(), workers=2)
    assert _bytes(one) == _bytes(many)
    assert [s["fingerprint"] for s, _ in many] == [s.fingerprint() for s in specs]


def test_the_referee_finds_no_difference_on_engine_rules(tmp_path: Path) -> None:
    fast = _fast()
    found = [s for s, _ in fast_eval.screen_many(RULES, fast)]
    out = fast_eval.referee(RULES, found, fast.data, share=1.0, path=tmp_path / "p.jsonl")
    assert out == {"checked": 3, "mismatched": 0}  # the two v2 rules have no slow path
    assert not (tmp_path / "p.jsonl").exists()


def test_the_referee_records_a_difference(tmp_path: Path) -> None:
    fast = _fast()
    found = [dict(s) for s, _ in fast_eval.screen_many(RULES[:1], fast)]
    found[0]["count"] = found[0]["count"] + 1
    out = fast_eval.referee(RULES[:1], found, fast.data, share=1.0, path=tmp_path / "p.jsonl")
    assert out["mismatched"] == 1
    row = json.loads((tmp_path / "p.jsonl").read_text().splitlines()[0])
    assert row["diff"]["count"][0] == row["diff"]["count"][1] + 1


def test_a_trade_costs_its_fills_once() -> None:
    from eulerlab.intraday import screen_common as sc

    fast = _fast()
    fast.screen(RULES[0])
    before = sc.intraday_fee.cache_info()
    trades = fast.pieces(RULES[0])
    first = [t.costs for t in trades]
    again = [t.costs for t in trades]
    assert first == again
    assert sc.intraday_fee.cache_info().misses == before.misses  # every fill already priced


@pytest.mark.parametrize("workers", [1, 2])
def test_evaluate_records_the_same_rows_either_way(
    workers: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    rules = Path(__file__).parents[1] / "config" / "constitution.yaml"
    (tmp_path / "config" / "constitution.yaml").write_text(rules.read_text())
    monkeypatch.setenv("EULERLAB_DATA_DIR", str(tmp_path / "data"))
    found = fast_eval.evaluate(RULES * 2, _fast(), asked_by="t", record=False, workers=workers)
    assert [f["fingerprint"] for f in found] == [s.fingerprint() for s in RULES * 2]
