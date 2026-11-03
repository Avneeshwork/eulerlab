"""The engineering agent codes the signals research cards name, free model first (ADR-127)."""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from eulerlab.agents import runtime, tasks, work
from eulerlab.agents.spec import AgentSpec, Skill, effective
from eulerlab.agents.workers import engineering
from eulerlab.devtools import fixer

NOW = datetime(2026, 11, 3, 4, 0, tzinfo=UTC)

FEATURE = '''"""Twenty-day high: the share of the last 20 closes below today's. For a card."""

from __future__ import annotations

from collections.abc import Sequence

from eulerlab.features.base import Feature
from eulerlab.features.panel import PanelRow


def fn(history: Sequence[PanelRow]) -> float | None:
    window = history[-21:]
    if len(window) < 21:
        return None
    return sum(1 for r in window[:-1] if r.close < window[-1].close) / 20.0


FEATURE = Feature("near_high_20", fn, "share of 20 closes below today", 21)
'''
TEST = "def test_it() -> None:\n    assert True\n"


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "src/eulerlab/features/coded").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "docs").mkdir()
    (repo / "docs/CODED_FEATURES.md").write_text("| Date |\n")
    for f in ("library.py", "base.py"):
        text = Path(f"src/eulerlab/features/{f}").read_text(encoding="utf-8")
        (repo / f"src/eulerlab/features/{f}").write_text(text)
    return repo


class _Git:
    """Records every command and runs none, except copying the worktree."""

    def __init__(self, repo: Path, fail: Sequence[str] = ()) -> None:
        self.repo, self.fail = repo, set(fail)
        self.calls: list[list[str]] = []
        self.tree: Path | None = None

    def __call__(self, cmd: Sequence[str], cwd: Path) -> tuple[int, str]:
        cmd = list(cmd)
        self.calls.append(cmd)
        if cmd[:3] == ["git", "worktree", "add"]:
            self.tree = Path(cmd[5])
            shutil.copytree(self.repo, self.tree)
            return 0, ""
        if cmd[:3] == ["git", "worktree", "remove"]:
            shutil.rmtree(cmd[-1], ignore_errors=True)
            return 0, ""
        if cmd[:2] == ["git", "status"]:
            assert self.tree is not None
            new = [
                str(p.relative_to(self.tree))
                for p in self.tree.rglob("*")
                if p.is_file() and not (self.repo / p.relative_to(self.tree)).exists()
            ]
            return 0, "\n".join(f"?? {n}" for n in new)
        if cmd[:3] == ["gh", "pr", "create"]:
            return 0, "https://github.com/o/r/pull/9"
        name = next((n for n in self.fail if n in " ".join(cmd)), None)
        return (1, f"{name} said no") if name else (0, "ok")

    def ran(self, word: str) -> bool:
        return any(word in " ".join(c) for c in self.calls)


def _reply(file: str | None, test: str | None = TEST, why: str = "counts closes") -> str:
    return json.dumps({"explanation": why, "file": file, "test": test})


def test_a_pure_signal_is_proven_pushed_and_given_a_pull_request(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    git = _Git(repo)
    asked: list[str] = []

    def ask(system: str, user: str) -> str:
        asked.append(user)
        return _reply(FEATURE)

    a = fixer.code_feature(
        "near_high_20", "title: a card", ask, card="c/card.yaml", model="groq", repo=repo, run=git
    )
    assert a.outcome == "pull request opened" and a.green
    assert [n for n, _, _ in a.checks] == ["pure", "ruff", "format", "mypy", "pytest", "engine"]
    assert a.branch.startswith("agent-feature/near_high_20-")
    assert git.ran("tests/test_coded_features.py") and git.ran("git push")
    added = next(c for c in git.calls if c[:2] == ["git", "add"])
    assert added[2:] == [
        "src/eulerlab/features/coded/near_high_20.py",
        "tests/test_coded_near_high_20.py",
        "docs/CODED_FEATURES.md",
    ]
    assert "<card>\ntitle: a card" in asked[0] and "class Feature" in asked[0]
    assert "def illiquidity_amihud" in asked[0]


def test_an_impure_signal_is_refused_before_any_check_then_retried(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    git = _Git(repo)
    replies = [_reply("import os\n" + FEATURE), _reply(FEATURE)]
    asked: list[str] = []

    def ask(system: str, user: str) -> str:
        asked.append(user)
        return replies.pop(0)

    a = fixer.code_feature("near_high_20", "card", ask, repo=repo, run=git, push=False)
    assert a.outcome == "committed" and len(asked) == 2
    assert "imports os" in asked[1]


def test_a_signal_needing_other_data_is_not_coded(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    git = _Git(repo)
    a = fixer.code_feature(
        "liquidity_beta",
        "card",
        lambda s, u: _reply(
            None, None, "cannot be built from one stock's own history: market liquidity"
        ),
        repo=repo,
        run=git,
    )
    assert a.outcome == "no fix" and "market liquidity" in a.explanation
    assert not git.ran("git commit") and git.ran("git branch -D agent-feature/liquidity_beta")


def test_failed_checks_twice_are_not_kept(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    git = _Git(repo, fail=["mypy"])
    a = fixer.code_feature("near_high_20", "card", lambda s, u: _reply(FEATURE), repo=repo, run=git)
    assert a.outcome == "checks failed" and not git.ran("git commit")


def test_a_bad_name_is_refused_before_any_model_request(tmp_path: Path) -> None:
    def ask(system: str, user: str) -> str:
        raise AssertionError("no model request")

    a = fixer.code_feature("Bad-Name", "card", ask, repo=_repo(tmp_path), run=_Git(tmp_path))
    assert a.outcome == "refused"


def test_the_coding_request_fits_groqs_free_minute() -> None:
    size = len(fixer.FEATURE_SYSTEM + fixer.feature_context("x_signal", "c" * 4000)) // 4
    assert size + 2_500 < engineering.FIT * 8000


# --- which model ---


def _ctx(tmp_path: Path, options: dict[str, Any]) -> runtime.Context:
    spec = AgentSpec(
        name="engineering",
        title="Engineering",
        job="codes signals",
        worker="eulerlab.agents.workers.engineering",
        uses_model=True,
        daily_requests=6,
        provider="claude-opus",
        options=options,
    )
    return runtime.Context(
        agent=effective(spec, None),
        brief="",
        brief_ids=[],
        out_dir=tmp_path / "out",
        root=tmp_path,
        now=NOW,
        budget_left=6,
    )


def test_groq_comes_first_and_is_skipped_when_a_request_would_not_fit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runtime, "resolve_provider", lambda wanted="": wanted)
    ctx = _ctx(tmp_path, {"models": ["groq", "claude-opus"]})
    assert engineering.models(ctx, 3_000) == ["groq", "claude-opus"]
    assert engineering.models(ctx, 20_000) == ["claude-opus"]
    assert "does not fit its free 8,000 tokens a minute" in ctx.notes[-1]


def test_an_unreachable_model_is_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime, "resolve_provider", lambda wanted="": "groq")
    ctx = _ctx(tmp_path, {"models": ["groq", "claude-opus"]})
    assert engineering.models(ctx, 100) == ["groq"]


def _card(tmp_path: Path, valid: bool = True) -> Path:
    folder = tmp_path / "drafts" / "run" / "paper"
    folder.mkdir(parents=True)
    (folder / "card.yaml").write_text("title: Near the 20-day high\n")
    (folder / "draft.json").write_text(json.dumps({"card": "valid" if valid else "incomplete"}))
    return folder / "card.yaml"


def _attempt(outcome: str, green: bool) -> fixer.Attempt:
    a = fixer.Attempt(id="x", file="f", branch="agent-feature/near_high_20-abc123")
    a.checks = [("pure", True, ""), ("pytest", green, "")]
    a.outcome = outcome
    return a


def test_opus_is_used_only_when_groqs_code_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx(tmp_path, {})
    ctx.args = {"mode": "feature", "feature": "near_high_20", "card": str(_card(tmp_path))}
    monkeypatch.setattr(engineering, "models", lambda c, size: ["groq", "claude-opus"])
    monkeypatch.setattr(engineering, "_use", lambda c, p: setattr(c, "model", p))
    used: list[str] = []

    def code(name: str, card_text: str, ask: Any, **kw: Any) -> fixer.Attempt:
        used.append(kw["model"])
        return _attempt(
            "pull request opened" if kw["model"] == "claude-opus" else "checks failed",
            kw["model"] == "claude-opus",
        )

    monkeypatch.setattr(fixer, "code_feature", code)
    out = engineering.run(ctx)
    assert used == ["groq", "claude-opus"]
    assert out.items[0].kind == "proposal" and "merge it" in out.summary
    assert out.data["tried"][0].startswith("groq: checks failed")


def test_a_groq_answer_that_it_cannot_be_built_does_not_spend_opus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx(tmp_path, {})
    ctx.args = {"mode": "feature", "feature": "liquidity_beta", "card": str(_card(tmp_path))}
    monkeypatch.setattr(engineering, "models", lambda c, size: ["groq", "claude-opus"])
    monkeypatch.setattr(engineering, "_use", lambda c, p: setattr(c, "model", p))
    used: list[str] = []

    def code(name: str, card_text: str, ask: Any, **kw: Any) -> fixer.Attempt:
        used.append(kw["model"])
        return _attempt("no fix", False)

    monkeypatch.setattr(fixer, "code_feature", code)
    out = engineering.run(ctx)
    assert used == ["groq"] and out.items[0].kind == "finding"


def test_a_signal_already_in_the_library_is_not_coded_again(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {})
    ctx.args = {"mode": "feature", "feature": "momentum_12_1", "card": "x"}
    assert "already in the library" in engineering.run(ctx).summary


# --- the hand-off from the lab ---


def _lab(root: Path, unbuildable: list[dict[str, Any]]) -> None:
    spec = AgentSpec(
        name="lab", title="Idea lab", job="tests cards", worker="eulerlab.agents.workers.lab"
    )
    runtime.run(
        "lab",
        root=root,
        agents={"lab": effective(spec, None)},
        now=NOW,
        worker=lambda ctx: runtime.WorkerResult("ok", data={"unbuildable": unbuildable}),
    )


def test_a_complete_card_the_lab_could_not_build_becomes_one_task_per_signal(
    tmp_path: Path,
) -> None:
    root = tmp_path / "agents"
    good, bad = _card(tmp_path / "a"), _card(tmp_path / "b", valid=False)
    _lab(
        root,
        [
            {"card": str(good), "features": ["near_high_20"]},
            {"card": str(bad), "features": ["liquidity_beta"]},
            {"card": str(good), "features": [""]},
        ],
    )
    made = work.coding_handoffs(root, NOW)
    assert [(t.kind, t.owner, t.args) for t in made] == [
        ("code_feature", "engineering", {"feature": "near_high_20", "card": str(good)})
    ]
    assert work.coding_handoffs(root, NOW) == []  # one task per signal, ever


def test_no_more_than_the_daily_cap_of_signals_is_handed_on(tmp_path: Path) -> None:
    root = tmp_path / "agents"
    rows = [
        {"card": str(_card(tmp_path / n)), "features": [f"signal_{n}"]} for n in ("a", "b", "c")
    ]
    _lab(root, rows)
    assert len(work.coding_handoffs(root, NOW)) == work.MAX_FEATURES == 2
    assert work.coding_handoffs(root, NOW) == []
    tomorrow = datetime(2026, 11, 4, 4, 0, tzinfo=UTC)
    assert [t.args["feature"] for t in work.coding_handoffs(root, tomorrow)] == ["signal_c"]


def test_the_task_starts_the_agent_with_the_signal_and_its_card() -> None:
    skill = Skill(
        kind="code_feature",
        what="code a signal",
        arg="feature",
        also=["card"],
        fixed={"mode": "feature"},
    )
    task = tasks.Task(
        id="T-1", title="t", detail="", owner="engineering", department="platform",
        created_by="lab", created="", due="", kind="code_feature",
        args={"feature": "near_high_20", "card": "c.yaml", "other": "x"},
    )  # fmt: skip
    assert work.run_args(task, skill) == {
        "mode": "feature",
        "feature": "near_high_20",
        "card": "c.yaml",
        "task": "T-1",
    }


def test_a_model_error_tries_once_more_then_the_next_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx(tmp_path, {})
    ctx.args = {"mode": "feature", "feature": "near_high_20", "card": str(_card(tmp_path))}
    monkeypatch.setattr(engineering, "models", lambda c, size: ["groq", "claude-opus"])
    monkeypatch.setattr(engineering, "_use", lambda c, p: setattr(c, "model", p))
    used: list[str] = []

    def code(name: str, card_text: str, ask: Any, **kw: Any) -> fixer.Attempt:
        used.append(kw["model"])
        if kw["model"] == "groq":
            raise RuntimeError("groq did not answer in 60 seconds")
        return _attempt("pull request opened", True)

    monkeypatch.setattr(fixer, "code_feature", code)
    out = engineering.run(ctx)
    assert used == ["groq", "groq", "claude-opus"] and out.items[0].kind == "proposal"


@pytest.mark.parametrize(
    "wrapped",
    ["'''\\\n" + FEATURE + "'''", "```python\n" + FEATURE + "```", FEATURE],
)
def test_code_wrapped_in_quotes_or_a_fence_is_unwrapped(wrapped: str) -> None:
    assert fixer.unwrap_code(wrapped).strip() == FEATURE.strip()


def test_a_failed_commit_is_not_reported_as_committed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    git = _Git(repo, fail=["git commit"])
    a = fixer.code_feature("near_high_20", "card", lambda s, u: _reply(FEATURE), repo=repo, run=git)
    assert a.outcome.startswith("commit failed") and not a.green
    assert git.ran("git branch -D agent-feature/near_high_20-")
