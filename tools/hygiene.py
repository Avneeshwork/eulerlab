"""``make hygiene`` — stop the repo filling up with dead code and duplicates.

Many agents and Claude threads write into this repo. Each one adds a module, a
screen, a test helper or a decision record, and nothing ever takes them out.
This check finds the kinds of clutter that have actually appeared (audit of
2026-11-09, ADR-161) and fails only on *new* clutter. Existing clutter is
listed in ``tools/hygiene_baseline.json`` so the gate is green today and the
debt can be paid down on purpose, one entry at a time.

Checks
  dead-module     a src module nothing imports: not src, tools, tests, Makefile
  test-only       a src module only tests import (warning only: new code is
                  often tested a commit before it is wired in)
  dup-function    two functions in src with the same body (>= 8 lines)
  adr-number      two decision records share a number
  research-number two research notes share a number
  card-duplicate  two hypothesis cards with the same title, claim or config
  tracked-junk    logs, editor files or a second JS lockfile under git
  data-literal    a src module spelling the data directory itself
                  (``Path("data/...")``) instead of ``eulerlab.paths.data_path``

Usage
  uv run python tools/hygiene.py            fail on anything not in the baseline
  uv run python tools/hygiene.py --report   print everything, never fail
  uv run python tools/hygiene.py --rebaseline   accept today's state (operator only)

Removing an entry from the baseline is how a cleanup is recorded: once the
clutter is gone, the stale baseline entry is reported so it can be deleted.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
BASELINE = REPO / "tools" / "hygiene_baseline.json"
MIN_DUP_LINES = 8
JUNK = re.compile(r"(^|/)(\.DS_Store|.*\.log|.*\.orig|.*\.bak|.*~|.*\.swp)$|^logs/")
SECOND_LOCKFILES = {"web/pnpm-lock.yaml", "web/yarn.lock"}
WARN_ONLY = {"test-only"}
SKIPPED_HOOKS = REPO / "data" / "logs" / "skipped_hooks.jsonl"
DATA_LITERAL = re.compile(r"""Path\(\s*["']data(/|["'])|["']data/[a-z]""")
DATA_LITERAL_ALLOWED = {"src/eulerlab/paths.py"}


def _module_name(path: Path) -> str:
    name = ".".join(path.relative_to(SRC).with_suffix("").parts)
    return name.removesuffix(".__init__")


def _src_modules() -> dict[str, Path]:
    return {_module_name(p): p for p in sorted((SRC / "eulerlab").rglob("*.py"))}


def _imports(path: Path, modules: dict[str, Path]) -> set[str]:
    """Every src module this file reaches, by import or by dotted string."""
    try:
        tree = ast.parse(path.read_text())
    except (SyntaxError, UnicodeDecodeError):
        return set()
    own = _module_name(path) if path.is_relative_to(SRC) else ""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level and own:
                parts = own.split(".")
                if path.name != "__init__.py":
                    parts = parts[:-1]
                parts = parts[: len(parts) - (node.level - 1)]
                base = ".".join([*parts, base] if base else parts)
            names.add(base)
            names.update(f"{base}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Constant) and str(node.value).startswith("eulerlab."):
            names.add(str(node.value))
    reached: set[str] = set()
    for name in names:
        parts = name.split(".")
        for i in range(1, len(parts) + 1):
            prefix = ".".join(parts[:i])
            if prefix in modules and modules[prefix] != path:
                reached.add(prefix)
    return reached


def check_modules() -> tuple[list[str], list[str]]:
    modules = _src_modules()
    from_code: set[str] = set()
    from_tests: set[str] = set()
    for path in [*SRC.rglob("*.py"), *(REPO / "tools").rglob("*.py")]:
        from_code |= _imports(path, modules)
    for path in (REPO / "tests").rglob("*.py"):
        from_tests |= _imports(path, modules)
    text = (REPO / "Makefile").read_text() + (REPO / "pyproject.toml").read_text()
    # Agents are wired by name in config/agents/*.yaml, scripts by `-m` in shell.
    wiring = [*(REPO / "tools").glob("*.sh"), *(REPO / "config").rglob("*.yaml")]
    for path in wiring:
        text += path.read_text()
    from_code |= {m for m in modules if re.search(re.escape(m) + r"\b", text)}
    # `python -m pkg` runs pkg/__main__.py.
    from_code |= {f"{m}.__main__" for m in from_code if f"{m}.__main__" in modules}
    leaves = [m for m, p in modules.items() if p.name != "__init__.py"]
    dead = sorted(m for m in leaves if m not in from_code and m not in from_tests)
    test_only = sorted(m for m in leaves if m not in from_code and m in from_tests)
    return dead, test_only


def check_duplicate_functions() -> list[str]:
    groups: dict[str, list[str]] = defaultdict(list)
    for path in sorted((SRC / "eulerlab").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        rel = path.relative_to(SRC / "eulerlab").as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if (node.end_lineno or node.lineno) - node.lineno + 1 < MIN_DUP_LINES:
                continue
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                body = body[1:]
            digest = hashlib.sha256("".join(ast.dump(b) for b in body).encode()).hexdigest()
            groups[digest].append(f"{rel}::{node.name}")
    return sorted(" = ".join(sorted(g)) for g in groups.values() if len(g) > 1)


def _number_collisions(folder: Path, pattern: str) -> list[str]:
    seen: dict[str, list[str]] = defaultdict(list)
    for path in sorted(folder.glob("*.md")):
        match = re.match(pattern, path.name)
        if match:
            seen[match.group(1)].append(path.name)
    return sorted(" = ".join(v) for v in seen.values() if len(v) > 1)


def check_cards() -> list[str]:
    seen: dict[str, list[str]] = defaultdict(list)
    for path in sorted((REPO / "hypotheses").glob("*.yaml")):
        card = yaml.safe_load(path.read_text()) or {}
        for field in ("title", "claim"):
            text = re.sub(r"[^a-z0-9]+", " ", str(card.get(field, "")).lower()).strip()
            if text:
                seen[f"{field}:{text}"].append(path.stem)
        for config in card.get("configurations") or []:
            seen["config:" + json.dumps(config, sort_keys=True, default=str)].append(path.stem)
    return sorted(
        f"{key.split(':', 1)[0]} " + " = ".join(sorted(set(v)))
        for key, v in seen.items()
        if len(set(v)) > 1
    )


def check_junk() -> list[str]:
    files = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    return sorted(f for f in files if JUNK.search(f) or f in SECOND_LOCKFILES)


def check_data_literals() -> list[str]:
    """Src files that spell `data/...` themselves. `EULERLAB_DATA_DIR` is the one
    setting for where data lives, and a literal path ignores it."""
    found = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(REPO).as_posix()
        if rel in DATA_LITERAL_ALLOWED:
            continue
        if DATA_LITERAL.search(path.read_text()):
            found.append(rel)
    return found


def collect() -> dict[str, list[str]]:
    dead, test_only = check_modules()
    return {
        "dead-module": dead,
        "test-only": test_only,
        "dup-function": check_duplicate_functions(),
        "adr-number": _number_collisions(REPO / "docs" / "DECISIONS", r"(ADR-\d+)"),
        "research-number": _number_collisions(REPO / "docs" / "RESEARCH", r"(\d{3})-"),
        "card-duplicate": check_cards(),
        "tracked-junk": check_junk(),
        "data-literal": check_data_literals(),
    }


def _paths(kind: str, item: str) -> set[str]:
    """The repo files an item is about, so a commit is judged on its own files."""
    if kind in ("dead-module", "test-only"):
        rel = "src/" + item.replace(".", "/")
        return {rel + ".py", rel + "/__init__.py"}
    if kind == "dup-function":
        return {"src/eulerlab/" + part.split("::")[0] for part in item.split(" = ")}
    if kind == "adr-number":
        return {"docs/DECISIONS/" + part for part in item.split(" = ")}
    if kind == "research-number":
        return {"docs/RESEARCH/" + part for part in item.split(" = ")}
    if kind == "card-duplicate":
        return {f"hypotheses/{card}.yaml" for card in item.split(" ", 1)[1].split(" = ")}
    return {item}


def _staged() -> set[str]:
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return set(out.splitlines())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", action="store_true", help="print all, never fail")
    parser.add_argument("--rebaseline", action="store_true", help="accept today's state")
    parser.add_argument(
        "--staged",
        action="store_true",
        help="fail only on new items whose files are staged (the commit hook): other"
        " threads' half-done work in the shared tree must not block this commit",
    )
    args = parser.parse_args(argv)

    found = collect()
    if args.rebaseline:
        BASELINE.write_text(json.dumps(found, indent=2, sort_keys=True) + "\n")
        print(f"hygiene: baseline written, {sum(map(len, found.values()))} known items")
        return 0

    baseline: dict[str, list[str]] = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
    new = {k: [x for x in v if x not in baseline.get(k, [])] for k, v in found.items()}
    gone = {k: [x for x in v if x not in found.get(k, [])] for k, v in baseline.items()}
    if args.staged:
        staged = _staged()
        new = {k: [x for x in v if _paths(k, x) & staged] for k, v in new.items()}
    n_new = sum(len(v) for k, v in new.items() if k not in WARN_ONLY)
    n_known = sum(map(len, found.values())) - sum(map(len, new.values()))
    n_gone = sum(map(len, gone.values()))

    status = "FAIL" if n_new and not args.report else "PASS"
    print(f"hygiene {status}: {n_new} new, {n_known} known debt, {n_gone} cleaned up")
    if SKIPPED_HOOKS.exists():
        skipped = len(SKIPPED_HOOKS.read_text().splitlines())
        print(f"  commits made without hooks (tools/hook_witness.py report): {skipped}")
    for title, items in (("NEW", new), ("CLEANED (delete from baseline)", gone)):
        # A warning is still printed; it just does not fail the commit.
        for kind, entries in items.items():
            for entry in entries:
                print(f"  {title} {kind}: {entry}")
    if args.report:
        for kind, entries in found.items():
            print(f"  {kind}: {len(entries)}")
            for entry in entries:
                print(f"    {entry}")
    if n_new and not args.report:
        print(
            "\nFix it (delete the dead code, reuse the existing function, pick the next"
            "\nfree number), or if it is deliberate, say why in the commit and ask the"
            "\noperator to run `make hygiene-rebaseline`."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
