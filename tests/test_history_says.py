"""What history says: matching past days, no look-ahead, too few means no numbers (ADR-109)."""

from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path

from eulerlab.agents import history_says
from eulerlab.agents.history_says import Day

S = history_says.Setup(
    start="2015-01-01",
    trend_window=20,
    vix_window=20,
    vix_low_below=30,
    vix_high_from=70,
    gap_sessions=5,
    gap_points=3.0,
    horizons=[1, 5],
    min_matches=5,
)


def _days(n: int = 400) -> list[Day]:
    start = date(2016, 1, 1)
    out = []
    for i in range(n):
        wave = math.sin(i / 9)
        out.append(
            Day(
                start + timedelta(days=i),
                100 + 10 * wave + i * 0.01,
                15 + 5 * math.cos(i / 7),
                100 + 12 * math.sin(i / 11),
            )
        )
    return out


def test_a_day_state_uses_only_closes_up_to_that_day() -> None:
    days = _days()
    i = 250
    before = history_says.state(days, i, S)
    changed = days[: i + 1] + [
        Day(d.day, d.nifty * 3, d.vix * 5, d.small / 4) for d in days[i + 1 :]
    ]
    assert before is not None and history_says.state(changed, i, S) == before


def test_base_rates_report_counts_and_withhold_numbers_when_too_few() -> None:
    days = _days()
    out = history_says.base_rates(days, S)
    assert out["available"] and out["matches"] > 0 and out["episodes"] <= out["matches"]
    for row in out["horizons"]:
        if row["n"] >= S.min_matches:
            assert {"median", "up", "worst_10"} <= set(row) and row["worst_10"] <= row["median"]
        else:
            assert row.get("too_few") and "median" not in row
    strict = history_says.base_rates(days, S.model_copy(update={"min_matches": 10_000}))
    assert all(r.get("too_few") for r in strict["horizons"])
    lines = history_says.describe(strict, 10_000)
    assert any("too few to lean on" in line for line in lines) and lines[-1].startswith(
        "History, not a forecast."
    )


def test_a_match_never_counts_a_return_that_runs_past_the_last_day() -> None:
    days = _days()
    out = history_says.base_rates(days, S)
    last = days[-1].day.isoformat()
    assert last not in out["match_days"]
    five = next(r for r in out["horizons"] if r["sessions"] == 5)
    one = next(r for r in out["horizons"] if r["sessions"] == 1)
    assert five["n"] <= one["n"] <= out["matches"]


def test_books_use_the_session_after_each_match_or_say_what_is_missing(tmp_path: Path) -> None:
    trading = ["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06"]
    folder = tmp_path / "s1"
    folder.mkdir()
    (folder / "r.json").write_text(
        json.dumps({"equity": {"days": trading, "values": [100, 101, 99.99, 102]}})
    )
    returns = history_says.longest_backtest(folder)
    assert round(returns["2026-01-02"], 4) == 0.01
    books = [
        {"strategy": "s1", "status": "active"},
        {"strategy": "s2", "status": "active"},
        {"strategy": "s3", "status": "halted"},
    ]
    lines = history_says.books_in_this_market(
        books, ["2026-01-01", "2026-01-05"], trading, {"s1": returns, "s2": {}}, 2
    )
    assert lines[0].startswith(
        "s1: in its backtest, the session after a day like today returned a median"
    )
    assert "(2 days)" in lines[0]
    assert (
        lines[1]
        == "s2: its backtest's daily returns are not saved, so there is nothing to compare."
    )
    assert len(lines) == 2


def test_the_shipped_setup_loads_and_never_touches_the_gate() -> None:
    s = history_says.setup()
    assert s.horizons == [1, 5, 20] and s.min_matches == 30
    source = Path("src/eulerlab/agents/history_says.py").read_text()
    assert "gates" not in source.split('"""', 2)[2] and "ledger" not in source.split('"""', 2)[2]
