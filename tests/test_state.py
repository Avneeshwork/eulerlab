"""STATE.md must stay machine-readable.

If this goes red, STATE.md drifted into prose. Fix the file, not the parser —
a STATE.md this cannot read is one the next session cannot resume from.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.state import StateParseError, read_state

WELL_FORMED = """# STATE

**Status:** COMPLETE
**Next:** Sprint 8 — Feature library
"""


def test_repository_state_file_parses() -> None:
    state = read_state()
    assert state.status
    assert state.status
    assert state.next_up


def test_parses_fields(tmp_path: Path) -> None:
    path = tmp_path / "STATE.md"
    path.write_text(WELL_FORMED, encoding="utf-8")

    state = read_state(path)

    assert state.status == "COMPLETE"
    assert state.status == "COMPLETE"
    assert state.summary() == "COMPLETE | next: Sprint 8 — Feature library"


def test_missing_field_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "STATE.md"
    path.write_text("**Status:** COMPLETE\n", encoding="utf-8")

    with pytest.raises(StateParseError, match="Next"):
        read_state(path)
