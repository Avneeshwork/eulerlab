"""The Data quality screen grades once per two minutes, not per visit (T-4369)."""

from __future__ import annotations

from typing import Any

import pytest

from eulerlab.api import agent_routes
from eulerlab.quality import contract


def test_a_second_visit_reuses_the_grading(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def grade_all() -> list[Any]:
        calls.append(1)
        return []

    monkeypatch.setattr(contract, "grade_all", grade_all)
    monkeypatch.setattr(contract, "save", lambda grades: None)
    monkeypatch.setattr(agent_routes, "_QUALITY", {})

    first = agent_routes.quality()
    second = agent_routes.quality()
    assert len(calls) == 1
    assert first["graded_at"] == second["graded_at"]

    agent_routes.quality(refresh=True)
    assert len(calls) == 2


def test_an_old_grading_is_redone(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def grade_all() -> list[Any]:
        calls.append(1)
        return []

    monkeypatch.setattr(contract, "grade_all", grade_all)
    monkeypatch.setattr(contract, "save", lambda grades: None)
    monkeypatch.setattr(agent_routes, "_QUALITY", {})
    agent_routes.quality()
    agent_routes._QUALITY["at"] -= agent_routes.QUALITY_TTL_SECONDS + 1
    agent_routes.quality()
    assert len(calls) == 2
