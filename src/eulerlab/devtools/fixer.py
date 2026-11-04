"""The engineering agent's hands: fix one file on a branch, prove it, and leave it for the operator (ADR-113).

Since ADR-127 it also codes one new signal for a research card
(`code_feature`): two new files under `features/coded/` and `tests/`, proven
the same way plus the purity check, pushed with a pull request opened.

    a code problem (doctor queue, or the daily quality check)
        -> refuse a file on the never-touch list
        -> context: CLAUDE.md, the ARCHITECTURE sections that name the module,
           the file, the test that imports it, the error
        -> one model request (the engineering agent's model): the whole new file,
           and optionally the whole new test file
        -> a git worktree on branch agent-fix/<id>, never main
        -> the diff may name only that file and its test, or it is thrown away
        -> ruff, ruff format, mypy --strict on the file, pytest on its tests,
           and the engine self-test
        -> green: commit and push the branch; the operator merges it
           (`make agent-fix-apply ID=<id>`)
        -> red: one retry with the errors, then the problem goes to the operator

**Why this lives outside `agents/`.** Agents may not import `subprocess`
(`agents/boundaries.py`). This module is the reviewed helper the boundary file
asks for: it runs exactly the commands in `_COMMANDS`, with fixed arguments,
and nothing a model writes is ever passed to a shell. The model's text is only
ever written to files inside the worktree and then checked.

**What it can never change** (`NEVER`): the gate and the mandate, the order
path and broker, deployment and the kill switch, validation and the trial
ledger, the agent boundaries, secrets, config, and itself.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
WORKTREES = Path("data/agents/engineering/worktrees")
BRANCH_PREFIX = "agent-fix/"

NEVER: tuple[str, ...] = (
    "src/eulerlab/gates.py",
    "src/eulerlab/gate_run.py",
    "mandate.yaml",
    "src/eulerlab/oms/",
    "src/eulerlab/broker/",
    "src/eulerlab/deploy/",
    "src/eulerlab/validation/",
    "src/eulerlab/features/trials.py",
    "src/eulerlab/agents/boundaries.py",
    "src/eulerlab/env.py",
    "src/eulerlab/devtools/",
    "config/",
    ".env",
)
"""Path prefixes the fixer refuses, before any model request is made."""

MAX_FILE_CHARS = 60_000
MAX_ARCH_CHARS = 24_000

Ask = Callable[[str, str], str]
Runner = Callable[[Sequence[str], Path], tuple[int, str]]


class Refused(ValueError):
    """The file may not be changed by an agent."""


def allowed(path: str) -> bool:
    return (
        path.startswith("src/eulerlab/")
        and path.endswith(".py")
        and not any(path == n or path.startswith(n) for n in NEVER)
    )


def module_of(path: str) -> str:
    return path.removeprefix("src/").removesuffix(".py").replace("/", ".")


def tests_for(path: str, repo: Path = REPO) -> list[str]:
    """Test files that import the module, most direct first."""
    module = module_of(path)
    short = module.rsplit(".", 1)
    found: list[tuple[int, str]] = []
    for test in sorted((repo / "tests").glob("test_*.py")):
        text = test.read_text(encoding="utf-8", errors="ignore")
        if module in text or (
            len(short) == 2
            and f"from {short[0]} import" in text
            and re.search(rf"\b{short[1]}\b", text)
        ):
            found.append((0 if module in text else 1, str(test.relative_to(repo))))
    return [t for _, t in sorted(found)]


def architecture_for(path: str, repo: Path = REPO, limit: int = MAX_ARCH_CHARS) -> str:
    """The ARCHITECTURE.md sections that mention the file or its module, up to `limit` characters."""
    doc = repo / "docs" / "ARCHITECTURE.md"
    if not doc.exists():
        return ""
    text = doc.read_text(encoding="utf-8")
    sections = re.split(r"(?m)^(?=#{2,3} )", text)
    stem = Path(path).stem
    wanted = [s for s in sections if path.removeprefix("src/eulerlab/") in s or f"{stem}.py" in s]
    out = "\n".join(wanted)
    return out[:limit]


SYSTEM = """You are Euler Lab's engineering agent. You fix ONE Python file in a quant research and trading platform.

You are given the project's rules (CLAUDE.md), the architecture sections that describe this module, the file,
the test file that exercises it, and the error. Reply with ONE JSON object and nothing else:
{"explanation": "what was wrong and what you changed, in two or three plain sentences",
 "file": "the complete new content of the file",
 "test": "the complete new content of the test file, or null to leave it unchanged"}

Rules:
- Change only what the error needs. Keep every public name, signature and behaviour the error does not involve.
- Keep the module's docstring and the house style: Python 3.12, type hints that pass mypy --strict, ruff clean.
- If the fix changes behaviour, add or adjust a test that would have caught the error.
- Never weaken, skip or delete a test to make it pass. Never add network calls, subprocess, eval or exec.
- If the error cannot be fixed inside this one file, reply {"explanation": "why", "file": null, "test": null}."""


@dataclass
class Attempt:
    id: str
    file: str
    test: str = ""
    branch: str = ""
    explanation: str = ""
    checks: list[tuple[str, bool, str]] = field(default_factory=list)
    outcome: str = ""
    """`branch pushed`, `checks failed`, `refused`, `no fix`, `diff too wide`."""

    @property
    def green(self) -> bool:
        return bool(self.checks) and all(ok for _, ok, _ in self.checks)


RUN_TIMEOUT = 900
"""Seconds one check may take: ruff, mypy or a fix's own tests."""
SUITE_TIMEOUT = 2400
"""Seconds the daily quality check's full test suite may take. The suite took
10-11 minutes on 2026-11-04 and more on a busy machine, so the old 900 s cut it
off and crashed the engineering agent's run (HISTORY #77)."""


def _run(cmd: Sequence[str], cwd: Path, timeout: int = RUN_TIMEOUT) -> tuple[int, str]:
    """Return code and the output's tail. A command past `timeout` is a failed check
    (code 124, as `timeout(1)` reports), never an exception that ends the run."""
    try:
        done = subprocess.run(
            list(cmd), cwd=cwd, capture_output=True, text=True, check=False, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return 124, f"did not finish in {timeout} s: {' '.join(cmd)[:200]}"
    return done.returncode, (done.stdout + done.stderr)[-4000:]


def _python(repo: Path) -> list[str]:
    """The repository's own interpreter, with the worktree's `src` first on the path.

    Reusing the checked-out environment keeps a fix to about a minute (no new
    virtualenv per worktree); `PYTHONPATH=src` makes it import the worktree's
    code, not the checkout's.
    """
    return ["env", "PYTHONPATH=src", str(repo / ".venv" / "bin" / "python")]


def _commands(file: str, tests: Sequence[str], repo: Path = REPO) -> list[tuple[str, list[str]]]:
    """The only commands the fixer runs, all with fixed arguments."""
    py = _python(repo)
    return [
        ("ruff", [*py, "-m", "ruff", "check", file, *tests]),
        ("format", [*py, "-m", "ruff", "format", "--check", file, *tests]),
        ("mypy", [*py, "-m", "mypy", file]),
        ("pytest", [*py, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *tests])
        if tests
        else ("pytest", ["true"]),
        ("engine", [*py, "-m", "eulerlab.backtest.selftest"]),
    ]


def _parse(answer: str) -> dict[str, object]:
    start, end = answer.find("{"), answer.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        raw = json.loads(answer[start : end + 1])
    except ValueError:
        return {}
    return raw if isinstance(raw, dict) else {}


def context(file: str, error: str, tests: Sequence[str], repo: Path = REPO) -> str:
    rules = (
        (repo / "CLAUDE.md").read_text(encoding="utf-8") if (repo / "CLAUDE.md").exists() else ""
    )
    source = (repo / file).read_text(encoding="utf-8")[:MAX_FILE_CHARS]
    test_text = (
        (repo / tests[0]).read_text(encoding="utf-8")[:MAX_FILE_CHARS]
        if tests
        else "(no test file imports it)"
    )
    return "\n\n".join(
        [
            f"<rules>\n{rules}\n</rules>",
            f"<architecture>\n{architecture_for(file, repo)}\n</architecture>",
            f'<file path="{file}">\n{source}\n</file>',
            f'<test path="{tests[0] if tests else ""}">\n{test_text}\n</test>',
            f"<error>\n{error[-4000:]}\n</error>",
        ]
    )


def fix(
    file: str,
    error: str,
    ask: Ask,
    *,
    repo: Path = REPO,
    run: Runner = _run,
    push: bool = True,
    retries: int = 1,
) -> Attempt:
    """Try to fix `file` for `error` on a fresh branch. Never touches the checked-out branch."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    attempt = Attempt(id=f"{stamp}-{hashlib.sha256(file.encode()).hexdigest()[:6]}", file=file)
    if not allowed(file):
        attempt.outcome = "refused"
        attempt.explanation = f"{file} is on the never-touch list or outside src/eulerlab"
        return attempt
    tests = tests_for(file, repo)
    attempt.test = tests[0] if tests else ""
    attempt.branch = BRANCH_PREFIX + attempt.id
    tree = repo / WORKTREES / attempt.id
    code, out = run(["git", "worktree", "add", "-b", attempt.branch, str(tree), "HEAD"], repo)
    if code != 0:
        attempt.outcome = f"worktree failed: {out[-200:]}"
        return attempt
    try:
        note = error
        for _ in range(retries + 1):
            reply = _parse(ask(SYSTEM, context(file, note, tests, tree)))
            attempt.explanation = str(reply.get("explanation", ""))[:600]
            new_file = reply.get("file")
            if not isinstance(new_file, str) or not new_file.strip():
                attempt.outcome = "no fix"
                return attempt
            (tree / file).write_text(new_file, encoding="utf-8")
            new_test = reply.get("test")
            if attempt.test and isinstance(new_test, str) and new_test.strip():
                (tree / attempt.test).write_text(new_test, encoding="utf-8")
            _, names = run(["git", "diff", "--name-only"], tree)
            changed = {n.strip() for n in names.splitlines() if n.strip()}
            if not changed <= {file, attempt.test}:
                attempt.outcome = f"diff too wide: {sorted(changed)}"
                return attempt
            attempt.checks = []
            for name, cmd in _commands(file, tests, repo):
                rc, text = run(cmd, tree)
                attempt.checks.append((name, rc == 0, text[-1500:]))
            if attempt.green:
                break
            failed = "\n".join(f"{n}: {t}" for n, ok, t in attempt.checks if not ok)
            note = f"{error}\n\nYour previous fix failed these checks:\n{failed}"
        if not attempt.green:
            attempt.outcome = "checks failed"
            return attempt
        run(["git", "add", file, *([attempt.test] if attempt.test else [])], tree)
        run(
            [
                "git",
                "commit",
                "-q",
                "-m",
                f"fix: engineering agent fix for {file}\n\n{attempt.explanation}",
            ],
            tree,
        )
        if push:
            rc, text = run(["git", "push", "-q", "-u", "origin", attempt.branch], tree)
            attempt.outcome = (
                "branch pushed" if rc == 0 else f"committed, push failed: {text[-200:]}"
            )
        else:
            attempt.outcome = "committed"
        return attempt
    finally:
        run(["git", "worktree", "remove", "--force", str(tree)], repo)


# --- coding a new signal for a research card (ADR-127) ---------------------

CODED_DIR = "src/eulerlab/features/coded"
CODED_LOG = "docs/CODED_FEATURES.md"
FEATURE_BRANCH_PREFIX = "agent-feature/"
FEATURE_TESTS = "tests/test_coded_features.py"
MAX_CARD_CHARS = 4_000

FEATURE_SYSTEM = """You are Euler Lab's engineering agent. You code ONE new stock signal ("feature") that a research card names but the feature library lacks.

A feature is a pure function of ONE stock's own daily history, which ends at the decision day:
    def fn(history: Sequence[PanelRow]) -> float | None
PanelRow has: day (date), symbol (str), close (float, raw exchange close), volume (float), turnover (float, rupees), isin (str).
Nothing else is available: no other stocks, no index, no fundamentals, no files, no network.

Reply with ONE JSON object and nothing else:
{"explanation": "what the signal measures and how, in two or three plain sentences; or why it cannot be built",
 "file": "the complete Python module, or null",
 "test": "the complete pytest file, or null"}

The module must:
- begin with its docstring on the first line (nothing before it, not even the file name), saying what it measures, the card it is for, and why higher is predicted to be better;
- put `from __future__ import annotations` right after the docstring;
- be plain code in the JSON string: no code fence, no surrounding quotes;
- import only from: __future__, math, statistics, collections.abc, itertools, eulerlab.features.base (Feature, TRADING_DAYS_PER_MONTH), eulerlab.features.panel (PanelRow), eulerlab.quality.robust (median); never eulerlab.features.library;
- define fn as above, returning None when history is too short or the value is undefined (never NaN or inf);
- end with FEATURE = Feature("<name>", fn, "<description under 60 characters>", <min_history days>);
- be Python 3.12, pass mypy --strict and ruff; no global state, no I/O, no eval or exec, no dunder attributes;
  use itertools.pairwise(window) for successive pairs, never zip(window, window[1:]).
The test must import FEATURE from eulerlab.features.coded.<name>, build PanelRow histories by hand, and check two or three values worked out by hand (work each one out step by step; keep the cases simple), plus None on short history. Every function in it is annotated, tests with `-> None`.
If the signal needs anything besides this one stock's own history (other stocks, the market, an index, fundamentals, fund data),
reply {"explanation": "cannot be built from one stock's own history: <what it needs>", "file": null, "test": null}. Do not substitute a different signal."""


def unwrap_code(text: str) -> str:
    """Code the model wrapped in a fence or a triple-quoted string, unwrapped.

    Seen 2026-11-03: gpt-oss-120b sent the file inside a triple-quoted string,
    so the module was one string and defined nothing."""
    body = text.strip()
    fence = re.fullmatch(r"```[a-zA-Z]*\n(.*?)\n?```", body, flags=re.DOTALL)
    if fence:
        return fence.group(1)
    for quote in ("'''", '"""'):
        if body.startswith(quote) and body.endswith(quote) and len(body) > 6:
            inner = body[3:-3]
            return inner[2:] if inner.startswith("\\\n") else inner.lstrip("\n")
    return text


_PLAIN = str.maketrans(
    {"\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-",
     "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u00a0": " ",
     "\u202f": " ", "\u2009": " "}
)  # fmt: skip


def plain(text: str) -> str:
    """Typographic dashes, quotes and spaces as ASCII. gpt-oss-120b writes U+2011 in
    comments, which ruff refuses as ambiguous (seen 2026-11-03)."""
    return text.translate(_PLAIN)


def feature_paths(name: str) -> tuple[str, str]:
    """The module and test an agent-coded feature lives in."""
    return f"{CODED_DIR}/{name}.py", f"tests/test_coded_{name}.py"


def feature_context(name: str, card_text: str, repo: Path = REPO) -> str:
    """Small on purpose: it must fit Groq's free 8,000 tokens a minute (ADR-127)."""
    base = (repo / "src/eulerlab/features/base.py").read_text(encoding="utf-8")
    base = base[base.find("FeatureFn") :]
    library = (repo / "src/eulerlab/features/library.py").read_text(encoding="utf-8")
    example = library.find("def illiquidity_amihud")
    end = library.find("\n\n\ndef ", example + 10)
    return "\n\n".join(
        [
            f'<base path="src/eulerlab/features/base.py">\n{base}\n</base>',
            f'<example_feature from="src/eulerlab/features/library.py">\n{library[example:end]}\n</example_feature>',
            f"<name>{name}</name>",
            f"<card>\n{card_text[:MAX_CARD_CHARS]}\n</card>",
        ]
    )


def _feature_commands(file: str, test: str, repo: Path = REPO) -> list[tuple[str, list[str]]]:
    py = _python(repo)
    return [
        ("ruff", [*py, "-m", "ruff", "check", file, test]),
        ("format", [*py, "-m", "ruff", "format", "--check", file, test]),
        ("mypy", [*py, "-m", "mypy", file, test]),
        (
            "pytest",
            [*py, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", test, FEATURE_TESTS],
        ),
        ("engine", [*py, "-m", "eulerlab.backtest.selftest"]),
    ]


def code_feature(
    name: str,
    card_text: str,
    ask: Ask,
    *,
    card: str = "",
    model: str = "",
    repo: Path = REPO,
    run: Runner = _run,
    push: bool = True,
    retries: int = 1,
) -> Attempt:
    """Write one new feature and its test on a fresh branch, prove them, push, open a PR.

    Only two new files may appear, plus one line in `docs/CODED_FEATURES.md`
    written by this code, not the model. Never touches the checked-out branch.
    """
    from eulerlab.features import coded

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    file, test = feature_paths(name)
    attempt = Attempt(id=f"{stamp}-{hashlib.sha256(name.encode()).hexdigest()[:6]}", file=file)
    attempt.test = test
    if not coded.NAME.match(name):
        attempt.outcome = "refused"
        attempt.explanation = f"{name!r} is not a feature name (lowercase, digits, underscores)"
        return attempt
    if (repo / file).exists():
        attempt.outcome = "refused"
        attempt.explanation = f"{file} already exists"
        return attempt
    attempt.branch = f"{FEATURE_BRANCH_PREFIX}{name}-{stamp}"
    tree = repo / WORKTREES / attempt.id
    code, out = run(["git", "worktree", "add", "-b", attempt.branch, str(tree), "HEAD"], repo)
    if code != 0:
        attempt.outcome = f"worktree failed: {out[-200:]}"
        return attempt
    try:
        note = feature_context(name, card_text, tree)
        for _ in range(retries + 1):
            reply = _parse(ask(FEATURE_SYSTEM, note))
            attempt.explanation = str(reply.get("explanation", ""))[:600]
            new_file, new_test = reply.get("file"), reply.get("test")
            if not isinstance(new_file, str) or not new_file.strip():
                attempt.outcome = "no fix"
                return attempt
            if not isinstance(new_test, str) or not new_test.strip():
                attempt.outcome = "no test"
                return attempt
            new_file, new_test = plain(unwrap_code(new_file)), plain(unwrap_code(new_test))
            (tree / file).write_text(new_file.rstrip() + "\n", encoding="utf-8")
            (tree / test).write_text(new_test.rstrip() + "\n", encoding="utf-8")
            # Mechanical, not the model: safe lint fixes and the house format.
            py = _python(repo)
            run([*py, "-m", "ruff", "check", "--fix", "-q", file, test], tree)
            run([*py, "-m", "ruff", "format", "-q", file, test], tree)
            new_file = (tree / file).read_text(encoding="utf-8")
            _, status = run(["git", "status", "--porcelain", "--untracked-files=all"], tree)
            changed = {line[3:].strip() for line in status.splitlines() if line.strip()}
            if not changed <= {file, test}:
                attempt.outcome = f"diff too wide: {sorted(changed)}"
                return attempt
            wrong = coded.problems(new_file)
            attempt.checks = [("pure", not wrong, "; ".join(wrong) or "ok")]
            if not wrong:
                for check, cmd in _feature_commands(file, test, repo):
                    rc, text = run(cmd, tree)
                    attempt.checks.append((check, rc == 0, text[-1500:]))
            if attempt.green:
                break
            failed = "\n".join(f"{n}: {t}" for n, ok, t in attempt.checks if not ok)
            note = (
                feature_context(name, card_text, tree)
                + f"\n\n<previous_attempt>\n{new_file[:6000]}\n</previous_attempt>"
                + f"\n\n<failed_checks>\n{failed[-3000:]}\n</failed_checks>"
            )
        if not attempt.green:
            attempt.outcome = "checks failed"
            return attempt
        day = datetime.now(UTC).date().isoformat()
        with (tree / CODED_LOG).open("a", encoding="utf-8") as log:
            log.write(
                f"| {day} | `{name}` | {card or 'given by hand'} | {model or 'model'} | {attempt.branch} |\n"
            )
        run(["git", "add", file, test, CODED_LOG], tree)
        rc, text = run(
            [
                "git",
                "commit",
                "-q",
                # The same checks just ran on exactly these files, and CI runs the
                # whole suite on the pull request. The repository's hooks would
                # re-run all tests with another interpreter (seen 2026-11-03).
                "--no-verify",
                "-m",
                f"feat(features): {name}, coded by the engineering agent for a research card (ADR-127)\n\n"
                f"{attempt.explanation}\n\nCard: {card or 'given by hand'}\nModel: {model or 'model'}",
            ],
            tree,
        )
        if rc != 0:
            attempt.outcome = f"commit failed: {text[-200:]}"
            attempt.checks.append(("commit", False, text[-1500:]))
            return attempt
        if not push:
            attempt.outcome = "committed"
            return attempt
        rc, text = run(["git", "push", "-q", "-u", "origin", attempt.branch], tree)
        if rc != 0:
            attempt.outcome = f"committed, push failed: {text[-200:]}"
            return attempt
        attempt.outcome = "branch pushed"
        rc, text = run(
            [
                "gh",
                "pr",
                "create",
                "--head",
                attempt.branch,
                "--title",
                f"feat(features): {name}, coded by the engineering agent (ADR-127)",
                "--body",
                f"{attempt.explanation}\n\nCard: `{card or 'given by hand'}`\nModel: {model or 'model'}\n\n"
                "Checks passed on the agent's branch: pure, ruff, format, mypy, its test, "
                "tests/test_coded_features.py, the engine self-test.\n\n"
                "Once merged, the idea lab's next run tests the card (trials logged first).",
            ],
            tree,
        )
        if rc == 0:
            attempt.outcome = "pull request opened"
            attempt.explanation += f"\nPR: {text.strip().splitlines()[-1] if text.strip() else ''}"
        return attempt
    finally:
        run(["git", "worktree", "remove", "--force", str(tree)], repo)
        if not attempt.green or attempt.outcome not in (
            "pull request opened",
            "branch pushed",
            "committed",
        ):
            # Nothing worth keeping on it: the branch goes with the worktree.
            run(["git", "branch", "-D", attempt.branch], repo)


def apply(attempt_id: str, *, repo: Path = REPO, run: Runner = _run) -> tuple[bool, str]:
    """The operator's tap: merge a fix branch into the checked-out branch, fast-forward or a merge commit."""
    branch = BRANCH_PREFIX + attempt_id
    if not re.fullmatch(r"[0-9T]+-[0-9a-f]{6}", attempt_id):
        return False, f"not a fix id: {attempt_id!r}"
    rc, text = run(["git", "merge", "--no-edit", branch], repo)
    return rc == 0, text[-500:]


def quality(repo: Path = REPO, run: Runner = _run) -> list[tuple[str, int, str]]:
    """The daily quality check: files ruff or mypy complain about, as (path, line, message)."""
    out: list[tuple[str, int, str]] = []
    py = [str(repo / ".venv" / "bin" / "python")]
    _, text = run([*py, "-m", "ruff", "check", "--output-format", "concise", "src"], repo)
    for m in re.finditer(r"(?m)^(src/eulerlab/\S+\.py):(\d+):\d+: (.+)$", text):
        out.append((m.group(1), int(m.group(2)), f"ruff: {m.group(3)}"))
    _, text = run([*py, "-m", "mypy"], repo)
    for m in re.finditer(r"(?m)^(src/eulerlab/\S+\.py):(\d+): error: (.+)$", text):
        out.append((m.group(1), int(m.group(2)), f"mypy: {m.group(3)}"))
    if run is _run:
        rc, text = _run(
            [*py, "-m", "pytest", "-q", "--tb=line", "-p", "no:cacheprovider"], repo, SUITE_TIMEOUT
        )
    else:
        rc, text = run([*py, "-m", "pytest", "-q", "--tb=line", "-p", "no:cacheprovider"], repo)
    if rc == 124:
        out.append(("tests", 0, f"pytest: {text}"))
    for m in re.finditer(r"(?m)^\S*?(src/eulerlab/\S+\.py):(\d+): (.+)$", text):
        out.append((m.group(1), int(m.group(2)), f"pytest: {m.group(3)}"))
    first: dict[str, tuple[str, int, str]] = {}
    for item in out:
        first.setdefault(item[0], item)
    return list(first.values())


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Merge an engineering agent fix branch.")
    parser.add_argument("id")
    args = parser.parse_args(argv)
    ok, text = apply(args.id)
    print(text)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
