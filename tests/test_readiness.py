"""Readiness for real money (ADR-153): every line needs evidence; nothing is assumed."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from eulerlab.deploy import readiness as rd


@dataclass
class Dep:
    id: str
    strategy_id: str
    status: str = "active"


NOW = datetime(2026, 11, 20, tzinfo=UTC)


def test_shadow_line_needs_sessions_and_an_edge_after_costs() -> None:
    summary = {
        "H-1": {
            "sessions": 12,
            "trades": 40,
            "mean_backtest_bps": 60.0,
            "mean_achievable_bps": 30.0,
            "median_slippage_bps": 28.0,
        }
    }
    assert rd.shadow_line("H-1", summary, 10).met
    summary["H-1"]["mean_achievable_bps"] = 10.0  # below 12.24 bps of costs
    assert not rd.shadow_line("H-1", summary, 10).met
    summary["H-1"].update(mean_achievable_bps=30.0, sessions=4)
    line = rd.shadow_line("H-1", summary, 10)
    assert not line.met and "10 sessions needed" in line.evidence
    assert not rd.shadow_line("H-2", summary, 10).met


def test_drill_needs_trip_and_reset_within_30_days(tmp_path: Path) -> None:
    log = tmp_path / "kill.jsonl"
    rows = [
        {"at": "2026-11-18T10:00:00+00:00", "action": "trip"},
        {"at": "2026-11-18T10:05:00+00:00", "action": "reset"},
    ]
    log.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    assert rd.drill_line(NOW, log).met
    log.write_text(json.dumps(rows[0]), encoding="utf-8")
    assert not rd.drill_line(NOW, log).met
    old = [{**r, "at": "2026-09-01T10:00:00+00:00"} for r in rows]
    log.write_text("\n".join(json.dumps(r) for r in old), encoding="utf-8")
    assert not rd.drill_line(NOW, log).met


def test_guardian_hold_blocks_the_strategy_it_names(tmp_path: Path) -> None:
    log = tmp_path / "g.jsonl"
    log.write_text(
        json.dumps({"rule": "too_good", "why": "net Sharpe H-0175 3.97"}), encoding="utf-8"
    )
    assert not rd.guardian_line("H-0175", log).met
    assert rd.guardian_line("H-0161", log).met


def test_no_pilot_block_means_no_pilot() -> None:
    line, sessions = rd.pilot_line({"min_days": 60})
    assert not line.met and sessions == 10
    line, sessions = rd.pilot_line(
        {"pilot": {"max_capital": 100000, "daily_loss_halt": 2000, "min_live_price_sessions": 8}}
    )
    assert line.met and sessions == 8


def test_verdict_today_is_not_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)  # no proof, no drill, no go, no guardian log
    lines = rd.checklist(
        "H-0161",
        deployments=[Dep("paper-H-0161-x", "H-0161")],
        summary={},
        now=NOW,
        mandate={"forward_test": {"min_days": 60}},
    )
    names = {x.check: x for x in lines}
    assert names["active paper book"].met
    assert not names["Kite order path proved (S-015)"].met
    assert not names["operator's go"].met
    assert rd.verdict(lines) == {"pilot": False, "full": False}


def test_go_must_name_the_strategy(tmp_path: Path) -> None:
    go = tmp_path / "go.json"
    go.write_text(
        json.dumps({"strategies": ["H-0161"], "at": "x", "note": "pilot"}), encoding="utf-8"
    )
    assert rd.go_line("H-0161", go).met
    assert not rd.go_line("H-0175", go).met


def _unused(_: Any) -> None:  # keeps the import of Any honest for mypy
    return None
