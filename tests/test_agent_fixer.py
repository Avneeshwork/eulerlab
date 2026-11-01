"""The engineering agent's fixer: one file and its test, on a branch, proven before anyone sees it (ADR-113)."""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from pathlib import Path

import pytest

from eulerlab.agents import boundaries
from eulerlab.devtools import fixer

FILE = "src/eulerlab/demo/thing.py"
TEST = "tests/test_thing.py"


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "src/eulerlab/demo").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "docs").mkdir()
    (repo / FILE).write_text("def half(x: int) -> int:\n    return x / 2\n")
    (repo / TEST).write_text(
        "from eulerlab.demo.thing import half\n\ndef test_half():\n    assert half(4) == 2\n"
    )
    (repo / "tests/test_other.py").write_text("import json\n")
    (repo / "CLAUDE.md").write_text("rules")
    (repo / "docs/ARCHITECTURE.md").write_text(
        "# Arch\n\n## Demo\n\n`demo/thing.py` halves numbers.\n\n## Other\n\nunrelated\n"
    )
    return repo


class _Git:
    """A stand-in for git and the checks: records every command, never runs one."""

    def __init__(self, repo: Path, fail: Sequence[str] = (), fail_times: int = 99) -> None:
        self.repo, self.fail, self.fail_times = repo, set(fail), fail_times
        self.calls: list[list[str]] = []
        self.tree: Path | None = None

    def __call__(self, cmd: Sequence[str], cwd: Path) -> tuple[int, str]:
        cmd = list(cmd)
        self.calls.append(cmd)
        if cmd[:3] == ["git", "worktree", "add"]:
            self.tree = Path(cmd[5])
            shutil.copytree(self.repo, self.tree, ignore=shutil.ignore_patterns("data"))
            return 0, ""
        if cmd[:3] == ["git", "worktree", "remove"]:
            shutil.rmtree(cmd[-1], ignore_errors=True)
            return 0, ""
        if cmd[:2] == ["git", "diff"]:
            assert self.tree is not None
            changed = [
                str(p.relative_to(self.tree))
                for p in self.tree.rglob("*")
                if p.is_file()
                and p.read_bytes() != (self.repo / p.relative_to(self.tree)).read_bytes()
            ]
            return 0, "\n".join(changed)
        name = next((n for n in self.fail if n in " ".join(cmd)), None)
        if name and self.fail_times > 0:
            self.fail_times -= 1
            return 1, f"{name} said no"
        return 0, "ok"

    def ran(self, word: str) -> bool:
        return any(word in " ".join(c) for c in self.calls)


def _answer(file: str | None, test: str | None = None) -> str:
    return json.dumps({"explanation": "used integer division", "file": file, "test": test})


GOOD = "def half(x: int) -> int:\n    return x // 2\n"


def test_the_never_touch_list_is_refused_before_any_model_request(tmp_path: Path) -> None:
    asked: list[str] = []

    def ask(system: str, user: str) -> str:
        asked.append(user)
        return ""

    for path in (
        "src/eulerlab/gates.py",
        "src/eulerlab/oms/ems.py",
        "src/eulerlab/broker/kite.py",
        "src/eulerlab/features/trials.py",
        "src/eulerlab/agents/boundaries.py",
        "src/eulerlab/devtools/fixer.py",
        "config/mandate.yaml",
        "tests/test_x.py",
    ):
        attempt = fixer.fix(path, "err", ask, repo=tmp_path)
        assert attempt.outcome == "refused", path
    assert asked == []
    assert fixer.allowed("src/eulerlab/agents/workers/lab.py")


def test_the_model_sees_the_rules_the_architecture_the_file_its_test_and_the_error(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    assert fixer.tests_for(FILE, repo) == [TEST]
    text = fixer.context(FILE, "TypeError: float", [TEST], repo)
    for part in ("rules", "halves numbers", "return x / 2", "def test_half", "TypeError: float"):
        assert part in text
    assert "unrelated" not in text


def test_a_green_fix_is_committed_on_its_own_branch(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    git = _Git(repo)
    attempt = fixer.fix(
        FILE, "TypeError", lambda s, u: _answer(GOOD), repo=repo, run=git, push=False
    )
    assert attempt.outcome == "committed" and attempt.green
    assert attempt.branch.startswith("agent-fix/") and attempt.test == TEST
    assert [n for n, _, _ in attempt.checks] == ["ruff", "format", "mypy", "pytest", "engine"]
    assert git.ran("git commit") and not git.ran("git push")
    assert git.calls[-1][:3] == ["git", "worktree", "remove"]
    assert (repo / FILE).read_text().endswith("x / 2\n"), "the checkout is never touched"


def test_a_fix_that_touches_another_file_is_thrown_away(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    class _Wide(_Git):
        def __call__(self, cmd: Sequence[str], cwd: Path) -> tuple[int, str]:
            if list(cmd)[:2] == ["git", "diff"] and self.tree:
                (self.tree / "tests/test_other.py").write_text("import os\n")
            return super().__call__(cmd, cwd)

    git = _Wide(repo)
    attempt = fixer.fix(FILE, "e", lambda s, u: _answer(GOOD), repo=repo, run=git, push=False)
    assert attempt.outcome.startswith("diff too wide")
    assert not git.ran("git commit")


def test_failed_checks_get_one_retry_with_the_errors_then_go_to_the_operator(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    prompts: list[str] = []

    def ask(system: str, user: str) -> str:
        prompts.append(user)
        return _answer(GOOD)

    once = _Git(repo, fail=["mypy"], fail_times=1)
    attempt = fixer.fix(FILE, "e", ask, repo=repo, run=once, push=False)
    assert attempt.outcome == "committed" and len(prompts) == 2
    assert "mypy said no" in prompts[1]

    always = _Git(repo, fail=["pytest"])
    attempt = fixer.fix(FILE, "e", ask, repo=repo, run=always, push=False)
    assert attempt.outcome == "checks failed" and not always.ran("git commit")


def test_no_fix_when_the_model_says_it_cannot_be_done_in_one_file(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    attempt = fixer.fix(FILE, "e", lambda s, u: _answer(None), repo=repo, run=_Git(repo))
    assert attempt.outcome == "no fix"


def test_apply_merges_only_a_fix_branch(tmp_path: Path) -> None:
    git = _Git(tmp_path)
    ok, _ = fixer.apply("20261101T120000-abc123", repo=tmp_path, run=git)
    assert ok and git.calls == [["git", "merge", "--no-edit", "agent-fix/20261101T120000-abc123"]]
    ok, _ = fixer.apply("main; rm -rf /", repo=tmp_path, run=git)
    assert not ok and len(git.calls) == 1


def test_the_quality_check_names_one_finding_per_file(tmp_path: Path) -> None:
    outputs = {
        "ruff": "src/eulerlab/a.py:3:1: F401 unused import\nsrc/eulerlab/a.py:9:1: E501 long\n",
        "mypy": "src/eulerlab/b.py:12: error: Incompatible return value\nFound 1 error\n",
        "pytest": "/home/x/src/eulerlab/c.py:40: AssertionError\n1 failed\n",
    }

    def run(cmd: Sequence[str], cwd: Path) -> tuple[int, str]:
        tool = next(k for k in outputs if k in " ".join(cmd))
        return 1, outputs[tool]

    found = fixer.quality(tmp_path, run)
    assert found == [
        ("src/eulerlab/a.py", 3, "ruff: F401 unused import"),
        ("src/eulerlab/b.py", 12, "mypy: Incompatible return value"),
        ("src/eulerlab/c.py", 40, "pytest: AssertionError"),
    ]


def test_only_the_engineering_agent_may_import_the_fixer() -> None:
    assert boundaries.fixer_users() == ["engineering.py"]


# --- the engineering agent's fix mode ---


def test_engineering_turns_queued_crashes_into_fixes_waiting_for_the_operator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab.agents import doctor, runtime
    from eulerlab.agents.spec import AgentSpec, effective

    doctor.treat(
        [
            doctor.Problem("code_error", "lab", "r1", "KeyError", file=FILE, error="trace"),
            doctor.Problem("code_error", "data", "r2", "ValueError", file="src/eulerlab/b.py"),
        ],
        tmp_path,
    )

    def fake_fix(file: str, error: str, ask: fixer.Ask, **_: object) -> fixer.Attempt:
        ask("system", "user")
        attempt = fixer.Attempt(id="20261101T120000-abc123", file=file, branch="agent-fix/x")
        attempt.checks = [("ruff", True, ""), ("pytest", file == FILE, "")]
        attempt.outcome = "branch pushed" if file == FILE else "checks failed"
        return attempt

    monkeypatch.setattr(fixer, "fix", fake_fix)
    spec = AgentSpec(
        name="engineering",
        title="Engineering",
        job="fixes code",
        worker="eulerlab.agents.workers.engineering",
        uses_model=True,
        daily_requests=5,
        provider="claude-opus",
    )
    out = runtime.run(
        "engineering",
        args={"mode": "fix"},
        root=tmp_path,
        agents={"engineering": effective(spec, None)},
        asker=lambda s, u, a: "{}",
    )
    assert out.status == "ok", out.summary
    kinds = [(i.kind, i.title.split(" ")[0]) for i in out.items]
    assert kinds == [("proposal", "fix"), ("finding", "could")]
    assert "make agent-fix-apply ID=20261101T120000-abc123" in out.items[0].body
    assert doctor.queued(tmp_path) == []
