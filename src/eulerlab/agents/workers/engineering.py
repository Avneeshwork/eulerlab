"""The engineering agent: reviews a branch against the house rules, and drafts code you merge.

**Review** (no model, every run). The rules CLAUDE.md states and CI cannot
all check:

- `gates.py` or `mandate.yaml` changed → critical. They are operator-owned.
- `src/` changed with no docs → critical (the same rule as `make docs-check`).
- A new or changed module under `src/` with no test file touched → warn.
- An agent module importing the order path, the gate or the ledger → critical
  (`agents/boundaries.py`).
- An `# ASSUMPTION:` comment with no `A-NNN` id → warn: it must have a row in
  `docs/ASSUMPTIONS.md`.

**Fix** (`mode=fix`, Claude Opus, ADR-113). It takes the code problems the
doctor queued (an agent run that crashed, named by the deepest `src/eulerlab`
frame) and the daily quality check's findings (`mode=quality`), and hands each
to `devtools/fixer.py`: one file and its test, on an `agent-fix/<id>` branch,
proven by ruff, mypy, the file's tests and the engine self-test. A green fix
waits in the inbox for the operator's merge (`make agent-fix-apply ID=<id>`);
it never reaches the checked-out branch by itself. It refuses to run on a
weaker model than the one its definition names.

**Draft** (`primitive=<description>`, with a model). It drafts a new feature
for `features/library.py` and its test, in the library's own conventions, and
writes them to its run folder as a proposal. It never applies them: the
operator, or a coding session the operator starts, turns a proposal into a
branch and a pull request, and CI and review decide whether it lands.
"""

from __future__ import annotations

import re
from pathlib import Path

from eulerlab.agents import boundaries
from eulerlab.agents.runtime import Context, Item, WorkerResult, untrusted

OPERATOR_OWNED = ("src/eulerlab/gates.py", "mandate.yaml")
ASSUMPTION = re.compile(r"#\s*ASSUMPTION:(?!\s*A-\d{3})")
LIBRARY = Path("src/eulerlab/features/library.py")


def review(files: list[str], *, docs_ok: bool, repo: Path = Path()) -> list[Item]:
    items: list[Item] = []
    owned = [f for f in files if f in OPERATOR_OWNED]
    if owned:
        items.append(
            Item(
                kind="review",
                title=f"operator-owned file changed: {', '.join(owned)}",
                body="CLAUDE.md: gates.py and mandate.yaml change only on the operator's explicit instruction in that session.",
                severity="critical",
                needs_approval=True,
            )
        )
    if not docs_ok:
        items.append(
            Item(
                kind="review",
                title="src/ changed with no documentation",
                body="make docs-check",
                severity="critical",
            )
        )
    src = [f for f in files if f.startswith("src/") and f.endswith(".py")]
    tests = [f for f in files if f.startswith("tests/")]
    if src and not tests:
        items.append(
            Item(
                kind="review",
                title=f"{len(src)} source file(s) changed and no test changed",
                body="\n".join(src[:20]),
                severity="warn",
            )
        )
    for module in boundaries.agent_modules():
        for violation in boundaries.violations(module):
            items.append(Item(kind="review", title=violation, severity="critical"))
    for name in src:
        path = repo / name
        if not path.exists():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if ASSUMPTION.search(line):
                items.append(
                    Item(
                        kind="review",
                        title=f"{name}:{number} has an ASSUMPTION with no A-NNN id",
                        body=line.strip()[:200],
                        severity="warn",
                    )
                )
    return items


def _branch() -> tuple[list[str], bool]:
    from tools import docs_check

    return docs_check.branch_files(), not docs_check.collect_violations()


FIX_MODEL = "claude-opus"
"""The provider fixes must run on. A fallback to a weaker model is refused, not used."""


def fixes(ctx: Context, *, limit: int) -> list[Item]:
    """Work the doctor's code queue: one fix attempt per file, up to `limit`."""
    from eulerlab.agents import doctor
    from eulerlab.agents.runtime import resolve_provider
    from eulerlab.devtools import fixer

    queue = doctor.queued(ctx.root)
    if not queue:
        return []
    wanted = ctx.agent.spec.provider or FIX_MODEL
    if ctx.asker is None and resolve_provider(wanted) != wanted:
        return [
            Item(
                kind="alert",
                title=f"{len(queue)} code problem(s) waiting: the fix model ({wanted}) is not reachable",
                body="Add the Anthropic key to .env (see config/llm.yaml). Fixes are not tried on a "
                "weaker model.",
                severity="warn",
            )
        ]
    items: list[Item] = []
    for problem in queue[:limit]:
        if not ctx.can_ask():
            break
        ctx.step(f"Fixing {problem.file} for {problem.agent}: {problem.detail[:80]}")
        attempt = fixer.fix(problem.file, problem.error or problem.detail, ctx.ask)
        doctor.done(problem.file, attempt.outcome, ctx.root)
        checks = ", ".join(f"{n} {'ok' if ok else 'FAILED'}" for n, ok, _ in attempt.checks)
        if attempt.green and attempt.outcome in ("branch pushed", "committed"):
            items.append(
                Item(
                    kind="proposal",
                    title=f"fix ready for {problem.file}"[:200],
                    body="\n".join(
                        [
                            attempt.explanation,
                            f"branch: {attempt.branch}",
                            f"checks: {checks}",
                            f"to merge it: make agent-fix-apply ID={attempt.id}",
                        ]
                    ),
                    needs_approval=True,
                    ref=attempt.branch,
                    data={"fix_id": attempt.id, "file": problem.file, "test": attempt.test},
                )
            )
        else:
            items.append(
                Item(
                    kind="finding",
                    title=f"could not fix {problem.file}: {attempt.outcome}"[:200],
                    body="\n".join([problem.detail, attempt.explanation, f"checks: {checks}"]),
                    severity="warn",
                    needs_approval=True,
                    data={"file": problem.file, "outcome": attempt.outcome},
                )
            )
    return items


def quality(ctx: Context) -> int:
    """The daily check: lint, types and tests; each failing file joins the doctor's code queue."""
    from eulerlab.agents import doctor
    from eulerlab.devtools import fixer

    found = fixer.quality()
    doctor.treat(
        [
            doctor.Problem(
                "code_error", "quality", "daily", message, file=path, line=line, error=message
            )
            for path, line, message in found
            if fixer.allowed(path)
        ],
        ctx.root,
    )
    return len(found)


def run(ctx: Context) -> WorkerResult:
    mode = str(ctx.args.get("mode") or "").strip()
    if mode in ("fix", "quality"):
        items: list[Item] = []
        found = 0
        if mode == "quality":
            ctx.step("Running lint, types and tests")
            found = quality(ctx)
        limit = int(ctx.args.get("max_fixes") or ctx.options.get("max_fixes") or 3)
        items = fixes(ctx, limit=limit)
        ready = sum(1 for i in items if i.kind == "proposal")
        return WorkerResult(
            (f"{found} quality finding(s); " if mode == "quality" else "")
            + f"{ready} fix(es) ready for you, {len(items) - ready} could not be fixed",
            items,
            data={"mode": mode, "found": found},
        )
    ctx.step("Reviewing the files changed on this branch")
    try:
        files, docs_ok = _branch()
    except Exception as exc:  # not a git checkout, or git missing
        files, docs_ok = [], True
        ctx.notes.append(f"branch not read: {type(exc).__name__}: {str(exc)[:120]}")
    items = review(files, docs_ok=docs_ok)

    wanted = str(ctx.args.get("primitive") or "").strip()
    if wanted:
        if not ctx.can_ask():
            items.append(
                Item(
                    kind="proposal",
                    title="no model budget left to draft a primitive",
                    severity="warn",
                )
            )
        else:
            library_head = LIBRARY.read_text(encoding="utf-8")[:9000] if LIBRARY.exists() else ""
            text = ctx.ask(
                "You draft one new feature for Euler Lab's feature library, in its exact conventions: "
                "a pure function `(history: Sequence[PanelRow]) -> float | None`, higher means better, "
                "None when history is too short, a docstring that says what it measures and why, no "
                "lookahead (only `history`, which ends at the decision day), no I/O, no imports beyond "
                "the library's own. Then a pytest test file for it with two or three hand-built cases. "
                "Reply with two fenced blocks: ```python feature``` then ```python test```. Nothing else.",
                untrusted("library", library_head)
                + "\n\nThe feature wanted:\n"
                + untrusted("request", wanted, 2000),
            )
            blocks = re.findall(r"```python\s*(.*?)```", text, flags=re.DOTALL)
            if len(blocks) >= 2:
                ctx.write("feature.py.txt", blocks[0])
                ctx.write("test_feature.py.txt", blocks[1])
                items.append(
                    Item(
                        kind="proposal",
                        title=f"draft primitive: {wanted[:120]}",
                        body=(
                            "Two files in this run's folder: feature.py.txt and test_feature.py.txt.\n"
                            "Nothing was applied or run. To use it: read both, then put them on a branch "
                            "and open a pull request; CI and review decide."
                        ),
                        needs_approval=True,
                        ref=str(ctx.out_dir),
                    )
                )
            else:
                items.append(
                    Item(
                        kind="proposal",
                        title="the model's draft did not have two code blocks",
                        severity="warn",
                        body=text[:500],
                    )
                )

    critical = sum(1 for i in items if i.severity == "critical")
    return WorkerResult(
        f"{len(files)} file(s) on the branch; {critical} critical, {sum(1 for i in items if i.severity == 'warn')} warnings",
        items,
        data={"files": files, "docs_ok": docs_ok},
    )
