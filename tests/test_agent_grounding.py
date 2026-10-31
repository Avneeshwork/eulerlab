"""The grounding check, the knowledge agent's retry, the brief's dropped commentary, and agent-eval (ADR-088)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from eulerlab.agents import evaluate, grounding, runtime
from eulerlab.agents.spec import AgentSpec, Effective, all_effective, effective


def test_supported_numbers_pass_and_invented_ones_are_named() -> None:
    evidence = ["19 trials are logged. The noise bar is Sharpe 1.875 over 2,869 days; share 0.12"]
    good = grounding.check("Sharpe bar 1.88, 19 trials, 2,869 days, 12% share.", evidence)
    assert good.ok and good.checked == 4
    bad = grounding.check("The bar is 2.41 after 312 trials.", evidence)
    assert bad.unsupported == ["2.41", "312"]


def test_ids_and_paths_must_be_in_the_evidence_and_sources_are_not_checked() -> None:
    evidence = ["docs/DECISIONS/ADR-084-paper-agent-stops-at-drafts.md"]
    assert grounding.check("ADR-084 says so.\n\nSources:\n- ADR-999 docs/x.md", evidence).ok
    assert grounding.check("See ADR-091.", evidence).unsupported == ["ADR-091"]


def test_single_digits_and_question_numbers_are_not_held_against_the_answer() -> None:
    assert grounding.check("Two steps: 1 and 2.", []).ok
    assert grounding.check("Since 2019, nothing.", [], question="what happened in 2019?").ok


def test_the_prompt_version_changes_with_the_prompt() -> None:
    assert grounding.prompt_version("a") != grounding.prompt_version("b")
    assert len(grounding.prompt_version("a")) == 12


# --- the knowledge agent with a fake model ---


def _fake_chat(
    monkeypatch: pytest.MonkeyPatch, replies: list[str], evidence: str
) -> list[list[dict[str, Any]]]:
    from eulerlab.assistant import chat

    seen: list[list[dict[str, Any]]] = []

    class Chosen:
        name = "fake"
        model = "m"

    def ask(messages: list[dict[str, Any]], **_: Any) -> chat.Answer:
        seen.append(list(messages))
        text = replies[min(len(seen) - 1, len(replies) - 1)]
        return chat.Answer(
            text, "fake", "m", "host", [{"tool": "search_knowledge", "arguments": "{}"}], [evidence]
        )

    monkeypatch.setattr(chat, "ask", ask)
    monkeypatch.setattr(chat, "selected_provider", lambda name=None: Chosen())
    monkeypatch.setattr(runtime, "resolve_provider", lambda wanted="": "fake")
    monkeypatch.setattr(
        "eulerlab.agents.workers.knowledge.resolve_provider", lambda wanted="": "fake"
    )
    return seen


def _knowledge(tmp_path: Path) -> dict[str, Effective]:
    spec = all_effective()["knowledge"].spec
    return {"knowledge": effective(spec, None)}


def test_a_grounded_answer_goes_through_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _fake_chat(monkeypatch, ["The bar is 1.88."], "noise bar 1.88")
    out = runtime.run(
        "knowledge", args={"question": "bar?"}, root=tmp_path, agents=_knowledge(tmp_path)
    )
    assert out.data["answer"].startswith("The bar is 1.88.") and len(seen) == 1
    assert out.data["grounding"]["retried"] is False and out.prompts


def test_an_invented_figure_is_sent_back_once_then_fixed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _fake_chat(monkeypatch, ["The bar is 2.41.", "The bar is 1.88."], "noise bar 1.88")
    out = runtime.run(
        "knowledge", args={"question": "bar?"}, root=tmp_path, agents=_knowledge(tmp_path)
    )
    assert len(seen) == 2 and "2.41" in seen[1][-1]["content"]
    assert out.data["answer"].startswith("The bar is 1.88.")
    assert out.data["first_answer"] == "The bar is 2.41."


def test_a_second_invented_figure_is_withheld_as_not_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_chat(monkeypatch, ["The bar is 2.41.", "It is 3.10."], "noise bar 1.88")
    out = runtime.run(
        "knowledge", args={"question": "bar?"}, root=tmp_path, agents=_knowledge(tmp_path)
    )
    assert out.data["answer"].startswith("Not held") and "3.10" in out.data["answer"]
    assert out.data["grounding"]["withheld"] is True


# --- the market brief drops commentary that invents a number ---


def test_the_brief_drops_commentary_with_a_number_not_in_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab.agents.workers import market_brief

    monkeypatch.setattr(market_brief, "_context", lambda notes: {})
    monkeypatch.setattr(market_brief, "_world", lambda notes, fetch: [])
    monkeypatch.setattr(market_brief, "_events", lambda day: [])
    monkeypatch.setattr(market_brief, "_books", list)
    spec = AgentSpec(
        name="market_brief",
        title="Market brief",
        job="a brief for the test",
        worker="eulerlab.agents.workers.market_brief",
        uses_model=True,
        daily_requests=3,
    )

    def asker(system: str, user: str, accept: object) -> str:
        return "Nifty should rise 3.4% this week."

    out = runtime.run(
        "market_brief",
        root=tmp_path,
        agents={"market_brief": effective(spec, None)},
        asker=asker,
        now=datetime(2026, 10, 29, 3, 0, tzinfo=UTC),
    )
    assert "COMMENTARY" not in out.data["text"]
    assert any("commentary dropped" in n for n in out.notes)


# --- agent-eval ---


def test_the_skeptic_catches_every_planted_fake_and_passes_a_clean_curve() -> None:
    from eulerlab.agents.workers import skeptic

    score = evaluate.score_skeptic()
    assert score.passed == score.cases == 10
    days = [date(2018, 1, 1) + timedelta(days=i) for i in range(1500)]
    values = [100.0 * (1.0003**i) * (1 + 0.002 * ((i % 7) - 3) / 3) for i in range(1500)]
    found = skeptic.attacks(days, values, {})
    assert not [i for i in skeptic.verdicts(found) if i.severity == "critical"]


def _output(
    answer: str, unsupported: list[str] | None = None, withheld: bool = False
) -> runtime.Output:
    return runtime.Output(
        agent="knowledge",
        run_id="r",
        started="s",
        finished="f",
        status="ok",
        summary=answer[:50],
        data={
            "answer": answer,
            "grounding": {"unsupported": unsupported or [], "withheld": withheld},
        },
    )


def test_knowledge_scoring_counts_not_held_and_made_up_figures(tmp_path: Path) -> None:
    cases = tmp_path / "k.yaml"
    cases.write_text(
        "cases:\n"
        "  - {id: a, question: 'bar?', expect: ['1.88']}\n"
        "  - {id: b, question: 'latency?', not_held: true}\n"
        "  - {id: c, question: 'trials?', expect: ['19']}\n"
    )
    answers = {
        "bar?": _output("The bar is 1.88."),
        "latency?": _output("Not held: nothing times orders."),
        "trials?": _output("312 trials.", unsupported=["312"]),
    }
    score = evaluate.score_knowledge(cases, ask=lambda q: answers[q])
    assert (score.cases, score.passed, score.made_up) == (3, 2, 1)


def test_a_made_up_figure_switches_the_agent_off(tmp_path: Path) -> None:
    said = evaluate.enforce(
        evaluate.Score("knowledge", cases=3, passed=2, made_up=1), root=tmp_path
    )
    assert "switched off" in said
    assert all_effective(tmp_path)["knowledge"].enabled is False
    assert evaluate.enforce(evaluate.Score("knowledge", cases=3, passed=3), root=tmp_path) == ""


def test_the_shipped_test_set_loads() -> None:
    import yaml

    spec = yaml.safe_load(evaluate.CASES.read_text())
    ids = [c["id"] for c in spec["cases"]]
    assert len(ids) == len(set(ids)) >= 12
    assert any(c.get("not_held") for c in spec["cases"])
