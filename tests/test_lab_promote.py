"""An approved idea-lab survivor is registered, validated and gated with no further tap (ADR-116)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml

from eulerlab.agents.runtime import Item
from eulerlab.research import promote

FORMULA = "formula:neg(ts_std(ret(1), 63))"


def _card(tmp_path: Path, floor: float = 10_000_000) -> Path:
    folder = tmp_path / "ideas" / "2026-11-01" / "neg-ts-std-ret-1-63-liq10000000"
    folder.mkdir(parents=True)
    config: dict[str, Any] = {
        "shape": "rank_and_hold",
        "feature": FORMULA,
        "top_n": 30,
        "rebalance": 21,
    }
    if floor:
        config["min_turnover"] = floor
    path = folder / "card.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "id": "PENDING",
                "title": "low volatility",
                "status": "draft",
                "claim": "calm stocks earn more",
                "configurations": [config],
                "red_flags": ["generated"],
                "holdout": {"starts": "2025-01-01", "status": "unread"},
            },
            sort_keys=False,
        )
    )
    return path


def _item(path: Path, survivors: int = 1) -> Item:
    return Item(kind="finding", title="x survived", ref=str(path), data={"survivors": survivors})


def test_only_a_floored_lab_survivor_is_eligible(tmp_path: Path) -> None:
    good = _card(tmp_path)
    assert promote.eligible("lab", _item(good)) == good
    assert promote.eligible("lab", _item(good.parent)) == good
    with pytest.raises(promote.Refused, match="only idea lab"):
        promote.eligible("research", _item(good))
    with pytest.raises(promote.Refused, match="not a survivor"):
        promote.eligible("lab", _item(good, survivors=0))
    old = _card(tmp_path / "old", floor=0)
    with pytest.raises(promote.Refused, match="liquidity floor"):
        promote.eligible("lab", _item(old))


def test_register_takes_a_fresh_id_keeps_the_configurations_and_happens_once(
    tmp_path: Path,
) -> None:
    path = _card(tmp_path)
    hyps = tmp_path / "hypotheses"
    hyps.mkdir()
    (hyps / "H-0001.yaml").write_text("id: H-0001\n")
    hid = promote.register(path, hyps)
    assert hid == "H-0002"
    written = yaml.safe_load((hyps / "H-0002.yaml").read_text())
    original = yaml.safe_load(path.read_text())
    assert written["configurations"] == original["configurations"]
    assert written["id"] == "H-0002" and written["status"] == "draft"
    with pytest.raises(promote.Refused, match="already registered"):
        promote.eligible("lab", _item(path))


def test_gate_runs_validate_then_the_gate_and_records_its_verdict(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def run(cmd: Sequence[str]) -> tuple[int, str]:
        calls.append(list(cmd))
        if "eulerlab.gate_run" in cmd:
            return 1, "gate: H-0001\n\nVERDICT: KILL — 2 of 9 rules failed\n"
        return 0, "evidence written"

    out = promote.gate(
        "lab/r/1", _card(tmp_path), hypotheses=tmp_path / "h", folder=tmp_path / "p", run=run
    )
    assert out.hypothesis == "H-0001" and out.verdict == "KILL — 2 of 9 rules failed"
    assert [c[2] for c in calls] == ["eulerlab.validation.run", "eulerlab.gate_run"]
    assert not any("--read-holdout" in c for c in calls), "the holdout stays the operator's"
    saved = json.loads((tmp_path / "p" / "H-0001.json").read_text())
    assert saved["verdict"].startswith("KILL")
    assert promote.results(tmp_path / "p")[0]["hypothesis"] == "H-0001"


def test_a_pass_gets_its_library_report_stored_in_its_own_process(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def run(cmd: Sequence[str]) -> tuple[int, str]:
        calls.append(list(cmd))
        if "eulerlab.gate_run" in cmd:
            return 0, "VERDICT: PROMOTE — all 9 rules passed\n"
        return 0, "stored" if "eulerlab.research.library_reports" in cmd else "evidence written"

    out = promote.gate(
        "lab/r/2", _card(tmp_path), hypotheses=tmp_path / "h", folder=tmp_path / "p", run=run
    )
    assert [c[2] for c in calls] == [
        "eulerlab.validation.run",
        "eulerlab.gate_run",
        "eulerlab.research.library_reports",
    ]
    assert calls[-1][-2:] == ["--only", out.hypothesis]
    assert out.report_output == "stored"


def test_a_kill_stores_no_report(tmp_path: Path) -> None:
    calls: list[str] = []

    def run(cmd: Sequence[str]) -> tuple[int, str]:
        calls.append(cmd[2])
        return (
            (1, "VERDICT: KILL — 1 of 9 rules failed\n") if "eulerlab.gate_run" in cmd else (0, "")
        )

    out = promote.gate(
        "lab/r/3", _card(tmp_path), hypotheses=tmp_path / "h", folder=tmp_path / "p", run=run
    )
    assert "eulerlab.research.library_reports" not in calls and out.report_output == ""


def test_a_rank_and_hold_card_is_stored_as_a_factor_card(tmp_path: Path) -> None:
    from eulerlab.research import library_reports as lr

    hyps = tmp_path / "hypotheses"
    hyps.mkdir()
    (hyps / "H-0901.yaml").write_text(_card(tmp_path).read_text())
    (hyps / "H-0902.yaml").write_text(
        yaml.safe_dump({"configurations": [{"shape": "options_day", "feature": "x"}]})
    )
    assert lr.is_factor_card("H-0901", hyps)
    assert not lr.is_factor_card("H-0902", hyps)


def test_a_failed_validation_never_reaches_the_gate(tmp_path: Path) -> None:
    calls: list[str] = []

    def run(cmd: Sequence[str]) -> tuple[int, str]:
        calls.append(cmd[2])
        return 2, "no panel"

    out = promote.gate(
        "i", _card(tmp_path), hypotheses=tmp_path / "h", folder=tmp_path / "p", run=run
    )
    assert calls == ["eulerlab.validation.run"] and out.verdict.startswith("validation stopped")


def test_validation_builds_a_lab_card_exactly_as_the_lab_tested_it() -> None:
    from eulerlab.backtest.strategies import RankAndHold
    from eulerlab.validation import run as validation

    strategy, rebalance = validation._strategy_for(
        {"feature": FORMULA, "top_n": 30, "rebalance": 21, "min_turnover": 10_000_000}
    )
    assert isinstance(strategy, RankAndHold)
    assert strategy.min_turnover == 10_000_000 and rebalance == 21
    plain, _ = validation._strategy_for({"feature": "momentum_12_1", "top_n": 30, "rebalance": 21})
    assert plain.min_turnover == 0


def test_approving_a_survivor_in_the_inbox_sends_it_to_the_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab.agents import inbox
    from eulerlab.api import agent_routes as r

    path = _card(tmp_path)
    sent: list[tuple[Any, ...]] = []
    monkeypatch.setattr(inbox, "find", lambda item_id: ("lab", _item(path)))
    monkeypatch.setattr(r._GATE_POOL, "submit", lambda *a: sent.append(a))
    assert r._gate_on_approve("lab/x/1").startswith("sent to the gate")
    assert sent and sent[0][1:] == ("lab/x/1", path)

    monkeypatch.setattr(inbox, "find", lambda item_id: ("lab", _item(_card(tmp_path / "o", 0))))
    assert "liquidity floor" in r._gate_on_approve("lab/x/2")
    monkeypatch.setattr(inbox, "find", lambda item_id: ("research", _item(path)))
    assert r._gate_on_approve("research/x/3") == ""
    assert len(sent) == 1


def test_results_list_every_rule_the_gate_printed_failed_and_passed(tmp_path: Path) -> None:
    from eulerlab.gates import Decision, Finding

    decision = Decision(
        "H-0099",
        [
            Finding("deflated sharpe", False, "best 0.512, mandate requires >= 0.95"),
            Finding("probability of overfitting", True, "12.0%, mandate allows <= 50%"),
            Finding("trial ledger", True, ""),
        ],
    )
    folder = tmp_path / "promote"
    folder.mkdir()
    (folder / "H-0099.json").write_text(
        json.dumps({"item": "i", "started": "2026-11-02", "gate_output": decision.render()}),
        encoding="utf-8",
    )
    (row,) = promote.results(folder)
    assert row["findings"] == [
        {
            "rule": "deflated sharpe",
            "passed": False,
            "detail": "best 0.512, mandate requires >= 0.95",
        },
        {
            "rule": "probability of overfitting",
            "passed": True,
            "detail": "12.0%, mandate allows <= 50%",
        },
        {"rule": "trial ledger", "passed": True, "detail": ""},
    ]
    assert promote.findings("validation stopped") == []


def test_a_card_whose_positions_cannot_be_rebuilt_still_gets_a_report() -> None:
    from eulerlab.research import library_reports as lr
    from eulerlab.validation.intraday import IntradayRun

    run = IntradayRun([], [], [], 1_000_000.0)
    assert lr._fills_for("H-9999", run) == ([], 0)
    assert "not rebuilt" in lr.NO_POSITIONS
