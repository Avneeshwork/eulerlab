"""The forward-test stage: gate PROMOTE, a paper deployment after it, its record, and the Kite read-only check (T-3311)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from eulerlab import forward
from eulerlab.deploy.deployments import Deployment
from eulerlab.validation import ledger

FORMULA = "formula:ts_rank(close, 504)"
DAY = date(2026, 11, 2)


def _deployment(
    strategy: str, start: date, mode: str = "paper", status: str = "active"
) -> Deployment:
    return Deployment(
        id=f"{mode}-{strategy}-{start}",
        strategy_id=strategy,
        mode=mode,
        capital=1_000_000,
        start=start,
        created_at="2026-11-02T00:00:00+00:00",
        status=status,
    )


def _card(root: Path, hid: str, configs: int = 1) -> None:
    root.mkdir(parents=True, exist_ok=True)
    config: dict[str, Any] = {
        "shape": "rank_and_hold",
        "feature": FORMULA,
        "top_n": 30,
        "rebalance": 5,
        "min_turnover": 10_000_000,
    }
    (root / f"{hid}.yaml").write_text(
        yaml.safe_dump({"id": hid, "configurations": [config] * configs}, sort_keys=False)
    )


def test_the_latest_gate_verdict_wins(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger.append(
        kind="gate", subject="H-0030", params={}, outcome={"verdict": "PROMOTE"}, path=path
    )
    ledger.append(kind="validation", subject="H-0030", params={}, outcome={}, path=path)
    ledger.append(
        kind="gate", subject="H-0031", params={}, outcome={"verdict": "PROMOTE"}, path=path
    )
    ledger.append(kind="gate", subject="H-0031", params={}, outcome={"verdict": "KILL"}, path=path)
    found = forward.verdicts(path)
    assert found["H-0030"][0] == "PROMOTE" and found["H-0031"][0] == "KILL"
    assert forward.promoted_on("H-0030", found) is not None
    assert forward.promoted_on("H-0031", found) is None


def test_stage_needs_a_promotion_and_a_paper_deployment_started_after_it() -> None:
    gate = {"H-0030": ("PROMOTE", DAY), "H-0031": ("KILL", DAY)}
    assert forward.stage("H-0031", gate=gate, deployments=[]) == ""
    assert forward.stage("H-0030", gate=gate, deployments=[]) == "promoted"
    before = _deployment("H-0030", date(2026, 11, 1))
    assert forward.stage("H-0030", gate=gate, deployments=[before]) == "promoted"
    after = _deployment("H-0030", DAY)
    assert forward.stage("H-0030", gate=gate, deployments=[after]) == "forward_testing"
    stopped = _deployment("H-0030", DAY, status="stopped")
    assert forward.stage("H-0030", gate=gate, deployments=[stopped]) == "promoted"
    live = _deployment("H-0030", DAY, mode="live")
    assert forward.stage("H-0030", gate=gate, deployments=[after, live]) == "live"


def test_the_strategy_list_shows_forward_testing() -> None:
    from eulerlab import strategies

    gate = {"H-0030": ("PROMOTE", DAY)}
    got = strategies._stage("H-0030", 1, gate, [_deployment("H-0030", DAY)])
    assert got is strategies.Stage.FORWARD_TESTING
    assert strategies._stage("H-0030", 1, gate, []) is strategies.Stage.BACKTESTED
    assert strategies._stage("H-0030", 0, {}, []) is strategies.Stage.REGISTERED


def test_a_promoted_card_trades_exactly_its_one_configuration(tmp_path: Path) -> None:
    _card(tmp_path, "H-0030")
    built = forward.build("H-0030", tmp_path)
    assert built.rebalance_every == 5 and built.min_turnover == 10_000_000 and built.top_n == 30
    assert built.name.startswith("H-0030: ")
    _card(tmp_path, "H-0032", configs=2)
    with pytest.raises(ValueError, match="2 configurations"):
        forward.build("H-0032", tmp_path)


def test_only_a_promoted_hypothesis_can_be_deployed(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    _card(tmp_path, "H-0030")
    _card(tmp_path, "H-0031")
    assert "never been through the gate" in forward.blocker("H-0030", ledger=path, root=tmp_path)
    ledger.append(
        kind="gate", subject="H-0030", params={}, outcome={"verdict": "PROMOTE"}, path=path
    )
    ledger.append(kind="gate", subject="H-0031", params={}, outcome={"verdict": "KILL"}, path=path)
    assert forward.blocker("H-0030", ledger=path, root=tmp_path) == ""
    assert "dead" in forward.blocker("H-0031", ledger=path, root=tmp_path)


def test_the_forward_record_and_the_mandate_rule() -> None:
    d = _deployment("H-0030", DAY)
    curve = [[f"2026-11-{i + 2:02d}", 100.0 + i + (i % 3)] for i in range(10)]
    no_rule = forward.report(d, {"curve": curve}, tested_sharpe=1.2, rule={})
    assert no_rule.days == 9 and no_rule.sharpe is not None and no_rule.ready is None
    assert "not set in mandate.yaml" in no_rule.reasons[0]
    strict = forward.report(
        d, {"curve": curve}, tested_sharpe=1.2, rule={"min_days": 60, "max_drawdown": 0.2}
    )
    assert strict.ready is False and "9 trading days of 60" in strict.reasons[0]
    met = forward.report(d, {"curve": curve}, tested_sharpe=1.2, rule={"min_days": 5})
    assert met.ready is True and met.reasons == []
    empty = forward.report(d, None, tested_sharpe=None, rule={"min_days": 5})
    assert empty.days == 0 and empty.ready is False


def test_the_rule_comes_only_from_the_mandate() -> None:
    assert forward.rules({"statistical": {}}) == {}
    assert forward.rules({"forward_test": {"min_days": 60}}) == {"min_days": 60}


class _FakeKite:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def profile(self) -> dict[str, Any]:
        return {"user_id": "AB1234"}

    def margins(self, segment: str) -> dict[str, Any]:
        return {"available": {"live_balance": 250000.0}}

    def positions(self) -> dict[str, list[dict[str, Any]]]:
        return {"net": [], "day": []}

    def orders(self) -> list[dict[str, Any]]:
        return []

    def holdings(self) -> list[dict[str, Any]]:
        return [
            {"tradingsymbol": "NIFTYBEES", "quantity": 10, "opening_quantity": 10, "t1_quantity": 0}
        ]

    def place_order(self, **kwargs: Any) -> str:
        self.sent.append("place")
        return "1"


def test_the_kite_check_reads_through_the_adapter_and_cannot_send() -> None:
    from eulerlab.broker import kite_check

    fake = _FakeKite()
    result = kite_check.check(fake)
    assert result.ok, result.lines
    assert any("AB1234" in line for line in result.lines)
    assert any("1 holding" in line for line in result.lines)
    with pytest.raises(kite_check.WriteRefused):
        kite_check.ReadOnly(fake).place_order(tradingsymbol="X")
    assert fake.sent == []


def test_broker_credentials_mean_key_secret_and_todays_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eulerlab.api import server
    from eulerlab.broker import kite_session

    monkeypatch.setenv("ZERODHA_API_KEY", "k")
    monkeypatch.setenv("ZERODHA_API_SECRET", "s")
    monkeypatch.delenv("ZERODHA_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(kite_session, "load", lambda *a, **k: None)
    ok, detail = server._credentials_present()
    assert not ok and "make kite-login" in detail
    monkeypatch.setattr(kite_session, "is_fresh", lambda *a, **k: True)
    ok, detail = server._credentials_present()
    assert ok, detail


def test_a_paper_verdict_reaches_only_the_paper_stages() -> None:
    gate = {"H-0040": ("PAPER", DAY)}
    assert forward.promoted_on("H-0040", gate) is None
    assert forward.paper_on("H-0040", gate) == DAY
    assert forward.stage("H-0040", gate=gate, deployments=[]) == "paper_candidate"
    started = _deployment("H-0040", DAY)
    assert forward.stage("H-0040", gate=gate, deployments=[started]) == "paper_evaluation"
    from eulerlab import strategies

    assert strategies._stage("H-0040", 1, gate, [started]) is strategies.Stage.PAPER_EVALUATION


def test_a_paper_verdict_can_be_paper_deployed(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    _card(tmp_path, "H-0040")
    ledger.append(kind="gate", subject="H-0040", params={}, outcome={"verdict": "PAPER"}, path=path)
    assert forward.blocker("H-0040", ledger=path, root=tmp_path) == ""
