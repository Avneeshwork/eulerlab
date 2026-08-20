"""Read ``STATE.md`` and report where the project is.

``STATE.md`` is written for a human first, so this parser reads the same bold
lines the operator reads. If the parse fails, the fix is to correct STATE.md,
not to loosen the parser — a STATE.md this script cannot read is one the next
session cannot trust either.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = REPO_ROOT / "STATE.md"


@dataclass(frozen=True)
class State:
    status: str
    next_up: str

    def summary(self) -> str:
        return f"{self.status} | next: {self.next_up}"


class StateParseError(ValueError):
    """STATE.md is missing a field this script requires."""


def _field(text: str, label: str) -> str:
    match = re.search(rf"^\*\*{label}:\*\*\s*(.+?)\s*$", text, re.MULTILINE)
    if match is None:
        msg = f"STATE.md has no '**{label}:**' line"
        raise StateParseError(msg)
    return match.group(1).strip()


def read_state(path: Path = STATE_PATH) -> State:
    """Read the two lines that must always be true.

    The sprint number used to be parsed here too. It was dropped when the
    build plan's sprints finished: a field that can only ever hold one value
    is not state, and keeping it would have meant STATE.md carrying a number
    nobody updates. Status and next step are the two things a cold session
    genuinely needs.
    """
    text = path.read_text(encoding="utf-8")
    return State(status=_field(text, "Status"), next_up=_field(text, "Next"))


def main() -> int:
    try:
        state = read_state()
    except (OSError, StateParseError) as exc:
        print(f"state: {exc}", file=sys.stderr)
        return 1
    print(state.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
