"""The loop's report. Its job is to say *why*, not to count throughput."""

from __future__ import annotations

from pathlib import Path

import yaml

from eulerlab.research import orchestrator


def _cards(tmp_path: Path, n: int = 2) -> Path:
    for i in range(1, n + 1):
        (tmp_path / f"H-{i:04d}.yaml").write_text(
            yaml.safe_dump(
                {
                    "id": f"H-{i:04d}",
                    "title": f"hypothesis {i}",
                    "status": "draft",
                    "configurations": [
                        {"feature": "momentum_12_1", "top_n": 30},
                        {"feature": "reversal_1m", "top_n": 30},
                    ],
                    "red_flags": ["Sprint 13 measured this cluster at +0.95."],
                }
            ),
            encoding="utf-8",
        )
    return tmp_path


def test_every_card_appears_in_the_survey(tmp_path: Path) -> None:
    assert len(orchestrator.survey(_cards(tmp_path, 3), years=11.4)) == 3


def test_a_buildable_card_is_marked_buildable(tmp_path: Path) -> None:
    assert orchestrator.survey(_cards(tmp_path), years=11.4)[0].buildable


def test_an_unbuildable_card_is_marked_not_buildable(tmp_path: Path) -> None:
    (tmp_path / "H-0001.yaml").write_text(
        yaml.safe_dump({"id": "H-0001", "title": "x", "configurations": [{"feature": "nope"}]}),
        encoding="utf-8",
    )
    assert not orchestrator.survey(tmp_path, years=11.4)[0].buildable


def test_the_report_states_the_accumulated_bar(tmp_path: Path) -> None:
    """The number the whole loop is accountable to."""
    text = orchestrator.render(orchestrator.survey(_cards(tmp_path), years=11.4), years=11.4)
    assert "the bar now" in text
    assert "trials logged" in text


def test_the_report_separates_killed_promoted_and_untested(tmp_path: Path) -> None:
    text = orchestrator.render(orchestrator.survey(_cards(tmp_path), years=11.4), years=11.4)
    for label in ("killed", "promoted", "never tested"):
        assert label in text


def test_the_report_says_throughput_is_not_the_goal(tmp_path: Path) -> None:
    text = orchestrator.render(orchestrator.survey(_cards(tmp_path), years=11.4), years=11.4)
    assert "Throughput is not the goal" in text


def test_the_real_hypotheses_directory_surveys_cleanly() -> None:
    cards = orchestrator.survey(Path("hypotheses"), years=11.4)
    assert {c.id for c in cards} >= {"H-0001", "H-0002"}


def test_the_gate_verdict_is_read_from_the_ledger() -> None:
    """H-0001 was killed by the real gate; the report must reflect that rather
    than tracking its own state."""
    cards = {c.id: c for c in orchestrator.survey(Path("hypotheses"), years=11.4)}
    assert cards["H-0001"].gate_verdict == "KILL"


def test_an_empty_directory_is_not_an_error(tmp_path: Path) -> None:
    assert orchestrator.survey(tmp_path, years=11.4) == []
