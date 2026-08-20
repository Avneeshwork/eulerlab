"""The chaos scenarios, run as part of the normal test suite.

`make chaos` is the operator-facing command. This runs the same scenarios in
pytest so that a change which breaks crash recovery fails CI, rather than
waiting for someone to remember to run the separate command. Two of them start
a real subprocess and `SIGKILL` it, so this file is slower than the rest of the
suite — worth it for the only tests that exercise a process that did not get to
finish.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eulerlab.oms import chaos


@pytest.mark.parametrize(("name", "scenario"), chaos.SCENARIOS, ids=[n for n, _ in chaos.SCENARIOS])
def test_scenario(name: str, scenario: object, tmp_path: Path) -> None:
    detail = scenario(tmp_path)  # type: ignore[operator]
    assert detail


def test_every_scenario_is_registered() -> None:
    """A scenario written and not wired in is a test that never runs."""
    assert len(chaos.SCENARIOS) == 11
