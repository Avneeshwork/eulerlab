"""The 2000-2014 history file: read by research only, less proved-wrong rows (ADR-189)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from eulerlab import constitution
from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.backtest.vector import run
from eulerlab.features import panel_mask as pm
from eulerlab.features.panel import PanelRow
from eulerlab.intraday import daily_universe_screen as du

FILE = Path(__file__).parents[1] / "config" / "constitution.yaml"


def _constitution(tmp_path: Path, **periods: str) -> Path:
    raw: dict[str, Any] = yaml.safe_load(FILE.read_text())
    raw["periods"].update(periods)
    path = tmp_path / "constitution.yaml"
    path.write_text(yaml.safe_dump(raw))
    return path


def test_the_research_start_is_2016_until_the_constitution_says_otherwise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(constitution.RESEARCH_END_ENV, raising=False)
    assert constitution.research_window(FILE)[0] == date(2016, 1, 1)
    earlier = _constitution(tmp_path, research_start="2005-01-01")
    assert constitution.research_window(earlier) == (date(2005, 1, 1), date(2025, 12, 31))


def test_a_research_start_after_discovery_end_does_not_load(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="research_start < discovery_end"):
        constitution.load(_constitution(tmp_path, research_start="2024-06-01"))


def _line(day: str, symbol: str, close: float, isin: str) -> str:
    row = {"d": day, "s": symbol, "o": close, "c": close, "t": 1.0, "isin": isin}
    return json.dumps(row, sort_keys=True) + "\n"


def test_an_early_window_joins_the_history_file_less_wrong_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    panel, history, mask = tmp_path / "p.jsonl", tmp_path / "h.jsonl", tmp_path / "m.jsonl"
    panel.write_text(_line("2015-01-02", "ABC", 12.0, "INE000A010"))
    history.write_text(
        _line("2010-06-01", "ABC", 10.0, "INE000A010")
        + _line("2010-06-02", "ABC", 99.0, "INE000A010")  # proved wrong below
        + _line("2010-06-03", "ABC", 10.2, "INE000A010")
    )
    wrong = pm.Entry(
        "INE000A010",
        date(2010, 6, 2),
        "next session's PREVCLOSE differs",
        True,
        pm._at_close(date(2010, 6, 3)),
    )
    pm.write(mask, [wrong])
    monkeypatch.setattr(du, "PANEL", panel)
    monkeypatch.setattr(pm, "HISTORY_PATH", history)
    monkeypatch.setattr(pm.active, "__defaults__", (mask,))
    got = du.load_panel(panel, start=date(2010, 1, 1), end=date(2015, 12, 31))
    assert sorted(got["ABC"]) == [date(2010, 6, 1), date(2010, 6, 3), date(2015, 1, 2)]
    late = du.load_panel(panel, start=date(2015, 1, 1), end=date(2015, 12, 31))
    assert sorted(late["ABC"]) == [date(2015, 1, 2)]  # 2015 on: the history file is not read


def test_vector_never_fills_at_a_print_proved_wrong(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start = date(2016, 1, 1)  # the cost schedule starts 2015; the mask does not care
    rows = [
        PanelRow(
            day=start + timedelta(days=d),
            symbol="SYM",
            close=100.0,
            volume=1e3,
            turnover=1e6,
            isin="INE000A010",
        )
        for d in range(120)
    ]
    bad_day = rows[61].day  # the first fill day after a decision on day 60
    rows[61] = PanelRow(
        day=bad_day, symbol="SYM", close=999.0, volume=1e3, turnover=1e6, isin="INE000A010"
    )

    class Hold(Strategy):
        name = "hold"

        def target_weights(self, view: MarketView) -> dict[str, float]:
            return {"SYM": 1.0}

    monkeypatch.setattr(pm.active, "__defaults__", (tmp_path / "none.jsonl",))
    unmasked = run(rows, Hold(), warmup=60, rebalance_every=200, asset_class="equity")
    assert [(f.day, f.price) for f in unmasked.fills] == [(bad_day, 999.0)]
    mask = tmp_path / "m.jsonl"
    entry = pm.Entry(
        "INE000A010", bad_day, "next session's PREVCLOSE differs", True, pm._at_close(rows[62].day)
    )
    pm.write(mask, [entry])
    monkeypatch.setattr(pm.active, "__defaults__", (mask,))
    result = run(rows, Hold(), warmup=60, rebalance_every=200, asset_class="equity")
    assert all(f.day != bad_day and f.price != 999.0 for f in result.fills)
