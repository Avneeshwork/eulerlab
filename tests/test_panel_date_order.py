"""A backfilled older day must not end up as the panel's last line (2026-11-09)."""

from __future__ import annotations

import json
from pathlib import Path

from eulerlab.features.panel import put_in_date_order


def _row(day: str, symbol: str) -> str:
    return json.dumps({"c": 1.0, "d": day, "s": symbol, "t": 1.0}, sort_keys=True) + "\n"


def test_appended_older_days_move_into_place(tmp_path: Path) -> None:
    path = tmp_path / "panel.jsonl"
    head = _row("2026-11-05", "A") + _row("2026-11-05", "B") + _row("2026-11-06", "A")
    path.write_text(head + _row("2026-02-01", "A") + _row("2026-11-01", "A"))
    put_in_date_order(path, len(head.encode()))
    days = [json.loads(line)["d"] for line in path.read_text().splitlines()]
    assert days == ["2026-02-01", "2026-11-01", "2026-11-05", "2026-11-05", "2026-11-06"]


def test_a_tail_newer_than_everything_stays_last(tmp_path: Path) -> None:
    path = tmp_path / "panel.jsonl"
    head = _row("2026-11-05", "A")
    path.write_text(head + _row("2026-11-09", "A"))
    put_in_date_order(path, len(head.encode()))
    assert json.loads(path.read_text().splitlines()[-1])["d"] == "2026-11-09"
