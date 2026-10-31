"""/api/history can back-adjust equity bars for splits and bonuses (the SIP needs it)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from eulerlab.api import server
from eulerlab.backtest import vector
from eulerlab.features.panel import PanelRow

BONUS_DAY = date(2024, 10, 28)


def _rows() -> list[PanelRow]:
    # A 1:1 bonus: 3000 before, 1500 after, with no change in value.
    days = [date(2024, 10, 24), date(2024, 10, 25), BONUS_DAY, date(2024, 10, 29)]
    closes = [3000.0, 3000.0, 1500.0, 1500.0]
    return [
        PanelRow(day=d, symbol="RELIANCE", close=c, volume=1, turnover=1.0, isin="INE002A01018")
        for d, c in zip(days, closes, strict=True)
    ]


class _Panel:
    def rows(self, days: int = 0) -> list[PanelRow]:
        return _rows()


@pytest.fixture
def bonus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "PANEL", _Panel())

    def adjusted(rows: Any, **_: Any) -> dict[str, dict[date, float]]:
        return {"RELIANCE": {r.day: r.close / 2 if r.day < BONUS_DAY else r.close for r in rows}}

    monkeypatch.setattr(vector, "build_adjusted_index", adjusted)


def test_raw_bars_by_default(bonus: None) -> None:
    out = server.history("RELIANCE")
    assert [b["close"] for b in out["bars"]] == [3000.0, 3000.0, 1500.0, 1500.0]
    assert out["adjusted"] is False


def test_adjusted_bars_have_no_bonus_cliff(bonus: None) -> None:
    out = server.history("RELIANCE", adjusted=True)
    assert [b["close"] for b in out["bars"]] == [1500.0, 1500.0, 1500.0, 1500.0]
    assert out["bars"][0]["open"] == 1500.0
    assert out["adjusted"] is True
