"""Nine roles and the model routing table (ADR-181)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from eulerlab.agents import roles, runtime
from eulerlab.agents.spec import AgentSpec, load_specs

NOW = datetime(2026, 11, 13, 10, tzinfo=UTC)


def test_every_committed_agent_has_one_of_nine_roles() -> None:
    specs = load_specs()
    assert len(roles.ROLES) == 9
    assert {name: s.role for name, s in specs.items() if s.role not in roles.ROLES} == {}
    used = {s.role for s in specs.values()}
    assert used == set(roles.ROLES) - {"evaluator"} | {"evaluator"} & used
    assert {"engineer", "generator", "red_team", "on_call", "chief_of_staff"} <= used


def test_an_unknown_role_is_refused() -> None:
    with pytest.raises(ValueError, match="not one of"):
        AgentSpec(
            name="xx", title="xxx", job="a job of ten letters", worker="eulerlab.agents.workers.lab",
            role="trader",
        )  # fmt: skip


def test_the_constitution_routes_each_tier() -> None:
    assert roles.provider_for("engineer") == "claude-opus"
    assert roles.provider_for("generator") == "claude-sonnet"
    assert roles.provider_for("scout") == "groq"
    assert roles.provider_for("evaluator") == "none"


def test_an_agent_without_its_own_provider_follows_its_role() -> None:
    spec = AgentSpec(
        name="xx", title="xxx", job="a job of ten letters", worker="eulerlab.agents.workers.lab",
        role="on_call",
    )  # fmt: skip
    assert runtime.routed_provider(spec) == "claude-sonnet"
    assert runtime.routed_provider(spec.model_copy(update={"provider": "groq"})) == "groq"
    assert runtime.routed_provider(spec.model_copy(update={"role": "evaluator"})) == ""


def test_no_committed_agent_was_moved_to_a_dearer_model_by_the_table() -> None:
    """An agent left to the table lands where it was before: the free default, groq."""
    specs = load_specs()
    routed = {runtime.routed_provider(s) for s in specs.values() if s.uses_model and not s.provider}
    assert routed <= {"groq"}
    odd = roles.exceptions(dict(specs))
    assert odd["skeptic"] == {"role": "red_team", "own": "groq", "routed": "claude-opus"}
    assert "autopilot" not in odd and "engineering" not in odd


def test_spend_is_counted_per_role(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from eulerlab.llm import usage

    log = tmp_path / "usage.jsonl"
    rows = [
        {"at": "2026-11-10T10:00:00+00:00", "agent": "autopilot", "provider": "claude-sonnet",
         "input_tokens": 1000, "output_tokens": 500},
        {"at": "2026-11-11T10:00:00+00:00", "agent": "watchdog", "provider": "groq",
         "input_tokens": 1000, "output_tokens": 500},
        {"at": "2026-09-01T10:00:00+00:00", "agent": "autopilot", "provider": "claude-sonnet",
         "input_tokens": 1000, "output_tokens": 500},
    ]  # fmt: skip
    log.write_text("".join(json.dumps(r) + "\n" for r in rows))
    monkeypatch.setattr(usage, "LOG", log)
    out = roles.spend(dict(load_specs()), NOW)
    assert out["generator"]["requests"] == 1 and out["on_call"]["requests"] == 1
    assert out["on_call"]["inr"] == 0.0, "Groq is free"
    assert "autopilot" in out["generator"]["agents"]
