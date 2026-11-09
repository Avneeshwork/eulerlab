"""Results timestamps from landed NSE answers: what is kept and when it was known."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from eulerlab.ingest import nse_earnings_announcements as ann


def _land(root: Path, rows: list[dict[str, str]], name: str = "2024-07-01_2024-09-30") -> Path:
    path = root / f"{name}.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def test_a_result_is_known_from_an_earlier_same_day_board_outcome(tmp_path: Path) -> None:
    path = _land(
        tmp_path,
        [
            {
                "desc": "Financial Result Updates",
                "symbol": "ABC",
                "an_dt": "05-Aug-2024 13:05:00",
                "exchdisstime": "05-Aug-2024 13:06:00",
            },
            {
                "desc": "Outcome of Board Meeting",
                "symbol": "ABC",
                "exchdisstime": "05-Aug-2024 13:02:30",
            },
            {"desc": "General updates", "symbol": "XYZ", "exchdisstime": "05-Aug-2024 10:00:00"},
        ],
    )
    rows, warnings = ann.derive([path])
    assert warnings == []
    assert [r["symbol"] for r in rows] == ["ABC"]
    assert rows[0]["knowledge_time"] == "2024-08-05T13:02:30+05:30"
    assert rows[0]["results_row_time"] == "2024-08-05T13:06:00+05:30"
    assert rows[0]["event_time"] <= rows[0]["knowledge_time"]


def test_a_row_outside_its_window_is_not_kept(tmp_path: Path) -> None:
    path = _land(
        tmp_path,
        [
            {
                "desc": "Financial Result Updates",
                "symbol": "ABC",
                "exchdisstime": "01-Oct-2024 09:00:00",
            }
        ],
    )
    assert ann.derive([path])[0] == []


def test_a_round_row_count_is_reported_as_possible_truncation(tmp_path: Path) -> None:
    rows = [{"desc": "General updates", "symbol": "X"}] * 1000
    _, warnings = ann.derive([_land(tmp_path, rows)])
    assert warnings and "1000" in warnings[0]


def test_a_landed_quarter_is_never_fetched_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _land(tmp_path, [], "2024-07-01_2024-09-30")

    def refuse(*_: object) -> None:
        raise AssertionError("fetched a quarter that was already landed")

    monkeypatch.setattr(ann, "_opener", refuse)
    paths = ann.land(date(2024, 7, 1), date(2024, 9, 30), root=tmp_path)
    assert [p.name for p in paths] == ["2024-07-01_2024-09-30.json"]


def test_an_unfinished_quarter_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="has not finished"):
        ann.land(date(2099, 1, 1), date(2099, 3, 31), root=tmp_path)


def test_since_2026_a_board_outcome_with_results_text_is_a_result(tmp_path: Path) -> None:
    text = "ABC Limited has submitted to the Exchange, the financial results for the period ended"
    path = _land(
        tmp_path,
        [
            {
                "desc": "Outcome of Board Meeting",
                "symbol": "ABC",
                "attchmntText": text,
                "exchdisstime": "05-Nov-2026 16:10:00",
            },
            {
                "desc": "Outcome of Board Meeting",
                "symbol": "XYZ",
                "attchmntText": "Outcome of Board Meeting",
                "exchdisstime": "05-Nov-2026 16:20:00",
            },
        ],
        name="2026-11-05_2026-11-05",
    )
    rows, _ = ann.derive([path])
    assert [(r["symbol"], r["knowledge_time"]) for r in rows] == [
        ("ABC", "2026-11-05T16:10:00+05:30")
    ]


def test_a_results_row_wins_over_the_outcome_text_on_the_same_day(tmp_path: Path) -> None:
    path = _land(
        tmp_path,
        [
            {
                "desc": "Financial Result Updates",
                "symbol": "ABC",
                "exchdisstime": "05-Aug-2024 13:06:00",
            },
            {
                "desc": "Outcome of Board Meeting",
                "symbol": "ABC",
                "attchmntText": "has submitted to the Exchange, the financial results for the quarter",
                "exchdisstime": "05-Aug-2024 13:02:30",
            },
        ],
    )
    rows, _ = ann.derive([path])
    assert len(rows) == 1 and rows[0]["results_row_time"] == "2024-08-05T13:06:00+05:30"
