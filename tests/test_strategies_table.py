"""The Strategies table's plain-terms figures."""

from __future__ import annotations

from typing import Any

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
