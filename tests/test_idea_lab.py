"""The idea lab's own ideas, its memory and its handoff with the research agent (ADR-111).

The end-to-end tests use the same kind of synthetic panel as `test_agent_trials.py`.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from eulerlab.agents import runtime
from eulerlab.agents.spec import AgentSpec, all_effective, effective
from eulerlab.features import formula
from eulerlab.features.panel import PanelRow
from eulerlab.research import codegen, idea_generator, idea_memory
from eulerlab.research.idea_memory import Experience
from eulerlab.validation import holdout

DAY = date(2026, 11, 2)
START = date(2019, 1, 1)


def _panel(n_symbols: int = 60, n_days: int = 900) -> list[PanelRow]:
    """Each name drifts at its own steady rate, so trailing return predicts forward return."""
    rows: list[PanelRow] = []
    for s in range(n_symbols):
        drift = (s - n_symbols / 2) * 0.00004
        price = 100.0
        for d in range(n_days):
            price *= 1.0 + drift + 0.004 * math.sin(d * 0.7 + s)
            rows.append(
                PanelRow(
                    day=START + timedelta(days=d),
                    symbol=f"S{s:02d}",
                    close=price,
                    volume=1e5,
                    turnover=1e9,
                    isin=f"IN{s:010d}",
                )
            )
    return rows


NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def _families() -> idea_generator.Families:
    return idea_generator.load_families()


def _exp(
    feature: str,
    family: str,
    *,
    ic: float = 0.0,
    t: float = 0.0,
    passed: bool = False,
    survived: bool = False,
    sharpe: float | None = None,
    at: str = "2026-11-01T12:00:00+00:00",
) -> Experience:
    return Experience(
        id=idea_memory.experience_id(feature, at),
        at=at,
        day=at[:10],
        card=feature,
        family=family,
        source="template",
        features=[feature],
        ic={feature: ic},
        t={feature: t},
        screened_in=passed,
        survived=survived,
        robust_sharpe=sharpe,
    )


# --- the families ---


def test_every_family_template_parses_and_has_a_reason() -> None:
    fams = _families()
    assert len(fams.families) >= 12
    total = 0
    for name, fam in fams.families.items():
        made = idea_generator.expand(fam)
        assert made, name
        total += len(made)
        for feature in made:
            assert formula.is_known(feature), feature
    assert total >= 60


def test_a_template_that_copies_a_library_feature_is_named_after_it() -> None:
    assert idea_generator.canonical("ts_drawdown(close, 126)") == "max_drawdown"
    assert idea_generator.canonical("neg(ret(21))") == "reversal_1m"
    assert idea_generator.canonical("neg(ret(5))") == "formula:neg(ret(5))"


# --- the plan ---


def test_the_same_day_plans_the_same_ideas_and_none_is_repeated() -> None:
    fams = _families()
    a = idea_generator.plan(fams, [], n=20, day=DAY)
    b = idea_generator.plan(fams, [], n=20, day=DAY)
    assert [i.feature for i in a.ideas] == [i.feature for i in b.ideas]
    assert len({i.feature for i in a.ideas}) == 20
    assert len({i.family for i in a.ideas}) >= 5  # an empty memory explores widely


def test_nothing_already_tested_is_planned_again() -> None:
    fams = _families()
    first = idea_generator.plan(fams, [], n=15, day=DAY)
    memory = [_exp(i.feature, i.family) for i in first.ideas]
    second = idea_generator.plan(fams, memory, n=15, day=DAY)
    assert not {i.feature for i in first.ideas} & {i.feature for i in second.ideas}


def test_memory_turns_into_flips_combinations_and_window_variants() -> None:
    fams = _families()
    memory = [
        _exp("formula:neg(ts_std(ret(1), 63))", "low_volatility", ic=0.04, t=3.0, passed=True),
        _exp("formula:delay(ret(126), 21)", "momentum", ic=0.03, t=2.5, passed=True),
        _exp("formula:neg(ret(5))", "short_term_reversal", ic=-0.03, t=-3.0),
    ]
    out = idea_generator.plan(fams, memory, n=12, day=DAY)
    kinds = {i.source for i in out.ideas}
    assert {"flip", "combo", "mutation", "template"} <= kinds
    flips = [i.feature for i in out.ideas if i.source == "flip"]
    assert flips == ["formula:ret(5)"]
    assert "formula:neg(ts_std(ret(1), 126))" in {i.feature for i in out.ideas}


def test_when_templates_run_out_the_memory_fills_the_day() -> None:
    fams = _families()
    everything = [f for fam in fams.families.values() for f in idea_generator.expand(fam)]
    memory = [_exp(f, "momentum") for f in everything]
    memory.append(
        _exp("formula:neg(ts_std(ret(1), 63))", "low_volatility", ic=0.04, t=3.0, passed=True)
    )
    out = idea_generator.plan(fams, memory, n=6, day=DAY)
    assert out.ideas and all(i.source != "template" for i in out.ideas)
    assert "every family template is already tested" in out.skipped


def test_neighbours_vary_windows_but_not_the_one_day_return() -> None:
    near = idea_generator.neighbours("formula:neg(ts_std(ret(1), 63))")
    assert near == ["formula:neg(ts_std(ret(1), 31))", "formula:neg(ts_std(ret(1), 126))"]
    assert idea_generator.flip("formula:neg(ret(5))") == "formula:ret(5)"


# --- cards ---


def test_a_written_card_builds_from_the_library_and_keeps_its_holdout(tmp_path: Path) -> None:
    fams = _families()
    ideas = idea_generator.plan(fams, [], n=3, day=DAY).ideas
    written = idea_generator.write_cards(
        ideas, fams, day=DAY, holdout_starts=date(2025, 1, 1), folder=tmp_path
    )
    assert len(written) == 3
    for idea, path in written:
        built = codegen.build_from_card(path)
        assert len(built) == 1
        h = holdout.load(path)
        assert h.holdout.starts == date(2025, 1, 1) and h.holdout.is_unread
        spec = yaml.safe_load(path.read_text())
        assert spec["family"] == idea.family and len(spec["red_flags"]) >= 3
    before = written[0][1].read_text()
    again = idea_generator.write_cards(
        ideas, fams, day=DAY, holdout_starts=date(2025, 1, 1), folder=tmp_path
    )
    assert again[0][1] == written[0][1] and again[0][1].read_text() == before


# --- model proposals ---


def test_model_ideas_must_parse_be_new_and_carry_a_reason() -> None:
    fams = _families()
    answer = json.dumps(
        {
            "ideas": [
                {
                    "family": "low_volatility",
                    "formula": "neg(ts_std(ret(1), 40))",
                    "reason": "calm stocks are under-owned by leveraged buyers",
                },
                {"family": "new", "formula": "exec(close)", "reason": "x" * 30},
                {"family": "new", "formula": "neg(ret(5))", "reason": "already tested, dropped"},
                {"family": "new", "formula": "ts_rank(volume, 63)", "reason": "short"},
                {
                    "family": "made_up",
                    "formula": "ts_rank(volume, 63)",
                    "reason": "rising volume rank shows growing interest from buyers",
                },
            ]
        }
    )
    got = idea_generator.proposals(answer, fams, {"formula:neg(ret(5))"}, limit=5)
    assert [(i.feature, i.family) for i in got] == [
        ("formula:neg(ts_std(ret(1), 40))", "low_volatility"),
        ("formula:ts_rank(volume, 63)", "model"),
    ]
    assert idea_generator.proposals("no json here", fams, set(), limit=5) == []


# --- memory ---


def test_memory_appends_and_scores_families(tmp_path: Path) -> None:
    for e in [
        _exp("a", "momentum", passed=True, survived=True, sharpe=0.8),
        _exp("b", "momentum"),
        _exp("c", "low_volatility"),
    ]:
        idea_memory.append(tmp_path, e)
    loaded = idea_memory.load(tmp_path)
    assert [e.card for e in loaded] == ["a", "b", "c"]
    s = idea_memory.scores(loaded, ["momentum", "low_volatility", "lottery_max"])
    assert s["momentum"].tried == 2 and s["momentum"].survived == 1
    assert s["lottery_max"].tried == 0
    assert s["momentum"].mean > s["low_volatility"].mean


def test_thompson_is_seeded_by_the_day_and_favours_what_works() -> None:
    import random

    s = idea_memory.scores(
        [_exp(str(i), "good", passed=True) for i in range(8)]
        + [_exp(f"x{i}", "bad") for i in range(8)]
    )
    picks = [
        idea_memory.thompson(s, ["good", "bad"], random.Random(idea_memory.seed_for(DAY, str(k))))
        for k in range(50)
    ]
    assert picks.count("good") > 40
    one = random.Random(idea_memory.seed_for(DAY))
    two = random.Random(idea_memory.seed_for(DAY))
    assert idea_memory.thompson(s, ["good", "bad"], one) == idea_memory.thompson(
        s, ["good", "bad"], two
    )


def test_lessons_cite_the_record_and_call_a_family_dead() -> None:
    memory = [_exp(f"f{i}", "lottery_max") for i in range(4)] + [
        _exp("w", "momentum", passed=True, survived=True, sharpe=0.9),
        _exp("r", "short_term_reversal", ic=-0.02, t=-2.5),
    ]
    found = idea_memory.lessons(memory)
    texts = " | ".join(lesson.text for lesson in found)
    assert "lottery_max: 0 of 4" in texts and "survived" in texts and "wrong way" in texts
    ids = {e.id for e in memory}
    assert all(lesson.cites and set(lesson.cites) <= ids for lesson in found)


def test_feedback_puts_working_families_first_and_skips_dead_ones() -> None:
    memory = [_exp(f"f{i}", "lottery_max") for i in range(4)] + [_exp("w", "momentum", passed=True)]
    searches = {"momentum": "price momentum", "lottery_max": "max effect", "skewness": "skew"}
    fb = idea_memory.feedback(memory, searches, missing_features=["liquidity_beta"])
    assert fb.working == ["momentum"] and fb.dead == ["lottery_max"]
    assert fb.topics == ["price momentum", "skew"]
    text = idea_memory.guidance(fb)
    assert "momentum" in text and "liquidity_beta" in text and "lottery_max" in text


# --- the lab, end to end ---


def _lab(**options: Any) -> dict[str, Any]:
    spec = all_effective()["lab"].spec
    merged = {**spec.options, **options}
    return {"lab": effective(spec.model_copy(update={"options": merged}), None)}


@pytest.fixture
def lab_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from eulerlab.features import panel, trials
    from eulerlab.quality import contract

    rows = _panel()
    monkeypatch.setattr(panel, "read_panel", lambda *a, **k: rows)
    monkeypatch.setattr(trials, "TRIALS_PATH", tmp_path / "trials.jsonl")
    monkeypatch.setattr(contract, "guard", lambda *a, **k: [])
    monkeypatch.setattr(idea_generator, "FOLDER", tmp_path / "lab_ideas")
    return tmp_path


def test_the_lab_tests_its_own_ideas_remembers_them_and_moves_on(lab_env: Path) -> None:
    root = lab_env / "agents"
    agents = _lab(max_ideas=4, model_ideas=0)
    out = runtime.run("lab", root=root, agents=agents, now=NOW)
    assert out.status == "ok", (out.summary, out.notes)
    assert "4 card(s) tested" in out.summary
    memory = idea_memory.load(root)
    assert len(memory) == 4 and all(e.trials >= 1 for e in memory)
    logged = (lab_env / "trials.jsonl").read_text().splitlines()
    assert len(logged) == sum(e.trials for e in memory)
    assert out.data["feedback"]["tested"] == 4 and out.data["feedback"]["topics"]
    assert any(i.title.startswith("Today's lab") for i in out.items)

    again = runtime.run("lab", root=root, agents=agents, now=NOW)
    first = set(out.data["planned"])
    assert first and not first & set(again.data["planned"])
    assert len(idea_memory.load(root)) == 8


def _drafting(folder: Path, needs: list[str]) -> Callable[[runtime.Context], runtime.WorkerResult]:
    def worker(ctx: runtime.Context) -> runtime.WorkerResult:
        item = runtime.Item(kind="draft", title="d", ref=str(folder), data={"needs_data": needs})
        return runtime.WorkerResult("drafted", [item])

    return worker


def test_the_lab_tests_every_untested_research_draft_not_only_the_latest(lab_env: Path) -> None:
    root = lab_env / "agents"
    drafts = []
    for i, feature in enumerate(["volume_trend", "liquidity_beta"]):
        folder = lab_env / f"draft-{i}"
        folder.mkdir()
        (folder / "card.yaml").write_text(
            f"id: PENDING\ntitle: draft {i}\nclaim: a claim\nconfigurations:\n"
            f"- {{shape: rank_and_hold, feature: {feature}, top_n: 30, rebalance: 21}}\n"
            "red_flags: [one]\nholdout: {starts: '2021-01-01', status: unread}\n"
        )
        drafts.append(folder)
    # The older run holds the buildable draft; the newer one holds only the unbuildable one,
    # marked as waiting for data the way the 2026-10-30 run marked it.
    for n, (folder, needs) in enumerate([(drafts[0], []), (drafts[1], ["Nifty futures"])]):
        runtime.run(
            "research",
            root=root,
            agents={
                "research": effective(
                    AgentSpec(
                        name="research",
                        title="research agent",
                        job="a job for the test",
                        worker="eulerlab.agents.workers.research",
                    ),
                    None,
                )
            },
            now=datetime(2026, 10, 29 + n, 12, 0, tzinfo=UTC),
            worker=_drafting(folder, needs),
        )
    (drafts[1] / "draft.json").write_text(json.dumps({"card": "valid"}))
    out = runtime.run("lab", root=root, agents=_lab(max_ideas=0, model_ideas=0), now=NOW)
    assert str(drafts[0] / "card.yaml") in out.data["tested"]
    assert out.data["feedback"]["missing_features"] == ["liquidity_beta"]
    assert any(i.kind == "proposal" and "liquidity_beta" in i.body for i in out.items)
    # The draft the lab skipped reaches engineering (HISTORY #67: before ADR-128
    # it was recorded only at a step skipped drafts never reach).
    from eulerlab.agents import work

    assert out.data["unbuildable"] == [
        {"card": str(drafts[1] / "card.yaml"), "features": ["liquidity_beta"], "source": "research"}
    ]
    [task] = work.coding_handoffs(root, NOW)
    assert task.owner == "engineering" and task.args == {
        "feature": "liquidity_beta",
        "card": str(drafts[1] / "card.yaml"),
    }


def test_the_committed_lab_writes_its_own_ideas_beside_research() -> None:
    """Research-only from 2026-11-03 ("we have to backtest only what research finds");
    its own ideas back on 2026-11-04 (operator, T-4458), at the settings before that
    switch. Research's cards are still tested."""
    options = all_effective()["lab"].spec.options
    assert options["max_ideas"] == 30
    assert options["model_ideas"] == 6


def test_the_lab_asks_the_model_for_formulas_and_tests_the_ones_that_parse(lab_env: Path) -> None:
    root = lab_env / "agents"
    answer = json.dumps(
        {
            "ideas": [
                {
                    "family": "new",
                    "formula": "ts_rank(turnover, 63)",
                    "reason": "rising turnover rank marks names drawing new buyers",
                },
                {"family": "new", "formula": "import os", "reason": "this must never run at all"},
            ]
        }
    )
    out = runtime.run(
        "lab",
        root=root,
        agents=_lab(max_ideas=1, model_ideas=2),
        now=NOW,
        asker=lambda system, user, accept: answer,
    )
    assert out.status == "ok", out.summary
    assert out.requests == 1
    assert "formula:ts_rank(turnover, 63)" in out.data["planned"]
    assert {e.source for e in idea_memory.load(root)} == {"template", "model"}


# --- the research agent's side of the handoff ---


def test_research_takes_one_topic_a_day_in_turn() -> None:
    from eulerlab.agents.workers import research

    topics = ["a", "b", "c"]
    days = [datetime(2026, 11, d, 12, 0, tzinfo=UTC) for d in (1, 2, 3)]
    assert sorted(research.todays_topic(topics, d) for d in days) == topics


def test_research_picks_its_own_topic_and_reads_the_lab_only_as_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab.research import budget, paper_agent, paper_search, quantpedia

    root = tmp_path / "agents"
    fb = idea_memory.Feedback(
        topics=["frog in the pan momentum"], working=["momentum"], dead=["small_size"]
    )
    runtime.run(
        "lab",
        root=root,
        agents=_lab(),
        now=NOW,
        worker=lambda ctx: runtime.WorkerResult("ok", data={"feedback": fb.model_dump()}),
    )
    folder = tmp_path / "draft"
    folder.mkdir()
    (folder / "card.yaml").write_text(
        "id: PENDING\ntitle: Intraday futures liquidity\n"
        "claim: stocks with intraday futures basis and delivery strength outperform\n"
        "rationale: a reason\nconfigurations:\n"
        "- {shape: rank_and_hold, feature: illiquidity_amihud, top_n: 30, rebalance: 21}\n"
        "red_flags: [a, b, c]\n"
    )
    seen: dict[str, Any] = {}

    def fake_run(topic: str, **kw: Any) -> paper_agent.Run:
        seen["topic"], seen["guidance"] = topic, kw.get("guidance", "")
        cand = paper_search.Candidate("openalex", "1", "A paper", [], 2024, "abc", "u", "t")
        draft = paper_agent.Draft(cand, "abstract only", outcome="drafted", path=folder)
        return paper_agent.Run(topic, tmp_path, budget.SearchCost(0, 1, 10.0), [draft], [])

    monkeypatch.setattr(paper_agent, "run", fake_run)
    monkeypatch.setattr(quantpedia, "catalogue", lambda *a, **k: [])
    monkeypatch.setattr(quantpedia, "leads", lambda *a, **k: [])
    agents = {
        "research": effective(
            AgentSpec(
                name="research",
                title="research agent",
                job="a job for the test",
                worker="eulerlab.agents.workers.research",
                uses_model=True,
                daily_requests=5,
                options={"topics": ["low volatility India", "reversal India"]},
            ),
            None,
        )
    }
    out = runtime.run("research", root=root, agents=agents, now=NOW)
    assert out.status == "ok", out.summary
    # Research goes first (ADR-128): its own list, never the lab's topic.
    assert seen["topic"] in ("low volatility India", "reversal India")
    assert "small_size" in seen["guidance"]  # what failed: memory
    assert "passed the idea lab" not in seen["guidance"]  # what worked: not direction
    draft = next(i for i in out.items if i.kind == "draft")
    assert draft.data["needs_data"] == [] and draft.data["unknown_features"] == []
    assert not [i for i in out.items if i.kind == "data_request"]


def test_a_second_lab_run_stops_while_one_is_testing(lab_env: Path) -> None:
    from eulerlab.agents.workers import lab

    root = lab_env / "agents"
    root.mkdir(parents=True)
    (root / lab.LOCK).write_text("2026-11-02T05:00:00+00:00")
    out = runtime.run("lab", root=root, agents=_lab(max_ideas=2, model_ideas=0), now=NOW)
    assert out.status == "skipped" and "another idea lab run" in out.summary
    assert not (lab_env / "trials.jsonl").exists()

    (root / lab.LOCK).unlink()
    done = runtime.run("lab", root=root, agents=_lab(max_ideas=1, model_ideas=0), now=NOW)
    assert done.status == "ok" and not (root / lab.LOCK).exists()


# --- the liquidity floor and the Nifty comparison (ADR-112) ---


def test_generated_cards_carry_the_liquidity_floor_in_the_card_and_the_folder(
    tmp_path: Path,
) -> None:
    fams = _families()
    assert fams.min_turnover == 10_000_000
    ideas = idea_generator.plan(fams, [], n=2, day=DAY).ideas
    written = idea_generator.write_cards(
        ideas, fams, day=DAY, holdout_starts=date(2025, 1, 1), folder=tmp_path
    )
    for _, path in written:
        assert path.parent.name.endswith("-liq10000000")
        config = yaml.safe_load(path.read_text())["configurations"][0]
        assert config["min_turnover"] == 10_000_000
        assert "|liq10000000" in codegen.build_from_card(path)[0].label


def test_cards_tested_without_the_floor_are_not_learned_from() -> None:
    old = _exp("formula:neg(ts_std(ret(1), 21))", "low_volatility", passed=True, sharpe=5.6)
    new = _exp("formula:delay(ret(126), 21)", "momentum", passed=True).model_copy(
        update={"min_turnover": 10_000_000.0}
    )
    draft = _exp("reversal_1m", "research").model_copy(update={"source": "research"})
    kept = idea_memory.usable([old, new, draft], 10_000_000)
    assert [e.card for e in kept] == [new.card, draft.card]
    replanned = idea_generator.plan(_families(), kept, n=40, day=DAY)
    assert old.features[0] in {i.feature for i in replanned.ideas}


def test_the_ic_screen_drops_names_below_the_floor() -> None:
    from eulerlab.features.ic import evaluate
    from eulerlab.features.library import BY_NAME

    rows = _panel(n_symbols=40, n_days=300)
    thin = [replace(r, turnover=1e5) if r.symbol < "S20" else r for r in rows]
    everyone = evaluate(thin, BY_NAME["reversal_1m"], min_names=10)
    liquid = evaluate(thin, BY_NAME["reversal_1m"], min_names=10, min_turnover=1e7)
    assert everyone.n > 0 and liquid.n > 0
    assert liquid.mean_ic != everyone.mean_ic
    assert evaluate(thin, BY_NAME["reversal_1m"], min_names=30, min_turnover=1e7).n == 0


def test_survival_needs_a_return_over_nifty() -> None:
    from eulerlab.agents.workers import lab

    days = [date(2020, 1, 1).toordinal() + i for i in range(400)]
    iso = [date.fromordinal(d).isoformat() for d in days]
    market = {date.fromordinal(d): 0.001 for d in days}
    same = [100.0 * 1.001**i for i in range(400)]
    wobble = [v * (1 + 0.0005 * math.sin(i)) for i, v in enumerate(same)]
    assert (lab.excess_sharpe(iso, wobble, market) or 0.0) <= 0.5
    better = [100.0 * 1.002**i * (1 + 0.0005 * math.sin(i)) for i in range(400)]
    assert (lab.excess_sharpe(iso, better, market) or 0.0) > 1.0
    assert lab.excess_sharpe(iso[:100], better[:100], market) is None
    assert lab.excess_sharpe(iso, better, {}) is None
