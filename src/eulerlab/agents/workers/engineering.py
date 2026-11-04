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

**Code a signal** (`mode=feature`, `feature=<name>`, `card=<card.yaml>`, ADR-127).
A research card names a signal the library lacks, so the idea lab skips it.
`devtools/fixer.code_feature` writes it as `features/coded/<name>.py` with its
test, proves it (purity check, ruff, mypy, its test, the shared coded-feature
test, the engine self-test), pushes `agent-feature/<name>-...` and opens a pull
request. The operator merges; the lab's next run tests the card.

**Which model.** `options.models`, in order: free Groq first, then Claude Opus
if Groq is unreachable, its request would not fit Groq's free per-minute limit,
or its code failed the checks (operator, 2026-11-03: "ensure engineering agent
can use free model too"). The checks are the same whichever model wrote it.
A bug fix sends the whole CLAUDE.md and the module, which is past Groq's free
limit, so fixes still run on Opus in practice.

**Draft** (`primitive=<description>`, with a model). It drafts a new feature
for `features/library.py` and its test, in the library's own conventions, and
writes them to its run folder as a proposal. It never applies them: the
operator, or a coding session the operator starts, turns a proposal into a
branch and a pull request, and CI and review decide whether it lands.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

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
"""The provider used when `options.models` names none."""

FIT = 0.8
"""Share of a provider's tokens-a-minute limit one request may use (research 143)."""


def models(ctx: Context, size: int) -> list[str]:
    """Providers to try, in order: `options.models`, skipping any that is unreachable
    or whose limit a request of `size` tokens would not fit. Says why in the notes."""
    from eulerlab.agents.runtime import resolve_provider
    from eulerlab.llm import client

    wanted = [str(m) for m in ctx.options.get("models") or [ctx.agent.spec.provider or FIX_MODEL]]
    try:
        loaded = client.load_config()
    except Exception:  # an unreadable config means only the names given
        loaded = None
    out: list[str] = []
    for name in wanted:
        if resolve_provider(name) != name:
            ctx.notes.append(f"{name} is not reachable (no key, or not confirmed); skipped")
            continue
        limit = None
        if loaded is not None:
            try:
                limit = loaded.get(name).tokens_per_minute
            except KeyError:
                limit = None
        if limit and size > FIT * limit:
            ctx.notes.append(
                f"{name}: a request of about {size:,} tokens does not fit its free "
                f"{limit:,} tokens a minute; skipped"
            )
            continue
        out.append(name)
    return out


def _use(ctx: Context, provider: str) -> None:
    from eulerlab.agents.runtime import model_asker

    ctx.asker = model_asker(provider)
    ctx.model = provider


def _fix_size(problem: Any, fixer: Any) -> int:
    """About how many tokens the smallest fix request sends; 0 when the file cannot be read.

    The small context (`fixer.small_context`), not the whole file: a model
    with a per-minute limit is sent the small one (HISTORY #78)."""
    try:
        tests = fixer.tests_for(problem.file)
        small = fixer.small_context(problem.file, problem.error or problem.detail, tests, 10**9)
        if small is None:
            return 0
        return int(fixer.tokens(fixer.EDIT_SYSTEM) + fixer.tokens(small) + fixer.OUTPUT_RESERVE)
    except OSError:
        return 0


def budget(name: str) -> int | None:
    """Tokens a fix request to `name` may use: `FIT` of its per-minute limit, or None for no limit."""
    from eulerlab.llm import client

    try:
        limit = client.load_config().get(name).tokens_per_minute
    except Exception:  # an unreadable config or an unknown name: no limit known
        return None
    return int(FIT * limit) if limit else None


def fixes(ctx: Context, *, limit: int) -> list[Item]:
    """Work the doctor's code queue: one fix attempt per file, up to `limit`."""
    from eulerlab.agents import doctor
    from eulerlab.devtools import fixer

    queue = doctor.queued(ctx.root)
    if not queue:
        return []
    injected = ctx.asker is not None  # a test's or caller's model, used as given
    items: list[Item] = []
    for problem in queue[:limit]:
        if not ctx.can_ask():
            break
        ctx.step(f"Fixing {problem.file} for {problem.agent}: {problem.detail[:80]}")
        order = [ctx.model or "given"] if injected else models(ctx, _fix_size(problem, fixer))
        if not order:
            items.append(
                Item(
                    kind="alert",
                    title=f"{len(queue)} code problem(s) waiting: no fix model is reachable",
                    body="Add the Groq or Anthropic key to .env (see config/llm.yaml).",
                    severity="warn",
                )
            )
            break
        attempt = fixer.Attempt(id="", file=problem.file, outcome="not tried")
        for provider in order:
            if not injected:
                _use(ctx, provider)
            attempt = fixer.fix(
                problem.file,
                problem.error or problem.detail,
                ctx.ask,
                budget=None if injected else budget(provider),
            )
            if attempt.green or not ctx.can_ask():
                break
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


def code_feature(ctx: Context) -> WorkerResult:
    """Code the signal a research card names, free model first (ADR-127)."""
    from eulerlab.devtools import fixer
    from eulerlab.features import coded, library

    name = str(ctx.args.get("feature") or "").strip()
    card = str(ctx.args.get("card") or "").strip()
    if not coded.NAME.match(name):
        return WorkerResult(f"Refused: {name!r} is not a feature name", status="refused")
    if name in library.BY_NAME:
        return WorkerResult(f"{name} is already in the library; the lab can test the card")
    path = Path(card)
    if not card or not path.exists():
        return WorkerResult(f"Refused: no card at {card!r}", status="refused")
    card_text = path.read_text(encoding="utf-8")
    size = len(fixer.FEATURE_SYSTEM + fixer.feature_context(name, card_text)) // 4 + 2_500
    injected = ctx.asker is not None
    order = [ctx.model or "given"] if injected else models(ctx, size)
    if not order:
        return WorkerResult("Refused: no model is reachable to code it", status="refused")
    tried: list[str] = []
    attempt = fixer.Attempt(id="", file="", outcome="not tried")
    for provider in order:
        if not ctx.can_ask():
            break
        if not injected:
            _use(ctx, provider)
        ctx.step(f"Coding {name} with {provider}")
        attempt = fixer.Attempt(id="", file="", outcome="not tried")
        for _ in range(2):
            try:
                attempt = fixer.code_feature(name, card_text, ctx.ask, card=card, model=provider)
                break
            except Exception as exc:
                # A timeout or busy model: once more, then the next model. A spent
                # budget ends the run (seen 2026-11-03: Groq took over 60 s once).
                if type(exc).__name__ == "BudgetSpent" or not ctx.can_ask():
                    raise
                attempt.outcome = f"model error: {str(exc)[:120]}"
                ctx.notes.append(f"{provider}: {attempt.outcome}")
        checks = ", ".join(f"{n} {'ok' if ok else 'FAILED'}" for n, ok, _ in attempt.checks)
        tried.append(f"{provider}: {attempt.outcome}" + (f" ({checks})" if checks else ""))
        tried += [
            f"  {n}: ...{' '.join(t.split())[-400:]}" for n, ok, t in attempt.checks if not ok
        ]
        if attempt.green or attempt.outcome in ("no fix", "refused"):
            break
    done = attempt.green and attempt.outcome in (
        "pull request opened",
        "branch pushed",
        "committed",
    )
    item = Item(
        kind="proposal" if done else "finding",
        title=(
            f"{name} coded: merge it to test the card"
            if done
            else f"{name} not coded: {attempt.outcome}"
        )[:200],
        body="\n".join([attempt.explanation, f"card: {card}", f"branch: {attempt.branch}", *tried]),
        severity="info" if done else "warn",
        needs_approval=True,
        ref=attempt.branch,
        data={"feature": name, "card": card, "tried": tried, "outcome": attempt.outcome},
    )
    summary = (
        f"{name}: {attempt.outcome} by {ctx.model}; merge it and the lab tests the card"
        if done
        else f"{name}: {attempt.outcome}. {attempt.explanation[:160]}"
    )
    return WorkerResult(summary, [item], data={"mode": "feature", "feature": name, "tried": tried})


def run(ctx: Context) -> WorkerResult:
    mode = str(ctx.args.get("mode") or "").strip()
    if mode == "feature":
        return code_feature(ctx)
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
