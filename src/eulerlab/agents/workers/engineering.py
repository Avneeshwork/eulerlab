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


def run(ctx: Context) -> WorkerResult:
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
