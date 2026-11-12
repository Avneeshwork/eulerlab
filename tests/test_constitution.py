"""The constitution (ADR-171): the operator's limits load, and refuse what they must."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from eulerlab import constitution
from eulerlab.llm import spend

REPO = Path(__file__).parents[1]
FILE = REPO / "config" / "constitution.yaml"


def _raw() -> dict[str, Any]:
    raw = yaml.safe_load(FILE.read_text())
    assert isinstance(raw, dict)
    return raw


def _write(tmp_path: Path, raw: dict[str, Any]) -> Path:
    path = tmp_path / "constitution.yaml"
    path.write_text(yaml.safe_dump(raw))
    return path


def test_the_committed_file_holds_the_operators_four_decisions() -> None:
    rules = constitution.load(FILE)
    assert rules.capital.test_capital_inr == 100_000
    assert rules.capital.leverage == 1.0
    assert rules.periods.backtest_end == date(2025, 12, 31)
    assert rules.periods.forward_start == date(2026, 1, 1)
    assert rules.budget.monthly_ai_inr == 1_000
    assert rules.actions["live_account"] == "never"
    assert set(rules.actions) == set(constitution.ACTIONS)


def test_a_day_belongs_to_one_period() -> None:
    periods = constitution.load(FILE).periods
    assert periods.part(date(2023, 12, 29)) == "discovery"
    assert periods.part(date(2024, 1, 1)) == "selection"
    assert periods.part(date(2025, 12, 31)) == "selection"
    assert periods.part(date(2026, 1, 1)) == "forward"


@pytest.mark.parametrize("level", ["act", "propose"])
def test_no_file_can_give_an_agent_the_live_account(tmp_path: Path, level: str) -> None:
    raw = _raw()
    raw["actions"]["live_account"] = level
    with pytest.raises(ValidationError, match="live_account"):
        constitution.load(_write(tmp_path, raw))


def test_leverage_above_one_does_not_load(tmp_path: Path) -> None:
    raw = _raw()
    raw["capital"]["leverage"] = 2.0
    with pytest.raises(ValidationError):
        constitution.load(_write(tmp_path, raw))


def test_an_action_without_a_level_does_not_load(tmp_path: Path) -> None:
    raw = _raw()
    del raw["actions"]["start_paper_book"]
    with pytest.raises(ValidationError, match="start_paper_book"):
        constitution.load(_write(tmp_path, raw))


def test_require_passes_act_and_refuses_the_rest(tmp_path: Path) -> None:
    constitution.require("start_paper_book", path=FILE)
    with pytest.raises(constitution.NotAllowed, match="never"):
        constitution.require("live_account", path=FILE)
    with pytest.raises(constitution.NotAllowed, match="propose"):
        constitution.require("merge_code", path=FILE)
    with pytest.raises(constitution.NotAllowed, match="not an action"):
        constitution.require("wire_money_abroad", path=FILE)
    with pytest.raises(constitution.NotAllowed, match="missing"):
        constitution.require("start_paper_book", path=tmp_path / "absent.yaml")


# --- the monthly budget -------------------------------------------------------------------

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
FREE = frozenset({"groq"})


def _log(tmp_path: Path, rows: list[dict[str, Any]]) -> Path:
    path = tmp_path / "llm_usage.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def _row(at: str, provider: str, model: str, prompt: int, completion: int) -> dict[str, Any]:
    return {
        "at": at,
        "agent": "autopilot",
        "provider": provider,
        "model": model,
        "prompt": prompt,
        "completion": completion,
    }


def test_a_request_costs_its_tokens_at_the_listed_price() -> None:
    budget = constitution.load(FILE).budget
    row = _row(
        "2026-11-02T10:00:00+00:00", "claude-sonnet", "claude-sonnet-5-5", 1_000_000, 100_000
    )
    # $2 in + $1 out = $3, at Rs 90
    assert spend.cost_inr(row, budget, FREE) == pytest.approx(270.0)
    assert spend.cost_inr({**row, "provider": "groq"}, budget, FREE) == 0.0
    unknown = spend.cost_inr({**row, "model": "new-paid-model"}, budget, FREE)
    assert unknown == pytest.approx((10.0 + 5.0) * 90.0)


def test_the_month_is_the_ist_calendar_month(tmp_path: Path) -> None:
    budget = constitution.load(FILE).budget
    log = _log(
        tmp_path,
        [
            # 31 Oct 17:00 UTC is 22:30 IST on 31 Oct: last month.
            _row("2026-10-31T17:00:00+00:00", "claude-sonnet", "claude-sonnet-5-5", 1_000_000, 0),
            # 31 Oct 19:00 UTC is 00:30 IST on 1 Nov: this month.
            _row("2026-10-31T19:00:00+00:00", "claude-sonnet", "claude-sonnet-5-5", 1_000_000, 0),
        ],
    )
    assert spend.month_spend_inr(NOW, rules=budget, free=FREE, log=log) == pytest.approx(180.0)


def test_a_paid_model_is_refused_once_the_month_is_spent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(REPO)
    monkeypatch.setattr(spend, "free_providers", lambda config=None: FREE)
    under = _log(tmp_path, [_row("2026-11-02T10:00:00+00:00", "x", "claude-opus-5-5", 100_000, 0)])
    spend.refuse_if_spent("claude-opus", NOW, log=under)
    over = _log(
        tmp_path, [_row("2026-11-02T10:00:00+00:00", "x", "claude-opus-5-5", 3_000_000, 0)]
    )  # $12 = Rs 1,080
    with pytest.raises(spend.MonthBudgetSpent, match="1,000"):
        spend.refuse_if_spent("claude-opus", NOW, log=over)
    spend.refuse_if_spent("groq", NOW, log=over)  # a free provider still answers
