"""The autonomy scorecard (ADR-173): one page from stored records."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from eulerlab import scorecard
from eulerlab.research import experiments

REPO = Path(__file__).parents[1]
NOW = datetime(2026, 11, 13, 6, 0, tzinfo=UTC)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in ("constitution.yaml", "llm.yaml"):
        (tmp_path / "config").mkdir(exist_ok=True)
        (tmp_path / "config" / name).write_text((REPO / "config" / name).read_text())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(experiments, "PATH", tmp_path / "experiments.jsonl")
    monkeypatch.setattr(experiments, "RETURNS", tmp_path / "returns")
    monkeypatch.setattr("eulerlab.llm.usage.LOG", tmp_path / "llm_usage.jsonl")
    monkeypatch.setattr(scorecard, "_paper_books", lambda: {"active": 2})
    return tmp_path


def test_an_empty_store_gives_a_page_that_claims_nothing(home: Path) -> None:
    card = scorecard.build(NOW, home / "agents")
    assert card["ai_spend"]["month_inr"] == 0 and card["ai_spend"]["left_inr"] == 1000
    assert card["search"]["families"] is None
    assert card["forward_confirmed_strategies"].startswith("not measured")
    text = scorecard.render(card)
    assert "Rs 100,000" in text and "never" in text and "not measured yet" in text


def test_spend_search_and_gate_use_come_from_the_records(home: Path) -> None:
    (home / "llm_usage.jsonl").write_text(
        json.dumps(
            {
                "at": "2026-11-10T10:00:00+00:00",
                "agent": "autopilot",
                "provider": "claude-sonnet",
                "model": "claude-sonnet-5-5",
                "prompt": 1_000_000,
                "completion": 0,
            }
        )
        + "\n"
    )
    days = [date(2022, 1, 3) + timedelta(days=i) for i in range(120)]
    for k in range(3):
        experiments.record(
            purpose="screen",
            fingerprint=f"r{k}",
            family="intraday:gap",
            first=days[0],
            end=days[-1],
            metrics={},
            daily={d: ((i * (k + 3)) % 7 - 3) / 1000 for i, d in enumerate(days)},
            now=NOW,
            path=experiments.PATH,
            returns_root=experiments.RETURNS,
        )
    log = home / "agents" / "autopilot" / "gates.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(
        json.dumps({"at": "2026-11-12T12:00:00+00:00", "verdict": "KILL", "entries": 2}) + "\n"
    )
    card = scorecard.build(NOW, home / "agents")
    assert card["ai_spend"] == {
        "month_inr": 180.0,
        "budget_inr": 1000.0,
        "left_inr": 820.0,
        "by_agent_inr": {"autopilot": 180.0},
    }
    assert card["search"]["all_time"] == {"screen": 3, "rules": 3}
    assert card["search"]["most_searched"] == {"intraday:gap": 3}
    assert card["gate"]["entries_last_7_days"] == 2
    assert card["gate"]["verdicts_last_7_days"] == {"KILL": 1}
    assert card["paper_books"] == {"active": 2}
