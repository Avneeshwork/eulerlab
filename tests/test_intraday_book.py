"""Paper trading for the minute-bar strategies (`deploy/intraday_book.py`)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from eulerlab.deploy import deployments as store
from eulerlab.deploy import intraday_book as book
from eulerlab.deploy.runner import make_oms
from eulerlab.intraday.bracket import Exit, Trade
from eulerlab.intraday.tweezer import Plan

HOLDOUT_END = date(2026, 10, 17)
DAYS = [date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)]


@dataclass
class FakeScan:
    trades: list[Trade]
    rejections: dict[str, int] = field(default_factory=dict)
    _session_dates: list[date] = field(default_factory=lambda: list(DAYS))


def _trade(day: date, entry: float, exit_price: float, shares: int = 10) -> Trade:
    at = datetime(day.year, day.month, day.day, 10, 0, tzinfo=UTC)
    plan = Plan(at, entry, entry - 1, entry + 1, entry + 2, 1.0, shares, 0, 0.01)
    return Trade(
        plan=plan,
        entry_ts=at,
        entry_price=entry,
        exits=[
            Exit(
                datetime(day.year, day.month, day.day, 14, 0, tzinfo=UTC),
                exit_price,
                shares,
                "target",
            )
        ],
    )


@pytest.fixture
def deployment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> store.Deployment:
    monkeypatch.setattr(store, "ROOT", tmp_path)
    created = store.create("orb_breakout_in", mode="paper", capital=100_000.0, start=DAYS[0])
    return store.Deployment.model_validate({**created.model_dump(), "slippage_bps": 0.0})


def _replay(deployment: store.Deployment, trades: list[Trade], **kw: Any) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def scan(strategy_id: str, symbol: str, **args: Any) -> FakeScan:
        seen.update(args)
        return FakeScan(trades)

    out = book.replay(
        deployment,
        make_oms(deployment),
        symbol="NIFTYBEES",
        market="equity",
        through=kw.pop("through", DAYS[-1]),
        end_of_holdout=kw.pop("end_of_holdout", HOLDOUT_END),
        traded_through=kw.pop("traded_through", None),
        scan=scan,
    )
    out["read_from"] = seen.get("start")
    return out


def test_each_leg_goes_through_the_oms_and_the_curve_is_by_session(
    deployment: store.Deployment,
) -> None:
    out = _replay(deployment, [_trade(DAYS[1], 250.0, 252.0)])
    assert [(f["side"], f["quantity"], f["price"]) for f in out["fills"]] == [
        ("buy", 10, 250.0),
        ("sell", 10, 252.0),
    ]
    assert out["sent"] == 2 and out["held"] == {}
    gain = 20.0 - out["costs"]
    assert [day for day, _ in out["curve"]] == [d.isoformat() for d in DAYS]
    assert out["curve"][0][1] == 100_000.0
    assert out["curve"][1][1] == pytest.approx(100_000.0 + gain, abs=0.01)


def test_nothing_on_or_before_the_holdout_end_is_read(deployment: store.Deployment) -> None:
    out = _replay(deployment, [])
    assert out["read_from"] == date(2026, 10, 18), "warmup stops at the holdout end"


def test_a_deployment_starting_inside_the_holdout_halts(deployment: store.Deployment) -> None:
    out = _replay(deployment, [], end_of_holdout=DAYS[0])
    assert "inside the holdout" in out["halt"]


def test_trades_before_the_start_are_not_taken(deployment: store.Deployment) -> None:
    out = _replay(deployment, [_trade(date(2026, 10, 18), 250.0, 260.0)])
    assert out["fills"] == [] and out["sent"] == 0


def test_a_new_trade_on_a_day_already_traded_halts(deployment: store.Deployment) -> None:
    """Changed minute history must not put a trade in the past."""
    out = _replay(deployment, [_trade(DAYS[0], 250.0, 251.0)], traded_through=DAYS[1])
    assert "minute history changed" in out["halt"]


def test_rerunning_sends_nothing_twice(deployment: store.Deployment) -> None:
    trades = [_trade(DAYS[0], 250.0, 251.0)]
    first = _replay(deployment, trades)
    again = _replay(deployment, trades, traded_through=DAYS[-1])
    assert first["sent"] == 2 and again["sent"] == 0
    assert again["curve"] == first["curve"]


def test_first_session_is_after_creation_and_the_holdout() -> None:
    assert book.first_session(date(2026, 10, 20), HOLDOUT_END) == date(2026, 10, 21)
    assert book.first_session(date(2026, 10, 10), HOLDOUT_END) == date(2026, 10, 18)


def test_without_a_holdout_end_the_strategy_cannot_deploy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(book, "holdout_end", lambda: None)
    monkeypatch.setattr(book, "instrument", lambda sid: ("NIFTYBEES", "equity"))
    assert "holdout_end" in book.blocker("orb_breakout_in")
    monkeypatch.setattr(book, "holdout_end", lambda: HOLDOUT_END)
    assert book.blocker("orb_breakout_in") == ""
