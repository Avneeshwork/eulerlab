"""``make verify`` — the one command the operator runs.

Runs every gate and prints a single table. Green means the repo is in a state
you can trust; red means stop and read the output printed underneath. Exit code
is non-zero if anything failed, so CI can use the same entry point.

Adding a check here is how a new invariant becomes something the operator can
verify without reading code.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
RESET = "\033[0m"


def _colour(text: str, code: str) -> str:
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return text
    return f"{code}{text}{RESET}"


@dataclass(frozen=True)
class Result:
    name: str
    ok: bool
    label: str
    detail: str
    output: str


def _run(cmd: Sequence[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _search(pattern: str, text: str) -> re.Match[str] | None:
    return re.search(pattern, text)


def check_lint() -> Result:
    lint_code, lint_out = _run([sys.executable, "-m", "ruff", "check", "."])
    fmt_code, fmt_out = _run([sys.executable, "-m", "ruff", "format", "--check", "."])

    if lint_code == 0 and fmt_code == 0:
        return Result("lint", True, "PASS", "0 issues, format clean", "")

    parts: list[str] = []
    if lint_code != 0:
        found = _search(r"Found (\d+) error", lint_out)
        parts.append(f"{found.group(1)} issues" if found else "lint failed")
    if fmt_code != 0:
        would = _search(r"(\d+) files? would be reformatted", fmt_out)
        parts.append(f"{would.group(1)} files need formatting" if would else "format failed")
    return Result("lint", False, "FAIL", ", ".join(parts), f"{lint_out}\n{fmt_out}".strip())


def check_types() -> Result:
    code, out = _run([sys.executable, "-m", "mypy"])
    if code == 0:
        found = _search(r"no issues found in (\d+) source file", out)
        detail = f"0 errors in {found.group(1)} files" if found else "0 errors"
        return Result("types", True, "PASS", detail, "")
    found = _search(r"Found (\d+) errors? in (\d+) file", out)
    detail = f"{found.group(1)} errors in {found.group(2)} files" if found else "mypy failed"
    return Result("types", False, "FAIL", detail, out)


def check_tests() -> Result:
    code, out = _run([sys.executable, "-m", "pytest"])
    passed = _search(r"(\d+) passed", out)
    if code == 0:
        detail = f"{passed.group(1)} passed" if passed else "passed"
        return Result("tests", True, "PASS", detail, "")
    failed = _search(r"(\d+) failed", out)
    bits = []
    if failed:
        bits.append(f"{failed.group(1)} failed")
    if passed:
        bits.append(f"{passed.group(1)} passed")
    return Result("tests", False, "FAIL", ", ".join(bits) or "pytest failed", out)


def _script_check(name: str, script: str, ok_label: str) -> Result:
    code, out = _run([sys.executable, str(REPO_ROOT / "tools" / script)])
    first = out.splitlines()[0] if out else ""
    if code == 0:
        return Result(name, True, ok_label, first, "")
    return Result(name, False, "FAIL", first or f"{script} failed", out)


def check_docs() -> Result:
    return _script_check("docs-check", "docs_check.py", "PASS")


def check_state() -> Result:
    return _script_check("state", "state.py", "OK")


def check_engine() -> Result:
    """The backtester self-tests.

    In `make verify` rather than beside it because the build plan calls this
    the most important gate in the project, and a gate you have to remember to
    run separately is one that gets skipped on the day it would have caught
    something. It is fast — synthetic worlds, no network, no real data — so
    there is no cost to making it mandatory.
    """
    name = "engine"
    completed = subprocess.run(
        [sys.executable, "-m", "eulerlab.backtest.selftest"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    output = (completed.stdout + completed.stderr).strip()
    summary = next((ln for ln in reversed(output.splitlines()) if ln.startswith("test-engine")), "")
    if completed.returncode == 0:
        return Result(name, True, "PASS", summary.replace("test-engine OK: ", ""), "")
    return Result(name, False, "FAIL", summary or "self-tests failed", output)


CHECKS = (check_lint, check_types, check_tests, check_docs, check_engine, check_state)


def main() -> int:
    results = [check() for check in CHECKS]

    print(_colour(f"{'CHECK':<12}{'RESULT':<9}{'DETAIL'}", DIM))
    for result in results:
        colour = GREEN if result.ok else RED
        print(f"{result.name:<12}{_colour(f'{result.label:<9}', colour)}{result.detail}")

    failures = [r for r in results if not r.ok]
    if failures:
        for result in failures:
            print(f"\n{_colour(f'--- {result.name} ---', RED)}\n{result.output}")
        print(_colour(f"\nverify FAILED: {len(failures)} of {len(results)} checks red", RED))
        return 1

    print(_colour(f"\nverify OK: {len(results)} of {len(results)} checks green", GREEN))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
