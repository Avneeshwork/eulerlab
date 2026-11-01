"""The Strategies table's plain-terms figures."""

from __future__ import annotations

from typing import Any

from eulerlab import results as result_store
from eulerlab.api import server
from eulerlab.workspace import resolve


def item(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "x",
        "asset_class": "equity",
        "sharpe": 0.5,
        "clears_bar": False,
        "result": {"total_return": 0.2},
        "adopted": None,
    }
    base.update(changes)
    return base


def test_the_verdict_is_the_bar_in_words() -> None:
    tenant = resolve(None)
    assert (
        server._table_figures(tenant, item(clears_bar=True, sharpe=3.0), 2.9)["verdict"]
        == "beats_bar"
    )
    assert server._table_figures(tenant, item(), 2.9)["verdict"] == "positive"
    lost = item(sharpe=-0.4, result={"total_return": -0.1})
    assert server._table_figures(tenant, lost, 2.9)["verdict"] == "loses"
    never = item(sharpe=None, result={})
    assert server._table_figures(tenant, never, 2.9)["verdict"] == "not_run"


def test_every_listed_strategy_carries_its_table_figures() -> None:
    fleet = server.fleet()
    assert fleet["strategies"]
    for row in fleet["strategies"]:
        assert row["table"]["verdict"] in {"beats_bar", "positive", "loses", "not_run"}
        assert "logic" in row


def test_the_row_shows_its_latest_run_not_the_ledgers_older_sharpe(
    monkeypatch: Any,
) -> None:
    """One row, one run (HISTORY #52).

    `momentum_12_1` showed the ledger's validated 1.27 and "beats the bar"
    beside the return and drawdown of its latest run, whose Sharpe is 0.39.
    """
    from types import SimpleNamespace

    row = SimpleNamespace(declaration=SimpleNamespace(id="momentum_12_1"), sharpe=1.2667)
    latest = SimpleNamespace(sharpe=0.385, universe="nifty250", at="2026-10-30")
    monkeypatch.setattr(result_store, "latest", lambda *a, **k: latest)
    assert server._headline_sharpe(resolve(None), row, {}) == 0.385
    assert not server._clears(resolve(None), row, 0.98, {})

    monkeypatch.setattr(result_store, "latest", lambda *a, **k: None)
    assert server._headline_sharpe(resolve(None), row, {}) == 1.2667
