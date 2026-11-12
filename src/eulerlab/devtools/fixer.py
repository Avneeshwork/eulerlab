"""The engineering agent's hands: fix one file on a branch, prove it, and leave it for the operator (ADR-113).

Since ADR-127 it also codes one new signal for a research card
(`code_feature`): two new files under `features/coded/` and `tests/`, proven
the same way plus the purity check, pushed with a pull request opened.

    a code problem (doctor queue, or the daily quality check)
        -> refuse a file on the never-touch list
        -> context: CLAUDE.md, the ARCHITECTURE sections that name the module,
           the file, the test that imports it, the error
           (with a per-minute token budget, as on Groq's free tier: the small
           context instead, see "Fitting a small model" below)
        -> one model request (the engineering agent's model): the whole new file,
           and optionally the whole new test file; or, in the small context,
           exact find-and-replace edits
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

**Fitting a small model** (2026-11-05, HISTORY #78). A bug fix used to send
the whole CLAUDE.md, the module and its test, about 12,000 tokens, past Groq's
free 8,000 a minute, so every fix fell to a paid model. With a `budget`,
`fix` sends `small_context`: the hard rules only (`rules_digest`), the module's
header and the function the error names (`excerpt`), the tests that mention it,
and the error; the model answers with edits (`EDIT_SYSTEM`) that must each match
the file exactly once (`apply_edits`). If the checks fail it tries once more with
the check output and a wider window. The proofs are the same in every mode.

**What it can never change** (`NEVER`): the gate and the mandate, the order
path and broker, deployment and the kill switch, validation and the trial
ledger, the agent boundaries, secrets, config, and itself.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from eulerlab.paths import data_path

REPO = Path(__file__).resolve().parents[3]
WORKTREES = data_path("agents/engineering/worktrees")
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


EDIT_SYSTEM = """You are Euler Lab's engineering agent. You fix ONE Python file in a quant research and trading platform.

You are given the project's hard rules, an EXCERPT of the file (its header and the part the error points at;
"# ... lines N-M not shown ..." marks what is left out), the tests that use that part, and the error.
Reply with ONE JSON object and nothing else:
{"explanation": "what was wrong and what you changed, in two or three plain sentences",
 "edits": [{"find": "text copied EXACTLY from the excerpt, enough lines to be unique", "replace": "the new text"}],
 "test_edits": [{"find": "...", "replace": "..."}] or null,
 "test_append": "new test functions to add at the end of the test file, or null"}

Rules:
- Each "find" must be copied character for character from the excerpt, whitespace included, and appear once in the file.
- Change only what the error needs. Keep every public name, signature and behaviour the error does not involve.
- Python 3.12, type hints that pass mypy --strict, ruff clean. If you add an import, add it with an edit to the header.
- If the fix changes behaviour, add a test (test_append) that would have caught the error.
- Never weaken, skip or delete a test to make it pass. Never add network calls, subprocess, eval or exec.
- If the error cannot be fixed inside this file, reply {"explanation": "why", "edits": []}."""

RULE_SECTIONS = ("### Truth", "### Data integrity", "### Code")
MAX_RULES_CHARS = 3_500
OUTPUT_RESERVE = 1_800
"""Tokens kept free in the budget for the model's answer."""


def tokens(text: str) -> int:
    """About how many tokens `text` is: four characters each, the usual rule of thumb."""
    return len(text) // 4


def rules_digest(repo: Path = REPO, limit: int = MAX_RULES_CHARS) -> str:
    """The hard rules a code change must keep, from CLAUDE.md: truth, data integrity, code."""
    doc = repo / "CLAUDE.md"
    if not doc.exists():
        return ""
    text = doc.read_text(encoding="utf-8")
    parts = re.split(r"(?m)^(?=#{2,3} )", text)
    kept = [s.strip() for s in parts if s.startswith(RULE_SECTIONS)]
    return "\n\n".join(kept)[:limit]


def error_lines(file: str, error: str) -> list[int]:
    """Line numbers in `file` that the error names: traceback frames and `path:line:` findings."""
    name = re.escape(Path(file).name)
    found = [int(m) for m in re.findall(rf'{name}", line (\d+)', error)]
    found += [int(m) for m in re.findall(rf"{re.escape(file)}:(\d+)", error)]
    return sorted(set(found))


def _spans(source: str, lines: Sequence[int], pad: int) -> list[tuple[int, int]]:
    """1-based inclusive line spans to show: the innermost function or class around each line, padded."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        tree = None
    total = len(source.splitlines())
    spans: list[tuple[int, int]] = []
    for line in lines:
        best: tuple[int, int] | None = None
        for node in ast.walk(tree) if tree is not None else []:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
                end = node.end_lineno or node.lineno
                if start <= line <= end and (best is None or end - start < best[1] - best[0]):
                    best = (start, end)
        lo, hi = best if best is not None else (line, line)
        spans.append((max(1, lo - pad), min(total, hi + pad)))
    spans.sort()
    merged: list[tuple[int, int]] = []
    for lo, hi in spans:
        if merged and lo <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(hi, merged[-1][1]))
        else:
            merged.append((lo, hi))
    return merged


def _header_end(source: str) -> int:
    """The last line of the module header: docstring, imports and constants before the first def or class."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return min(40, len(source.splitlines()))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            return max(0, min([node.lineno, *(d.lineno for d in node.decorator_list)]) - 1)
    return len(source.splitlines())


def excerpt(source: str, lines: Sequence[int], pad: int, header_limit: int = 80) -> str:
    """The module's header and the spans around `lines`, with markers for what is left out.

    With no line to point at, the whole file is returned: there is nothing to narrow to."""
    src = source.splitlines()
    if not lines:
        return source
    head = min(_header_end(source), header_limit)
    chunks: list[str] = []
    shown = 0
    for lo, hi in [(1, head), *_spans(source, lines, pad)] if head else _spans(source, lines, pad):
        lo = max(lo, shown + 1)
        if lo > hi:
            continue
        if lo > shown + 1:
            chunks.append(f"# ... lines {shown + 1}-{lo - 1} not shown ...")
        chunks.append("\n".join(src[lo - 1 : hi]))
        shown = hi
    if shown < len(src):
        chunks.append(f"# ... lines {shown + 1}-{len(src)} not shown ...")
    return "\n".join(chunks)


def shown_names(source: str, lines: Sequence[int], pad: int) -> set[str]:
    """Names of the functions and classes the excerpt shows."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    spans = _spans(source, lines, pad)
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) and any(
            lo <= node.lineno <= hi for lo, hi in spans
        ):
            out.add(node.name)
    return out


def related_tests(test_source: str, names: set[str], limit: int) -> str:
    """The test functions that mention any of `names`, up to `limit` characters."""
    try:
        tree = ast.parse(test_source)
    except SyntaxError:
        return test_source[:limit]
    src = test_source.splitlines()
    picked: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith(
            "test"
        ):
            body = "\n".join(src[node.lineno - 1 : node.end_lineno or node.lineno])
            if not names or any(re.search(rf"\b{re.escape(n)}\b", body) for n in names):
                picked.append(body)
    out = "\n\n".join(picked)
    return out[:limit] if out else "(no test mentions the code shown)"


def small_context(
    file: str, error: str, tests: Sequence[str], budget: int, pad: int = 10, repo: Path = REPO
) -> str | None:
    """The smallest useful request for `file`, fitted to `budget` tokens; None if it cannot fit.

    Pieces are dropped in order until it fits: first the tests shrink, then the
    window narrows, then the error is cut to its last lines."""
    source = (repo / file).read_text(encoding="utf-8")
    lines = error_lines(file, error)
    test_text = (repo / tests[0]).read_text(encoding="utf-8") if tests else ""
    rules = rules_digest(repo)
    for test_limit, width, tail in ((6000, pad, 3000), (2500, pad, 2000), (0, 3, 1200)):
        body = excerpt(source, lines, width)
        names = shown_names(source, lines, width)
        related = related_tests(test_text, names, test_limit) if test_text and test_limit else ""
        text = "\n\n".join(
            [
                f"<rules>\n{rules}\n</rules>",
                f'<file path="{file}" excerpt="true">\n{body}\n</file>',
                f'<tests path="{tests[0] if tests else ""}">\n{related or "(not shown)"}\n</tests>',
                f"<error>\n{error[-tail:]}\n</error>",
            ]
        )
        if tokens(EDIT_SYSTEM) + tokens(text) + OUTPUT_RESERVE <= budget:
            return text
    return None


class EditFailed(ValueError):
    """A find text did not match the file exactly once."""


def apply_edits(text: str, edits: object) -> str:
    """`text` with each edit applied in order; each `find` must occur exactly once."""
    if not isinstance(edits, list):
        raise EditFailed("edits is not a list")
    for edit in edits:
        if not isinstance(edit, dict):
            raise EditFailed("an edit is not an object")
        find, replace = edit.get("find"), edit.get("replace")
        if not isinstance(find, str) or not isinstance(replace, str) or not find:
            raise EditFailed("an edit needs a non-empty find and a replace")
        count = text.count(find)
        if count != 1:
            raise EditFailed(f"find text matched {count} times, not once: {find[:120]!r}")
        text = text.replace(find, replace, 1)
    return text


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
    budget: int | None = None,
) -> Attempt:
    """Try to fix `file` for `error` on a fresh branch. Never touches the checked-out branch.

    `budget`: the model's tokens per request (its per-minute limit, with a
    margin). With one, the small context and edits are used, a second try
    widening the window; without one, the whole file as before."""
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
        pads = [10, 60][: retries + 1]
        for round_ in range(retries + 1):
            if budget is not None:
                small = small_context(file, note, tests, budget, pad=pads[round_], repo=tree)
                if small is None:
                    attempt.outcome = "too big for this model"
                    attempt.explanation = (
                        f"even the smallest request does not fit {budget:,} tokens; "
                        "a model with a larger limit is needed"
                    )
                    return attempt
                reply = _parse(ask(EDIT_SYSTEM, small))
                attempt.explanation = str(reply.get("explanation", ""))[:600]
                edits = reply.get("edits")
                if not edits:
                    attempt.outcome = "no fix"
                    return attempt
                try:
                    current = (tree / file).read_text(encoding="utf-8")
                    (tree / file).write_text(apply_edits(current, edits), encoding="utf-8")
                    if attempt.test:
                        test_path = tree / attempt.test
                        test_now = test_path.read_text(encoding="utf-8")
                        if reply.get("test_edits"):
                            test_now = apply_edits(test_now, reply.get("test_edits"))
                        extra = reply.get("test_append")
                        if isinstance(extra, str) and extra.strip():
                            test_now = test_now.rstrip("\n") + "\n\n\n" + extra.strip() + "\n"
                        test_path.write_text(test_now, encoding="utf-8")
                except EditFailed as exc:
                    run(["git", "checkout", "--", "."], tree)
                    attempt.checks = [("edits", False, str(exc))]
                    note = f"{error}\n\nYour previous edits could not be applied: {exc}"
                    continue
            else:
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
            if budget is not None:
                # The next round starts from the original file, with a wider window.
                run(["git", "checkout", "--", "."], tree)
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
