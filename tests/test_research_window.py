"""One research window, read from the constitution, sealed before 2026 (ADR-184)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from eulerlab import constitution
from eulerlab.intraday import cross_section as cs
from eulerlab.intraday import daily_more_screen as dm
from eulerlab.intraday import research_screen as rs
from eulerlab.intraday import rule_engine
from tools import hygiene

FILE = Path(__file__).parents[1] / "config" / "constitution.yaml"


def _with_periods(tmp_path: Path, **periods: str) -> Path:
    raw: dict[str, Any] = yaml.safe_load(FILE.read_text())
    raw["periods"].update(periods)
    path = tmp_path / "constitution.yaml"
    path.write_text(yaml.safe_dump(raw))
    return path


def test_the_window_runs_from_the_constitutions_start_to_its_backtest_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(constitution.RESEARCH_END_ENV, raising=False)
    first, last = constitution.research_window()
    periods = constitution.load(FILE).periods
    assert first == periods.research_start == date(2005, 1, 1)  # operator, 2026-11-14
    assert last == periods.backtest_end == date(2025, 12, 31)


def test_every_screen_and_the_engine_share_the_one_window() -> None:
    assert rs.DATA_END == cs.DATA_END == dm.END == rule_engine.END
    assert rs.RESEARCH_START == cs.RESEARCH_START == dm.FIRST
    assert rs.DATA_END < constitution.SEALED_FROM


def test_an_earlier_end_reproduces_an_old_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(constitution.RESEARCH_END_ENV, "2024-11-30")
    assert constitution.research_window() == (date(2005, 1, 1), date(2024, 11, 30))


def test_the_environment_cannot_move_the_end_later(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(constitution.RESEARCH_END_ENV, "2026-01-02")
    with pytest.raises(constitution.NotAllowed, match="after the constitution's backtest_end"):
        constitution.research_window()


def test_a_constitution_reaching_2026_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(constitution.RESEARCH_END_ENV, raising=False)
    careless = _with_periods(tmp_path, backtest_end="2026-03-31", forward_start="2026-04-01")
    assert constitution.load(careless).periods.backtest_end == date(2026, 3, 31)
    with pytest.raises(constitution.NotAllowed, match="reaches the forward test"):
        constitution.research_window(careless)


def test_sealed_refuses_the_forward_period_and_an_empty_window() -> None:
    assert constitution.sealed(date(2025, 12, 31), FILE) == date(2025, 12, 31)
    for end in (date(2026, 1, 1), date(2026, 11, 13)):
        with pytest.raises(constitution.NotAllowed):
            constitution.sealed(end, FILE)
    with pytest.raises(constitution.NotAllowed, match="ends before it starts"):
        constitution.sealed(date(2004, 12, 31), FILE)


def test_no_other_module_defines_its_own_window() -> None:
    assert hygiene.check_window_literals() == []


def test_the_hygiene_check_catches_a_copied_window() -> None:
    assert hygiene.window_literals("DATA_END = date(2024, 11, 30)\n") == ["DATA_END"]
    assert hygiene.window_literals("FIRST = date(2016, 1, 1)\n") == ["FIRST"]
    assert hygiene.window_literals("A, END = 1, date(2025, 12, 31)\n") == ["END"]
    assert hygiene.window_literals("EVAL_START = date(2024, 1, 1)\n") == []
    assert hygiene.window_literals("DATA_END = rs.DATA_END\n") == []
