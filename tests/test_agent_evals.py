"""Evals per role, the held-out wall, the canary and the floor (ADR-183)."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from eulerlab.agents import evals

REPO = Path(__file__).parents[1]
NOW = datetime(2026, 11, 13, 10, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("EULERLAB_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def test_every_role_has_about_twenty_cases_a_quarter_held_out() -> None:
    for role in evals.ROLES:
        public = evals.cases(role, root=REPO / evals.CASES)
        held = evals.cases(role, held_out=True, root=REPO / evals.CASES)
        assert len(public) + len(held) == 20 and len(held) == 5, role
        assert not {c["id"] for c in public} & {c["id"] for c in held}


@pytest.mark.parametrize("role", sorted(evals.SOLVERS))
def test_the_code_roles_pass_their_own_cases(role: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO)
    for held in (False, True):
        result = evals.score(role, evals.SOLVERS[role], held_out=held)
        assert result.share == 1.0, result.failures


def test_the_engineer_judge_refuses_a_fix_that_touches_a_protected_file() -> None:
    case = evals.cases("engineer", root=REPO / evals.CASES)[0]
    inside = {"changed": case["input"]["may_touch"][:1], "tests_pass": True}
    assert evals.judge("engineer", case, inside)
    assert not evals.judge("engineer", case, {**inside, "tests_pass": False})
    assert not evals.judge(
        "engineer", case, {"changed": ["src/eulerlab/gates.py"], "tests_pass": True}
    )


def test_no_agent_can_read_the_held_out_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    """Issue #149: the read tool refuses them, search does not index them, no worker opens them."""
    from eulerlab.agents import knowledge_index
    from eulerlab.assistant import tools

    monkeypatch.chdir(REPO)
    for role in evals.ROLES:
        path = f"config/agent_eval/heldout/{role}.yaml"
        assert (REPO / path).exists()
        assert "cannot be read" in tools.TOOLS["read_document"].run({"path": path})
        assert "cannot be read" in tools.TOOLS["read_document"].run({"path": f"docs/../{path}"})
    assert not any(src.startswith("config") for _, src, _ in knowledge_index.SOURCES)
    workers = sorted((REPO / "src/eulerlab/agents/workers").glob("*.py"))
    readers = [w.name for w in workers if "heldout" in w.read_text(encoding="utf-8")]
    # engineering names the files only to refuse any change to them (OPERATOR_OWNED)
    assert readers == ["engineering.py"]
    # Only the eval module itself asks for held-out cases.
    callers = []
    for module in (REPO / "src/eulerlab").rglob("*.py"):
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
            if isinstance(node, ast.keyword) and node.arg == "held_out" and module.name != "evals.py":
                callers.append(str(module.relative_to(REPO)))
    assert callers == []


def test_the_held_out_files_are_protected_from_agents() -> None:
    from eulerlab.agents import guardian
    from eulerlab.agents.workers import engineering

    for role in evals.ROLES:
        rel = f"config/agent_eval/heldout/{role}.yaml"
        assert Path(rel) in guardian.PROTECTED and rel in engineering.OPERATOR_OWNED


def _lazy(case: Any) -> str:
    return "ticket"


def test_a_self_change_that_is_not_better_is_rejected(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(REPO)
    row = evals.propose("on_call", "v2", "ticket everything", _lazy, current=evals.on_call,
                        by="on_call", now=NOW)  # fmt: skip
    assert row["event"] == "rejected" and row["held_out_new"] < row["held_out_old"] == 1.0
    assert [r["event"] for r in evals.history("on_call:v2")] == ["proposed", "rejected"]


def test_a_better_change_goes_through_a_week_of_canary_and_is_decided_by_the_numbers(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue #149: one proposed self-change through the canary, accepted or rejected by numbers."""
    monkeypatch.chdir(REPO)
    row = evals.propose("on_call", "v3", "map remedies by code", evals.on_call, current=_lazy,
                        by="on_call", now=NOW)  # fmt: skip
    assert row["event"] == "canary"
    with pytest.raises(ValueError, match="less than 7 days"):
        evals.conclude("on_call:v3", live_new=1.0, live_old=0.4, now=NOW + timedelta(days=3))
    done = evals.conclude("on_call:v3", live_new=1.0, live_old=0.4, now=NOW + timedelta(days=7))
    assert done["event"] == "accepted"
    evals.propose(
        "on_call", "v4", "same again", evals.on_call, current=_lazy, by="on_call", now=NOW
    )
    worse = evals.conclude("on_call:v4", live_new=0.5, live_old=0.9, now=NOW + timedelta(days=8))
    assert worse["event"] == "rejected" and worse["why"] == "worse than the old version live"
    with pytest.raises(ValueError, match="not in canary"):
        evals.conclude("on_call:v4", live_new=1.0, live_old=0.0, now=NOW + timedelta(days=9))


def test_a_baseline_is_stored_per_role(store: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO)
    public = evals.score("red_team", evals.red_team)
    held = evals.score("red_team", evals.red_team, held_out=True)
    evals.set_baseline("red_team", public, held, "current", now=NOW)
    assert evals.baselines()["red_team"] == {"version": "current", "public": 1.0, "held_out": 1.0,
                                             "cases": 20, "at": NOW.isoformat()}  # fmt: skip


def test_the_guardian_switches_off_a_role_below_its_floor(tmp_path: Path) -> None:
    from eulerlab.agents.spec import load_specs, read_settings

    specs = load_specs(REPO / "config" / "agents")
    assert evals.guard("on_call", 0.95, specs, root=tmp_path) == []
    off = evals.guard("on_call", 0.6, specs, root=tmp_path)
    assert off == ["data", "watchdog"]
    settings = read_settings(tmp_path)
    assert all(settings[n].enabled is False for n in off)
