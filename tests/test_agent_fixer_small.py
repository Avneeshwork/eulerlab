"""The fixer's small context for a model with a per-minute limit: excerpt, edits, budget (HISTORY #78)."""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from pathlib import Path

import pytest

from eulerlab.agents.workers import engineering
from eulerlab.devtools import fixer

FILE = "src/eulerlab/demo/thing.py"
TEST = "tests/test_thing.py"

SOURCE = '''"""A demo module."""

from __future__ import annotations

import math

LIMIT = 10


def double(x: int) -> int:
    return x * 2


def half(x: int) -> int:
    return x / 2


def unrelated(y: int) -> int:
    return y + 1
''' + "".join(f"\n\ndef filler_{i}(z: int) -> int:\n    return z - {i}\n" for i in range(60))

TESTS = """from eulerlab.demo.thing import double, half, unrelated


def test_half() -> None:
    assert half(4) == 2


def test_double() -> None:
    assert double(2) == 4


def test_unrelated() -> None:
    assert unrelated(1) == 2
"""


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "src/eulerlab/demo").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "docs").mkdir()
    (repo / FILE).write_text(SOURCE)
    (repo / TEST).write_text(TESTS)
    (repo / "CLAUDE.md").write_text(
        "# Rules\n\n## Hard rules\n\n### Truth\n- never invent\n\n### Code\n- mypy --strict\n\n"
        "### Money safety\n- not for a fix\n\n## Style\n- plain\n"
    )
    (repo / "docs/ARCHITECTURE.md").write_text("# Arch\n")
    return repo


class _Git:
    """Records commands; copies the repo for `worktree add`; `checkout` restores the original."""

    def __init__(self, repo: Path, fail: Sequence[str] = (), fail_times: int = 99) -> None:
        self.repo, self.fail, self.fail_times = repo, set(fail), fail_times
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
        if cmd[:2] == ["git", "checkout"] and self.tree is not None:
            for rel in (FILE, TEST):
                shutil.copy(self.repo / rel, self.tree / rel)
            return 0, ""
        if cmd[:2] == ["git", "diff"] and self.tree is not None:
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


ERROR = (
    f'Traceback (most recent call last):\n  File "/r/{FILE}", line 15, in half\nTypeError: float'
)


def test_the_rules_digest_keeps_truth_data_and_code_only(tmp_path: Path) -> None:
    digest = fixer.rules_digest(_repo(tmp_path))
    assert "never invent" in digest and "mypy --strict" in digest
    assert "Money safety" not in digest and "plain" not in digest


def test_the_excerpt_shows_the_header_and_the_failing_function_not_the_rest() -> None:
    assert fixer.error_lines(FILE, ERROR) == [15]
    assert fixer.error_lines(FILE, f"{FILE}:9: error: bad") == [9]
    text = fixer.excerpt(SOURCE, [15], pad=0)
    assert "import math" in text and "def half" in text and "return x / 2" in text
    assert "filler_30" not in text and "# ... lines" in text
    assert fixer.shown_names(SOURCE, [15], 0) == {"half"}
    assert fixer.excerpt(SOURCE, [], pad=0) == SOURCE  # nothing named: the whole file


def test_only_the_tests_that_use_the_code_shown_are_sent() -> None:
    got = fixer.related_tests(TESTS, {"half"}, 5000)
    assert "test_half" in got and "test_double" not in got


def test_the_small_context_fits_a_free_groq_budget_where_the_old_one_does_not(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    big = "x = 1  # padding\n" * 4000
    (repo / FILE).write_text(SOURCE + big)
    old = fixer.tokens(fixer.SYSTEM) + fixer.tokens(fixer.context(FILE, ERROR, [TEST], repo))
    assert old > 6400
    small = fixer.small_context(FILE, ERROR, [TEST], 6400, repo=repo)
    assert small is not None and "def half" in small and "padding" not in small
    assert fixer.tokens(fixer.EDIT_SYSTEM) + fixer.tokens(small) + fixer.OUTPUT_RESERVE <= 6400
    assert fixer.small_context(FILE, ERROR, [TEST], 500, repo=repo) is None


def test_an_edit_must_match_exactly_once() -> None:
    assert (
        fixer.apply_edits("a = 1\nb = 2\n", [{"find": "b = 2", "replace": "b = 3"}])
        == "a = 1\nb = 3\n"
    )
    with pytest.raises(fixer.EditFailed, match="0 times"):
        fixer.apply_edits("a = 1\n", [{"find": "zzz", "replace": "y"}])
    with pytest.raises(fixer.EditFailed, match="2 times"):
        fixer.apply_edits("x\nx\n", [{"find": "x", "replace": "y"}])
    with pytest.raises(fixer.EditFailed):
        fixer.apply_edits("x\n", "not a list")


def _edits(find: str, replace: str, append: str | None = None) -> str:
    return json.dumps(
        {
            "explanation": "integer division",
            "edits": [{"find": find, "replace": replace}],
            "test_append": append,
        }
    )


def test_a_budgeted_fix_sends_the_small_context_applies_edits_and_proves_them(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    seen: list[tuple[str, str]] = []

    def ask(system: str, user: str) -> str:
        seen.append((system, user))
        return _edits(
            "    return x / 2",
            "    return x // 2",
            "def test_half_of_odd() -> None:\n    assert half(5) == 2",
        )

    git = _Git(repo)
    attempt = fixer.fix(FILE, ERROR, ask, repo=repo, run=git, push=False, budget=6400)
    assert attempt.outcome == "committed" and attempt.green
    system, user = seen[0]
    assert system == fixer.EDIT_SYSTEM and "filler_30" not in user and "def half" in user
    assert git.ran("git commit")


def test_edits_that_do_not_match_get_a_second_try_with_a_wider_window(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    answers = [
        _edits("return x/2", "return x // 2"),
        _edits("    return x / 2", "    return x // 2"),
    ]
    prompts: list[str] = []

    def ask(system: str, user: str) -> str:
        prompts.append(user)
        return answers[len(prompts) - 1]

    attempt = fixer.fix(FILE, ERROR, ask, repo=repo, run=_Git(repo), push=False, budget=6400)
    assert attempt.outcome == "committed" and len(prompts) == 2
    assert "could not be applied" in prompts[1] and "0 times" in prompts[1]


def test_failed_checks_retry_from_the_original_file(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    prompts: list[str] = []

    def ask(system: str, user: str) -> str:
        prompts.append(user)
        return _edits("    return x / 2", "    return x // 2")

    once = _Git(repo, fail=["mypy"], fail_times=1)
    attempt = fixer.fix(FILE, ERROR, ask, repo=repo, run=once, push=False, budget=6400)
    # The second round's find still matches: the first round's edit was undone.
    assert attempt.outcome == "committed" and len(prompts) == 2 and "mypy said no" in prompts[1]


def test_a_request_too_big_for_the_budget_says_so_without_asking(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    asked: list[str] = []

    def ask(system: str, user: str) -> str:
        asked.append(user)
        return ""

    attempt = fixer.fix(FILE, ERROR, ask, repo=repo, run=_Git(repo), push=False, budget=300)
    assert attempt.outcome == "too big for this model" and asked == []


def test_groq_gets_a_budget_and_a_model_without_a_limit_does_not() -> None:
    assert engineering.budget("groq") == int(engineering.FIT * 8000)
    assert engineering.budget("claude-opus") is None
    assert engineering.budget("no-such-model") is None
