"""Paper trading for the research studies (`deploy/study_book.py`).

The adapter was checked against real data on 2026-10-17: run over each study's
own 2024 window it reproduced the stored trade logs exactly (Donchian 530 of
530, initial-balance failure 774 of 774, Hikkake 915 of 915). These tests pin
the parts that need no data.
"""

from __future__ import annotations

import types
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from eulerlab.deploy import deployments as store
from eulerlab.deploy import study_book
from eulerlab.deploy.runner import make_oms

DAYS = [date(2026, 10, 19), date(2026, 10, 20)]


@pytest.fixture
def deployment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> store.Deployment:
    monkeypatch.setattr(store, "ROOT", tmp_path)
    created = store.create(
        "nse_github_donchian_breakout", mode="paper", capital=200_000.0, start=DAYS[0]
    )
    return store.Deployment.model_validate({**created.model_dump(), "slippage_bps": 0.0})


def _trade(day: date, symbol: str, direction: int, entry: float, exit_: float) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "day": day,
        "direction": direction,
        "quantity": 10,
        "entry": entry,
        "exit": exit_,
        "minute": 30,
    }


def test_long_and_short_legs_go_through_the_oms(deployment: store.Deployment) -> None:
    out = study_book.replay(
        deployment,
        make_oms(deployment),
        trades=[_trade(DAYS[0], "TCS", 1, 100.0, 101.0), _trade(DAYS[1], "INFY", -1, 50.0, 49.0)],
        sessions=DAYS,
        through=DAYS[-1],
        traded_through=None,
    )
    assert [(f["symbol"], f["side"]) for f in out["fills"]] == [
        ("TCS", "buy"),
        ("TCS", "sell"),
        ("INFY", "sell"),
        ("INFY", "buy"),
    ]
    assert out["held"] == {} and out["sent"] == 4
    assert out["equity"] == pytest.approx(200_000.0 + 10 + 10 - out["costs"], abs=0.01)


def test_a_new_trade_on_a_day_already_traded_halts(deployment: store.Deployment) -> None:
    out = study_book.replay(
        deployment,
        make_oms(deployment),
        trades=[_trade(DAYS[0], "TCS", 1, 100.0, 101.0)],
        sessions=DAYS,
        through=DAYS[-1],
        traded_through=DAYS[1],
    )
    assert "minute history changed" in out["halt"]


def test_normalise_reads_side_or_direction_and_derives_quantity() -> None:
    short = study_book.normalise(
        {
            "symbol": "X",
            "day": "2026-10-19",
            "side": "short",
            "entry": 100.0,
            "exit": 98.0,
            "gross_pnl": 40.0,
        }
    )
    assert (short["direction"], short["quantity"]) == (-1, 20)
    flat = study_book.normalise(
        {
            "symbol": "X",
            "day": "2026-10-19",
            "direction": 1,
            "entry": 100.0,
            "exit": 100.0,
            "gross_pnl": 0.0,
        },
        notional=250_000.0,
    )
    assert (flat["direction"], flat["quantity"]) == (1, 2_500)


def test_the_study_runs_on_the_paper_window_and_is_put_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def load_days(symbol: str, **kw: Any) -> list[Any]:
        calls.append({"symbol": symbol, **kw})
        return [types.SimpleNamespace(day=DAYS[0])]

    real = types.SimpleNamespace(load_days=load_days)
    module = types.ModuleType("fake_study")
    module.EVAL_START, module.DATA_END, module.rs = date(2024, 1, 1), date(2024, 11, 30), real  # type: ignore[attr-defined]
    module.CAPITAL, module.NOTIONAL = 100_000.0, 50_000.0  # type: ignore[attr-defined]

    def run_all() -> dict[str, Any]:
        module.rs.load_days("TCS", cutoff=module.DATA_END)
        assert (DAYS[0], DAYS[1]) == (module.EVAL_START, module.DATA_END)
        trade = {
            "symbol": "TCS",
            "day": "2026-10-19",
            "side": "long",
            "entry": 10.0,
            "exit": 11.0,
            "quantity": 7,
        }
        return {"runs": [{"id": "x", "trade_log": [trade]}]}

    module.run_all = run_all  # type: ignore[attr-defined]
    trades, sessions = study_book.study_trades(
        "x",
        start=DAYS[0],
        through=DAYS[1],
        since=date(2026, 10, 17),
        capital=200_000.0,
        module=module,
    )
    assert calls == [
        {"symbol": "TCS", "cutoff": DAYS[1], "cache": False, "since": date(2026, 10, 17)}
    ]
    assert trades[0]["quantity"] == 14, "sized to the deployment: 200k / 100k"
    assert sessions == [DAYS[0]]
    assert (module.EVAL_START, module.DATA_END, module.rs) == (
        date(2024, 1, 1),
        date(2024, 11, 30),
        real,
    )


def test_a_study_that_fails_still_has_its_window_put_back() -> None:
    module = types.ModuleType("broken_study")
    module.EVAL_START, module.DATA_END, module.rs = date(2024, 1, 1), date(2024, 11, 30), object()  # type: ignore[attr-defined]

    def run_all() -> dict[str, Any]:
        raise RuntimeError("needs a training window")

    module.run_all = run_all  # type: ignore[attr-defined]
    with pytest.raises(RuntimeError):
        study_book.study_trades(
            "x",
            start=DAYS[0],
            through=DAYS[1],
            since=date(2026, 10, 17),
            capital=1.0,
            module=module,
        )
    assert date(2024, 1, 1) == module.EVAL_START


def test_which_studies_the_book_runs() -> None:
    assert study_book.module_of("nse_github_donchian_breakout") == "github_donchian"
    assert study_book.module_of("nse_initial_balance_failure") == "company_github"
    assert study_book.module_of("gao_last_half_hour") is None


def test_the_research_112_screens_run_through_their_own_runner() -> None:
    for strategy_id in study_book.FIVE:
        assert study_book.module_of(strategy_id) == "india_five"
