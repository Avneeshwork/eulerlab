"""The promotion gate: it must promote, and it must kill.

A gate only ever seen killing things is as untested as one only ever seen
passing them. Both directions are exercised here, plus every individual rule
in isolation — because a gate that fails for the wrong reason gives the right
answer today and the wrong one tomorrow.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eulerlab import gates
from eulerlab.validation import ledger


def _passing_pack() -> dict[str, Any]:
    """Evidence that clears every threshold in the mandate."""
    return {
        "hypothesis": "H-TEST",
        "configurations": [
            {"configuration": "c1", "full_sample_sharpe": 1.5, "deflated_sharpe_probability": 0.99}
        ],
        "search": {
            "method": "families",
            "families": {"strategies": 70, "families": 28, "sigma": 0.48, "bar": 0.99},
            "romano_wolf": {
                "passed": True,
                "alpha": 0.05,
                "candidate_sharpe": 1.4,
                "critical_sharpe": 0.94,
                "strategies": 55,
            },
        },
        "pbo": {"value": 0.10, "verdict": "low"},
        "min_backtest_length_years": 2.0,
        "available_years": 10.0,
        "stress_tests": [
            {"test": "costs x2", "base_sharpe": 1.5, "stressed_sharpe": 1.4, "survives": True},
            {
                "test": "drop best 5 names",
                "base_sharpe": 1.5,
                "stressed_sharpe": 1.3,
                "survives": True,
            },
            {
                "test": "regime: first half",
                "base_sharpe": 1.5,
                "stressed_sharpe": 1.2,
                "survives": True,
            },
            {
                "test": "regime: second half",
                "base_sharpe": 1.5,
                "stressed_sharpe": 1.4,
                "survives": True,
            },
        ],
    }


MANDATE = gates.load_mandate()


def _decide(pack: dict[str, Any]) -> gates.Decision:
    """Statistical + robustness rules only; process rules need real files."""
    decision = gates.Decision(hypothesis="H-TEST")
    decision.findings.extend(gates._check_statistics(pack, MANDATE["statistical"]))
    decision.findings.extend(gates._check_robustness(pack, MANDATE["robustness"]))
    return decision


# --- the gate can say yes ---


def test_evidence_clearing_every_threshold_is_promoted() -> None:
    """Without this the gate might be killing everything for a trivial reason."""
    decision = _decide(_passing_pack())
    assert decision.verdict is gates.Verdict.PROMOTE, [f.detail for f in decision.failures]


# --- and every rule can say no, one at a time ---


def test_a_low_deflated_sharpe_kills() -> None:
    pack = _passing_pack()
    pack["configurations"][0]["deflated_sharpe_probability"] = 0.5
    assert _decide(pack).verdict is gates.Verdict.KILL


def test_a_high_pbo_kills() -> None:
    pack = _passing_pack()
    pack["pbo"]["value"] = 0.6
    assert _decide(pack).verdict is gates.Verdict.KILL


def test_too_little_history_kills() -> None:
    pack = _passing_pack()
    pack["available_years"] = 2.1  # only 1.05x the 2.0 needed
    assert _decide(pack).verdict is gates.Verdict.KILL


def test_collapsing_under_double_costs_kills() -> None:
    pack = _passing_pack()
    pack["stress_tests"][0]["stressed_sharpe"] = 0.3  # 20% retained
    assert _decide(pack).verdict is gates.Verdict.KILL


def test_depending_on_a_few_names_kills() -> None:
    pack = _passing_pack()
    pack["stress_tests"][1]["stressed_sharpe"] = 0.2
    assert _decide(pack).verdict is gates.Verdict.KILL


def test_working_in_only_one_regime_kills() -> None:
    """The case a full-sample Sharpe hides, and the one Sprints 10 and 11 hit."""
    pack = _passing_pack()
    pack["stress_tests"][2]["stressed_sharpe"] = 0.1  # first half retains 7%
    assert _decide(pack).verdict is gates.Verdict.KILL


def test_any_negative_stress_kills_regardless_of_retention() -> None:
    pack = _passing_pack()
    pack["stress_tests"][3]["survives"] = False
    assert _decide(pack).verdict is gates.Verdict.KILL


# --- the default is no ---


def test_missing_statistics_kill_rather_than_being_skipped() -> None:
    """A check that cannot be evaluated fails. Wrongly killing a good strategy
    costs an opportunity; wrongly promoting a bad one costs money."""
    assert _decide({"hypothesis": "x"}).verdict is gates.Verdict.KILL


def test_missing_stress_tests_kill() -> None:
    pack = _passing_pack()
    del pack["stress_tests"]
    decision = _decide(pack)
    assert decision.verdict is gates.Verdict.KILL
    assert any("no stress tests" in f.detail for f in decision.failures)


def test_an_empty_pack_kills() -> None:
    assert _decide({}).verdict is gates.Verdict.KILL


# --- process rules ---


def test_an_altered_evidence_pack_is_detected(tmp_path: Path) -> None:
    """A pack edited after the run must not pass as evidence."""
    pack = _passing_pack()
    body = json.dumps(pack, indent=2, sort_keys=True)
    pack["signature"] = ledger.compute_hash({"body": body})
    spec = tmp_path / "H-TEST.yaml"
    spec.write_text("id: H-TEST\ntitle: t\nclaim: c\nconfigurations: [{a: 1}]\nred_flags: [f]\n")

    clean = gates.decide(pack, hypothesis_path=spec, mandate=MANDATE)
    assert not any(f.rule == "evidence signature" and not f.passed for f in clean.findings)

    pack["pbo"]["value"] = 0.01  # tamper after signing
    tampered = gates.decide(pack, hypothesis_path=spec, mandate=MANDATE)
    assert any(f.rule == "evidence signature" and not f.passed for f in tampered.findings)


def test_an_unregistered_hypothesis_kills(tmp_path: Path) -> None:
    decision = gates.decide(
        _passing_pack(), hypothesis_path=tmp_path / "absent.yaml", mandate=MANDATE
    )
    assert any(f.rule == "pre-registration" and not f.passed for f in decision.findings)


def test_a_hypothesis_without_red_flags_kills(tmp_path: Path) -> None:
    """Red flags declared in advance are what make a hypothesis a claim rather
    than a description of what happened."""
    spec = tmp_path / "H.yaml"
    spec.write_text("id: H\ntitle: t\nclaim: c\nconfigurations: [{a: 1}]\nred_flags: []\n")
    decision = gates.decide(_passing_pack(), hypothesis_path=spec, mandate=MANDATE)
    assert any(f.rule == "pre-registration" and not f.passed for f in decision.findings)


# --- the holdout ---


def test_the_holdout_is_not_read_for_a_killed_strategy(tmp_path: Path) -> None:
    """Reading it to 'check something' is exactly what CLAUDE.md forbids."""
    killed = _decide({})
    allowed, reason = gates.may_read_holdout(killed, mandate=MANDATE, path=tmp_path / "h.jsonl")
    assert not allowed
    assert "KILL" in reason


def test_the_holdout_may_be_read_once_after_a_pass(tmp_path: Path) -> None:
    path = tmp_path / "h.jsonl"
    passing = _decide(_passing_pack())
    allowed, _ = gates.may_read_holdout(passing, mandate=MANDATE, path=path)
    assert allowed

    gates.record_holdout_read("H-TEST", authorised_by="operator", path=path)
    allowed_again, reason = gates.may_read_holdout(passing, mandate=MANDATE, path=path)
    assert not allowed_again
    assert "already been read" in reason


def test_a_recorded_read_cannot_be_unspent(tmp_path: Path) -> None:
    """There is deliberately no function to undo it. The holdout cannot be
    regenerated, so a second read does not produce weaker evidence — none."""
    path = tmp_path / "h.jsonl"
    gates.record_holdout_read("H-TEST", authorised_by="operator", path=path)
    assert len(gates.holdout_reads(path)) == 1
    assert not hasattr(gates, "clear_holdout_reads")
    assert not hasattr(gates, "reset_holdout")


# --- the mandate owns the numbers, not this file ---


def test_no_threshold_is_hardcoded_in_the_gate() -> None:
    """Changing what the gate demands must mean editing the operator's YAML,
    visibly, rather than a constant buried in logic."""
    source = Path("src/eulerlab/gates.py").read_text(encoding="utf-8")
    for value in ("0.95", "0.25", "3.0", "1.5", "0.60", "0.50"):
        assert f"= {value}" not in source, f"threshold {value} hardcoded in gates.py"


def test_the_mandate_declares_its_owner() -> None:
    assert MANDATE["owner"] == "operator"
    assert MANDATE["version"] >= 1


# --- the search correction (ADR-108) ---


def test_a_pack_using_the_old_ledger_count_kills() -> None:
    pack = _passing_pack()
    pack["search"]["method"] = None
    decision = _decide(pack)
    assert decision.verdict is gates.Verdict.KILL
    assert "search correction" in [f.rule for f in decision.failures]


def test_failing_romano_wolf_kills() -> None:
    pack = _passing_pack()
    pack["search"]["romano_wolf"]["passed"] = False
    decision = _decide(pack)
    assert decision.verdict is gates.Verdict.KILL
    assert [f.rule for f in decision.failures] == ["romano-wolf"]


def test_a_looser_romano_wolf_level_than_the_mandate_kills() -> None:
    pack = _passing_pack()
    pack["search"]["romano_wolf"]["alpha"] = 0.10
    assert _decide(pack).verdict is gates.Verdict.KILL


def test_a_missing_romano_wolf_test_kills() -> None:
    pack = _passing_pack()
    del pack["search"]["romano_wolf"]
    assert _decide(pack).verdict is gates.Verdict.KILL


SIMPLE = {**MANDATE, "mode": "simple"}


def _simple_pack(
    first: float,
    second: float,
    doubled: float,
    psr: float = 0.99,
    years: tuple[float, ...] = (0.1, 0.05, -0.02),
) -> dict[str, object]:
    return {
        "configurations": [{"full_sample_sharpe": 1.0, "probabilistic_sharpe": psr}],
        "stress_tests": [
            {"test": "regime: first half", "stressed_sharpe": first},
            {"test": "regime: second half", "stressed_sharpe": second},
            {"test": "costs x2", "stressed_sharpe": doubled},
        ],
        "stability": {
            str(2021 + i): {"days": 250.0, "net_return": r, "sharpe": 1.0}
            for i, r in enumerate(years)
        },
    }


def test_simple_mode_passes_positive_halves_and_double_costs() -> None:
    found = gates._check_simple(_simple_pack(0.4, 0.2, 0.1), SIMPLE["simple"])
    assert all(f.passed for f in found) and len(found) == 6


def test_simple_mode_kills_a_negative_half_or_double_costs() -> None:
    assert not all(
        f.passed for f in gates._check_simple(_simple_pack(0.4, -0.1, 0.1), SIMPLE["simple"])
    )
    assert not all(
        f.passed for f in gates._check_simple(_simple_pack(0.4, 0.2, -0.1), SIMPLE["simple"])
    )


def test_simple_mode_still_kills_missing_evidence() -> None:
    assert not any(f.passed for f in gates._check_simple({}, SIMPLE["simple"]))


def test_simple_mode_keeps_the_process_rules(tmp_path: Path) -> None:
    decision = gates.decide(
        _simple_pack(1.0, 1.0, 1.0), hypothesis_path=tmp_path / "absent.yaml", mandate=SIMPLE
    )
    assert decision.verdict is gates.Verdict.KILL
    assert any(f.rule == "pre-registration" and not f.passed for f in decision.findings)


def test_simple_mode_kills_a_low_probabilistic_sharpe() -> None:
    found = gates._check_simple(_simple_pack(0.4, 0.2, 0.1, psr=0.80), SIMPLE["simple"])
    assert [f.rule for f in found if not f.passed] == ["probabilistic sharpe"]


def test_simple_mode_kills_too_few_positive_years() -> None:
    pack = _simple_pack(0.4, 0.2, 0.1, years=(0.1, -0.05, -0.02))
    found = gates._check_simple(pack, SIMPLE["simple"])
    assert [f.rule for f in found if not f.passed] == ["stability: positive years"]


def test_short_years_do_not_count_toward_stability() -> None:
    pack = _simple_pack(0.4, 0.2, 0.1, years=(0.1, 0.05))
    stability = pack["stability"]
    assert isinstance(stability, dict)
    stability["2024"] = {"days": 10.0, "net_return": -0.5, "sharpe": -1.0}
    assert all(f.passed for f in gates._check_simple(pack, SIMPLE["simple"]))
