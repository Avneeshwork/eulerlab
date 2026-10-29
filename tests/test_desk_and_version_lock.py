"""The trade desk's tickets and the strategy version lock (ADR-087)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from eulerlab import desk
from eulerlab.deploy import version_lock

DEPLOYMENT = SimpleNamespace(
    id="paper-mom-2026-10-01-abc123", strategy_id="mom", mode="paper", capital=100000.0
)
STATE = {
    "equity": 100000.0,
    "book": [
        {"symbol": "AAA", "quantity": 10, "value": 30000},
        {"symbol": "BBB", "quantity": 5, "value": 20000},
    ],
    "intended": {"names": ["AAA", "CCC"], "wanted": 2, "affordable": 2},
    "next_rebalance": "2026-11-01",
}


def test_a_ticket_lists_sells_buys_holds_and_its_checks() -> None:
    ticket = desk.build(DEPLOYMENT, STATE, max_notional=60000, max_per_second=5)
    assert [s["symbol"] for s in ticket.sells] == ["BBB"]
    assert [b["symbol"] for b in ticket.buys] == ["CCC"]
    assert ticket.holds == ["AAA"]
    assert ticket.buys[0]["target_value"] == pytest.approx(100000 * desk.GROSS / 2)
    assert not ticket.blocked
    assert ticket.est_cost > 0


def test_the_ticket_id_is_deterministic() -> None:
    assert desk.build(DEPLOYMENT, STATE).id == desk.build(DEPLOYMENT, STATE).id


def test_a_tripped_switch_or_a_big_buy_blocks_the_ticket() -> None:
    assert desk.build(DEPLOYMENT, STATE, tripped="daily loss").blocked
    assert desk.build(DEPLOYMENT, STATE, max_notional=1000).blocked
    assert desk.build(DEPLOYMENT, STATE, lock=(False, "code changed")).blocked


def test_a_blocked_ticket_cannot_be_approved_and_a_decision_is_final() -> None:
    blocked = desk.build(DEPLOYMENT, STATE, tripped="daily loss")
    with pytest.raises(ValueError, match="blocked"):
        desk.decide(blocked, "approved")
    clean = desk.build(DEPLOYMENT, STATE)
    desk.decide(clean, "approved", "looks right")
    with pytest.raises(ValueError, match="already"):
        desk.decide(clean, "rejected")
    assert desk.approved_today(DEPLOYMENT.id)
    assert not desk.approved_today(DEPLOYMENT.id, now=datetime(2030, 1, 1, tzinfo=UTC))


def test_the_lock_is_written_once_and_reports_a_change(tmp_path: Path) -> None:
    first = version_lock.check(tmp_path, "mom", current="aaa")
    assert first.status == "locked-now"
    assert version_lock.check(tmp_path, "mom", current="aaa").status == "same"
    changed = version_lock.check(tmp_path, "mom", current="bbb")
    assert changed.changed and "make relock" in changed.detail
    assert version_lock.check(tmp_path, "mom", current="").status == "unavailable"


def test_relock_needs_a_note_and_keeps_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    version_lock.check(tmp_path, "mom", current="aaa")
    monkeypatch.setattr(version_lock, "fingerprint", lambda _: "bbb")
    with pytest.raises(ValueError):
        version_lock.relock(tmp_path, "mom", " ")
    version_lock.relock(tmp_path, "mom", "reviewed the lookback fix")
    saved = json.loads((tmp_path / version_lock.FILE).read_text())
    assert saved["fingerprint"] == "bbb" and saved["history"][0]["fingerprint"] == "aaa"


def test_a_real_overnight_strategy_has_a_fingerprint() -> None:
    from eulerlab.deploy import overnight

    some = next(iter(overnight.STRATEGIES))
    assert len(version_lock.fingerprint(some)) == 64
