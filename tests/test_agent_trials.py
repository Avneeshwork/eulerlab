"""The agents' trial allowance and the idea lab (ADR-089).

A synthetic panel where each name has its own steady drift, so trailing return
predicts forward return and momentum screens in; flat names screen out.
"""

from __future__ import annotations

import json
import math
import random
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from eulerlab.agents import runtime
from eulerlab.agents.spec import all_effective, effective
from eulerlab.features.panel import PanelRow
from eulerlab.research import agent_trials

START = date(2019, 1, 1)
HOLDOUT = date(2021, 1, 1)
NOW = datetime(2026, 10, 29, 6, 0, tzinfo=UTC)
ALLOW = agent_trials.Allowance(per_week=5)


def _panel(n_symbols: int = 60, n_days: int = 900, trending: bool = True) -> list[PanelRow]:
    rows: list[PanelRow] = []
    rng = random.Random(11)
    for s in range(n_symbols):
        drift = (s - n_symbols / 2) * 0.00004 if trending else 0.0
        price = 100.0
        for d in range(n_days):
            wiggle = 0.004 * math.sin(d * 0.7 + s) if trending else rng.gauss(0.0, 0.01)
            price *= 1.0 + drift + wiggle
            rows.append(
                PanelRow(
                    day=START + timedelta(days=d),
                    symbol=f"S{s:02d}",
                    close=price,
                    volume=1e5,
                    turnover=1e9,
                    isin=f"IN{s:010d}",
                )
            )
    return rows


def _card(tmp_path: Path, configs: str) -> Path:
    folder = tmp_path / "draft-a"
    folder.mkdir()
    path = folder / "card.yaml"
    path.write_text(
        "id: H-PENDING\ntitle: Momentum\nclaim: winners keep winning\n"
        f"configurations:\n{configs}"
        "red_flags: [crowded]\n"
        f"holdout: {{starts: '{HOLDOUT.isoformat()}', status: unread}}\n"
    )
    return path


ONE = "  - {feature: momentum_6_1, top_n: 10, rebalance: 21}\n"


def test_a_card_is_screened_then_backtested_and_every_step_is_a_trial(tmp_path: Path) -> None:
    log = tmp_path / "trials.jsonl"
    rows = _panel()
    out = agent_trials.test_card(
        _card(tmp_path, ONE), allowance=ALLOW, read_rows=lambda: rows, now=NOW, trials_path=log
    )
    assert out.card == "draft-a" and out.trials_spent == 2
    assert out.screened_in and len(out.backtests) == 1
    assert out.backtests[0].values[-1] != out.backtests[0].values[0]
    logged = [json.loads(x)["feature"] for x in log.read_text().splitlines()]
    assert logged == ["agent|draft-a|ic|momentum_6_1", "agent|draft-a|bt|momentum_6_1|top10|rb21"]
    assert agent_trials.spent_this_week(NOW, log) == 2


def test_the_holdout_is_never_seen(tmp_path: Path) -> None:
    rows = _panel()
    out = agent_trials.test_card(
        _card(tmp_path, ONE),
        allowance=ALLOW,
        read_rows=lambda: rows,
        now=NOW,
        trials_path=tmp_path / "t.jsonl",
    )
    assert max(out.backtests[0].days) < HOLDOUT.isoformat()
    assert "holdout rows withheld" in out.research_window


def test_a_flat_feature_screens_out_and_is_not_backtested(tmp_path: Path) -> None:
    rows = _panel(trending=False)
    out = agent_trials.test_card(
        _card(tmp_path, ONE),
        allowance=ALLOW,
        read_rows=lambda: rows,
        now=NOW,
        trials_path=tmp_path / "t.jsonl",
    )
    assert not out.screened_in and out.backtests == [] and out.trials_spent == 1


def test_a_card_that_does_not_fit_the_allowance_spends_nothing(tmp_path: Path) -> None:
    log = tmp_path / "t.jsonl"
    many = (
        ONE
        + "  - {feature: momentum_6_1, top_n: 20, rebalance: 21}\n" * 1
        + "  - {feature: momentum_12_1, top_n: 10, rebalance: 21}\n"
    )
    with pytest.raises(agent_trials.OverAllowance, match="needs 5 trials"):
        agent_trials.test_card(
            _card(tmp_path, many),
            allowance=agent_trials.Allowance(per_week=4),
            read_rows=list,
            now=NOW,
            trials_path=log,
        )
    assert not log.exists()


def test_the_week_resets_on_monday_ist(tmp_path: Path) -> None:
    log = tmp_path / "t.jsonl"
    log.write_text(
        json.dumps({"feature": "agent|x|ic|f", "logged_at": "2026-10-25T10:00:00+00:00"})
        + "\n"
        + json.dumps({"feature": "agent|x|ic|f", "logged_at": "2026-10-27T10:00:00+00:00"})
        + "\n"
        + json.dumps({"feature": "momentum_12_1", "logged_at": "2026-10-27T10:00:00+00:00"})
        + "\n"
    )
    assert agent_trials.spent_this_week(NOW, log) == 1
    assert agent_trials.left_this_week(ALLOW, NOW, log) == 4


def test_the_shipped_allowance_is_the_operators_choice() -> None:
    # Lifted by the operator on 2026-10-31 (ADR-107).
    assert agent_trials.load_allowance().per_week is None


def test_no_limit_never_runs_out(tmp_path: Path) -> None:
    log = tmp_path / "trials.jsonl"
    log.write_text(
        "".join(
            json.dumps({"feature": f"agent|H-1|{i}", "logged_at": "2026-10-27T10:00:00+00:00"})
            + "\n"
            for i in range(500)
        )
    )
    unlimited = agent_trials.Allowance(per_week=None)
    assert agent_trials.spent_this_week(NOW, log) == 500
    assert agent_trials.left_this_week(unlimited, NOW, log) == agent_trials.UNLIMITED
    assert agent_trials.describe(unlimited) == "no weekly limit"


def test_the_lab_sends_a_survivor_to_the_inbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab.features import panel, trials
    from eulerlab.quality import contract

    rows = _panel()
    monkeypatch.setattr(panel, "read_panel", lambda *a, **k: rows)
    monkeypatch.setattr(trials, "TRIALS_PATH", tmp_path / "trials.jsonl")
    monkeypatch.setattr(contract, "guard", lambda *a, **k: [])
    # The synthetic panel's signal is perfect, so its Sharpe is far above what the
    # doctor trusts (ADR-113); raise the line here to test the survivor path.
    from eulerlab.agents import doctor

    monkeypatch.setattr(doctor, "SUSPECT_SHARPE", 1e9)
    card = _card(tmp_path, ONE)
    agents = {"lab": effective(all_effective()["lab"].spec, None)}
    out = runtime.run(
        "lab", args={"card": str(card.parent)}, root=tmp_path / "agents", agents=agents, now=NOW
    )
    assert out.status == "ok", out.summary
    assert "2 trial(s) spent" in out.summary
    assert out.items and out.items[0].data["trials"] == 2
    again = runtime.run(
        "lab", args={"card": str(card.parent)}, root=tmp_path / "agents", agents=agents, now=NOW
    )
    assert "0 card(s) tested" in again.summary


def test_a_sharpe_too_good_to_trust_never_survives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab.agents import doctor
    from eulerlab.features import panel, trials
    from eulerlab.quality import contract

    rows = _panel()
    monkeypatch.setattr(panel, "read_panel", lambda *a, **k: rows)
    monkeypatch.setattr(trials, "TRIALS_PATH", tmp_path / "trials.jsonl")
    monkeypatch.setattr(contract, "guard", lambda *a, **k: [])
    card = _card(tmp_path, ONE)
    agents = {"lab": effective(all_effective()["lab"].spec, None)}
    out = runtime.run(
        "lab", args={"card": str(card.parent)}, root=tmp_path / "agents", agents=agents, now=NOW
    )
    assert "0 survived" in out.items[0].title
    log = (tmp_path / "agents" / doctor.FOLDER / doctor.LOG).read_text()
    assert "suspicious" in log


def test_the_lab_cannot_be_started_from_the_web_page() -> None:
    from eulerlab.api import agent_routes as r

    said = r.agent_run("lab", r.RunRequest())
    assert said["ok"] is False and "make agent NAME=lab" in said["error"]


def test_only_the_lab_can_reach_the_trial_path() -> None:
    from eulerlab.agents import boundaries

    assert boundaries.trial_spenders() == list(boundaries.TRIAL_SPENDERS)
