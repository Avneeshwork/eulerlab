"""The research loop (#162, ADR-190): tools the model calls, screens cut at the discovery end,
and the autopilot writing its cards after looking."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from eulerlab.agents import boundaries, runtime
from eulerlab.agents.spec import AgentSpec, effective
from eulerlab.agents.workers import autopilot as writer
from eulerlab.assistant import chat
from eulerlab.intraday import rule_engine as engine
from eulerlab.llm import trace
from eulerlab.llm.client import Provider
from eulerlab.research import agent_tools, experiments
from test_research_autopilot import GAP_FADE, _data, _gappy

NOW = datetime(2026, 11, 14, 12, tzinfo=UTC)
END = date(2023, 12, 31)
GROQ = Provider(
    name="groq", base_url="https://api.groq.com/openai/v1", model="openai/gpt-oss-120b", free=True
)


@pytest.fixture
def folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "hypotheses").mkdir()
    (tmp_path / "research" / "papers").mkdir(parents=True)
    (tmp_path / "config").mkdir()
    rules = Path(__file__).parents[1] / "config" / "constitution.yaml"
    (tmp_path / "config" / "constitution.yaml").write_text(rules.read_text())
    models = Path(__file__).parents[1] / "config" / "llm.yaml"
    (tmp_path / "config" / "llm.yaml").write_text(models.read_text())
    monkeypatch.setenv("EULERLAB_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def _tools(**extra: Any) -> agent_tools.ResearchTools:
    return agent_tools.ResearchTools(
        asked_by="autopilot",
        discovery_end=END,
        now=NOW,
        engine=lambda end: engine.Engine(_gappy()),
        **extra,
    )


# --- the tools ----------------------------------------------------------------------------


def test_a_screen_is_recorded_and_counted(folder: Path) -> None:
    tools = _tools()
    text = tools.call("screen_rule", json.dumps({"spec": GAP_FADE}))
    assert "net_sharpe" in text and "discovery only" in text
    (row,) = experiments.rows(purpose="screen")
    assert row["asked_by"] == "autopilot"
    assert row["metrics"]["explore"] is True
    assert row["family"] == "intraday:gap"
    assert len(tools.screened) == 1


def test_the_same_rule_is_not_screened_twice(folder: Path) -> None:
    _tools().call("screen_rule", json.dumps({"spec": GAP_FADE}))
    again = _tools().call("screen_rule", json.dumps({"spec": GAP_FADE}))
    assert "Already screened" in again
    assert len(experiments.rows(purpose="screen")) == 1


def test_screens_stop_at_the_runs_allowance(folder: Path) -> None:
    tools = _tools(max_screens=1)
    tools.call("screen_rule", json.dumps({"spec": GAP_FADE}))
    other = {**GAP_FADE, "side": "with"}  # follow the gap instead of fading it: another idea
    assert "used its 1 screens" in tools.call("screen_rule", json.dumps({"spec": other}))


def test_a_screen_with_other_numbers_is_tuning_and_is_refused(folder: Path) -> None:
    tools = _tools()
    tools.call("screen_rule", json.dumps({"spec": GAP_FADE}))
    tuned = {**GAP_FADE, "when": [{"signal": "gap", "op": ">=", "value": 0.02, "absolute": True}]}
    out = tools.call("screen_rule", json.dumps({"spec": tuned}))
    assert "screened this idea this run already" in out
    later = _tools().call("screen_rule", json.dumps({"spec": tuned}))  # the next night
    assert "the same idea as" in later
    assert len(experiments.rows(purpose="screen")) == 1  # neither spent a screen


def test_an_engine_reading_past_the_discovery_end_is_refused(folder: Path) -> None:
    late = _gappy()  # its sessions run into 2022; pretend the discovery end is earlier
    tools = agent_tools.ResearchTools(
        asked_by="autopilot",
        discovery_end=date(2021, 12, 31),
        now=NOW,
        engine=lambda end: engine.Engine(late),
    )
    out = tools.call("screen_rule", json.dumps({"spec": GAP_FADE}))
    assert "SealedPeriod" in out
    assert experiments.rows(purpose="screen") == []


def test_the_discovery_engine_drops_every_bar_after_the_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eulerlab.research import fast_eval

    full = _data({"AAA": [100.0] * 300})
    monkeypatch.setattr(engine, "Data", lambda: full)
    monkeypatch.setattr(fast_eval, "real_store", fast_eval.Store)
    cut = agent_tools.discovery_engine(date(2022, 6, 30))
    assert isinstance(cut, fast_eval.FastEngine)
    assert max(cut.store.days) <= date(2022, 6, 30)
    assert max(cut.data.sessions) <= date(2022, 6, 30)
    assert max(cut.data.panel["AAA"]) <= date(2022, 6, 30)
    assert cut.data.end <= date(2022, 6, 30)


def test_a_bad_spec_is_an_answer_not_a_crash(folder: Path) -> None:
    out = _tools().call("screen_rule", json.dumps({"spec": {"kind": "swing", "side": "short"}}))
    assert "does not parse" in out


def test_family_record_tallies_screens(folder: Path) -> None:
    _tools().call("screen_rule", json.dumps({"spec": GAP_FADE}))
    out = _tools().call("family_record", json.dumps({"match": "gap"}))
    assert "intraday:gap: 1 tried" in out


def test_the_toolbox_offers_only_its_own_tools() -> None:
    names = {s["function"]["name"] for s in _tools().schemas()}
    assert names == {
        "language",
        "signals",
        "claim_record",
        "family_record",
        "agenda",
        "ask_question",
        "record_finding",
        "define_feature",
        "feature_ic",
        "event_study",
        "screen_rule",
        "screen_formula",
        "combine_signals",
    }
    assert "no tool" in _tools().call("place_order", "{}")


def test_the_research_tools_import_nothing_an_agent_may_not() -> None:
    path = Path(agent_tools.__file__)
    assert boundaries.violations(path) == []


# --- the loop through the runtime -----------------------------------------------------------


def _call(name: str, arguments: dict[str, Any], n: int) -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": f"c{n}",
                            "function": {"name": name, "arguments": json.dumps(arguments)},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }


def _say(text: str) -> dict[str, Any]:
    return {"choices": [{"message": {"content": text}, "finish_reason": "stop"}]}


class ScriptedModel:
    """Plays a researcher: looks at the signals, screens one rule, then writes it up."""

    def __init__(self, final: str) -> None:
        self.script = [
            _call("signals", {}, 1),
            _call("screen_rule", {"spec": GAP_FADE}, 2),
            _say(final),
        ]
        self.seen: list[dict[str, Any]] = []

    def __call__(self, chosen: Provider, payload: dict[str, Any]) -> dict[str, Any]:
        self.seen.append(payload)
        return self.script.pop(0)


def _autopilot(**options: Any) -> dict[str, Any]:
    spec = AgentSpec(
        name="autopilot",
        title="Research autopilot",
        job="writes rules",
        worker="eulerlab.agents.workers.autopilot",
        uses_model=True,
        daily_requests=17,
        provider="groq",
        options={"cards": 2, "explore": True, **options},
    )
    return {"autopilot": effective(spec, None)}


def _final() -> str:
    swing = {**GAP_FADE, "kind": "swing", "hold": 3, "side": "with"}
    return json.dumps(
        {
            "cards": [
                {"title": "gap fade", "claim": "c", "rationale": "screened", "engine": GAP_FADE},
                {"title": "gap follow", "claim": "c", "rationale": "r", "engine": swing},
            ]
        }
    )


def test_the_autopilot_researches_then_writes_cards(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = ScriptedModel(_final())
    monkeypatch.setattr(chat, "_send", model)
    monkeypatch.setattr(chat, "selected_provider", lambda name="", model="": GROQ)
    monkeypatch.setattr(agent_tools, "discovery_engine", lambda end: engine.Engine(_gappy()))
    out = runtime.run("autopilot", root=folder / "agents", agents=_autopilot(), now=NOW)
    assert out.status == "ok", out.summary
    assert len(out.data["cards"]) == 2
    assert out.requests == 3 and len(out.traces) == 3
    # The second request carried the screen's figures back to the model.
    assert any(
        m.get("role") == "tool" and "net_sharpe" in str(m.get("content"))
        for m in model.seen[2]["messages"]
    )
    card = yaml.safe_load((folder / out.data["cards"][0]["path"]).read_text())
    assert card["exploration"]["screens"] == 1
    assert card["exploration"]["this_rule_screened"] is True
    assert card["exploration"]["traces"] == out.traces
    assert any("exploratory screen" in f for f in card["red_flags"])
    assert {r["id"] for r in trace.rows()} == set(out.traces)


def test_a_failed_loop_falls_back_to_the_one_shot_prompt(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(chosen: Provider, payload: dict[str, Any]) -> dict[str, Any]:
        if "tools" in payload:
            raise chat.Refused("no tools on this model")
        return _say(_final())

    monkeypatch.setattr(chat, "_send", broken)
    monkeypatch.setattr(chat, "selected_provider", lambda name="", model="": GROQ)
    out = runtime.run("autopilot", root=folder / "agents", agents=_autopilot(), now=NOW)
    assert out.status == "ok", out.summary
    assert len(out.data["cards"]) == 2
    assert any("research loop failed" in n for n in out.notes)
    card = yaml.safe_load((folder / out.data["cards"][0]["path"]).read_text())
    assert "exploration" not in card


def test_the_loop_is_off_unless_asked(folder: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict[str, Any]] = []

    def one_shot(chosen: Provider, payload: dict[str, Any]) -> dict[str, Any]:
        sent.append(payload)
        return _say(_final())

    monkeypatch.setattr(chat, "_send", one_shot)
    monkeypatch.setattr(chat, "selected_provider", lambda name="", model="": GROQ)
    runtime.run("autopilot", root=folder / "agents", agents=_autopilot(explore=False), now=NOW)
    assert sent and all("tools" not in p for p in sent)


def test_converse_needs_two_requests_left(folder: Path) -> None:
    agents = _autopilot()
    spec = agents["autopilot"]
    ctx = runtime.Context(
        agent=spec, brief="", brief_ids=[], out_dir=folder, root=folder, now=NOW, budget_left=1
    )
    with pytest.raises(runtime.BudgetSpent):
        ctx.converse("s", "u", _tools(), rounds=5)


def test_explore_system_prompt_names_the_bar() -> None:
    assert "raises the bar" in writer.EXPLORE_SYSTEM
    for tool in ("agenda", "define_feature", "feature_ic", "event_study", "record_finding"):
        assert tool in writer.EXPLORE_SYSTEM


# --- formula cards (ADR-191) ------------------------------------------------------------------

V2 = {
    "shape": "event",
    "kind": "intraday",
    "side": "short",
    "when": "and(gt(gap_ratio, 1.02), results_morning)",
    "score": "gap_ratio",
}
GAP_RATIO = "div(open_price, delay(close_price, 1))"


def _keep_gap_ratio() -> None:
    from eulerlab.paths import data_path

    path = data_path("derived/features.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"name": "gap_ratio", "formula": GAP_RATIO, "status": "kept", "author": "t", "why": "w"}
    path.write_text(json.dumps(row) + "\n")


def test_a_formula_card_is_written_with_its_features_expanded(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _keep_gap_ratio()
    swing = {**GAP_FADE, "kind": "swing", "hold": 3, "side": "with"}
    answer = json.dumps(
        {
            "cards": [
                {"title": "results gap fade", "claim": "c", "rationale": "r", "engine_v2": V2},
                {"title": "gap follow", "claim": "c", "rationale": "r", "engine": swing},
            ]
        }
    )
    monkeypatch.setattr(chat, "_send", lambda chosen, payload: _say(answer))
    monkeypatch.setattr(chat, "selected_provider", lambda name="", model="": GROQ)
    out = runtime.run(
        "autopilot", root=folder / "agents", agents=_autopilot(explore=False), now=NOW
    )
    assert out.status == "ok", out.summary
    first = out.data["cards"][0]
    card = yaml.safe_load((folder / first["path"]).read_text())
    assert "engine" not in card
    assert card["engine_v2"]["when"] == f"and(gt({GAP_RATIO}, 1.02), results_morning)"
    # The card reads back without the registry: it stores the formula, not the name.
    (folder / "data" / "derived" / "features.jsonl").unlink()
    spec = engine.card_spec(first["id"], folder / "hypotheses")
    assert spec is not None and spec.fingerprint() == writer.spec_of(card).fingerprint()


def test_a_formula_card_that_reads_ahead_is_dropped_with_why() -> None:
    bad = {**V2, "when": "gt(close_price, 100)"}
    kept, dropped = writer.accept([{"title": "peek", "engine_v2": bad}], {})
    assert kept == [] and "delay" in dropped[0]
