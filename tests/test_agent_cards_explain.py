"""Agent cards say what was found, not just how many (T-4212)."""

from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path

import pytest

from eulerlab.agents import runtime
from eulerlab.agents.runtime import Item, WorkerResult
from eulerlab.agents.workers import skeptic
from eulerlab.api import agent_routes as r


def test_activity_carries_the_findings_worst_first() -> None:
    def worker(ctx: runtime.Context) -> WorkerResult:
        return WorkerResult(
            "1 alert",
            [
                Item(kind="finding", title="a note", severity="info"),
                Item(kind="finding", title="a warning", severity="warn", ref="make check-costs"),
                Item(kind="alert", title="book halted", body="history changed", severity="warn"),
                Item(kind="finding", title="panel grade D", severity="critical"),
            ],
        )

    runtime.run("operations", worker=worker)
    rows = {row["name"]: row for row in r.agents_activity()["agents"]}
    found = rows["operations"]["findings"]
    assert [f["title"] for f in found] == ["panel grade D", "book halted", "a warning", "a note"]
    assert found[1]["body"] == "history changed"
    assert rows["operations"]["findings_total"] == 4
    assert rows["lab"]["cli_only"] is True and "Sunday" in rows["lab"]["schedule"]


def _report(path: Path, drift: float) -> None:
    days = [date(2019, 1, 1) + timedelta(days=i) for i in range(900)]
    values = [100.0]
    for i in range(1, 900):
        values.append(values[-1] * (1 + drift + 0.01 * math.sin(i)))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"equity": {"days": [d.isoformat() for d in days], "values": values}})
    )


def test_the_skeptic_lists_targets_and_attacks_all_when_none_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(skeptic, "WORKSPACES", tmp_path)
    _report(tmp_path / "w1" / "reports" / "steady" / "a.json", 0.0008)
    _report(tmp_path / "w1" / "reports" / "flat" / "a.json", 0.0)
    (tmp_path / "w1" / "reports" / "broken").mkdir()
    (tmp_path / "w1" / "reports" / "broken" / "a.json").write_text("{not json")

    assert [t["strategy"] for t in skeptic.targets()] == ["broken", "flat", "steady"]

    out = runtime.run("skeptic", args={}, root=tmp_path / "agents")
    assert out.status == "ok"
    assert out.summary.startswith("Checked 2 stored results")
    assert "1 too short or unreadable" in out.summary
    assert {i.ref for i in out.items} == {"strategy=flat", "strategy=steady"}
    order = [{"critical": 0, "warn": 1, "info": 2}[i.severity] for i in out.items]
    assert order == sorted(order)
    # No model request is spent checking all of them.
    assert out.requests == 0


def test_the_skeptic_refuses_a_strategy_with_no_stored_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(skeptic, "WORKSPACES", tmp_path)
    out = runtime.run("skeptic", args={"strategy": "nothing_here"}, root=tmp_path / "agents")
    assert out.status == "refused" and "nothing_here" in out.summary


def test_the_skeptic_targets_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(skeptic, "WORKSPACES", tmp_path)
    _report(tmp_path / "w" / "reports" / "one" / "r.json", 0.0005)
    body = r.skeptic_targets()
    assert body["ok"] and body["targets"][0]["strategy"] == "one"
