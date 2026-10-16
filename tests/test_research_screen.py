"""Focused checks for the fixed candidate screen and its data cutoff."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from eulerlab.intraday import india_papers as ip
from eulerlab.intraday import research_screen as rs
from eulerlab.intraday import strategy_optimizer as optimizer


def test_archive_file_crossing_cutoff_is_not_opened(tmp_path: Path) -> None:
    root = tmp_path / "bars"
    folder = root / "GOLDBEES"
    folder.mkdir(parents=True)
    allowed = folder / "2024-10-02_2024-11-30.parquet"
    crossing = folder / "2024-12-01_2025-01-29.parquet"
    allowed.write_bytes(b"eligible")
    crossing.write_bytes(b"must never be read")

    loaded = rs._files("GOLDBEES", root=root)

    assert [name for name, _ in loaded] == [str(allowed)]
    assert loaded[0][1] == b"eligible"


def test_optimizer_can_read_complete_files_through_a_new_frozen_cutoff(tmp_path: Path) -> None:
    root = tmp_path / "bars"
    folder = root / "GOLDBEES"
    folder.mkdir(parents=True)
    before = folder / "2024-12-01_2025-01-29.parquet"
    crossing = folder / "2025-01-30_2025-03-30.parquet"
    before.write_bytes(b"eligible for a 2025 test")
    crossing.write_bytes(b"extends beyond the frozen cutoff")

    loaded = rs._files("GOLDBEES", root=root, cutoff=date(2025, 2, 28))

    assert [name for name, _ in loaded] == [str(before)]


def test_fixed_gold_averages_match_expected_values() -> None:
    values = [1.0, 2.0, 4.0]
    assert rs._average(values, "sma") == pytest.approx(7 / 3)
    assert rs._average(values, "wma") == pytest.approx(17 / 6)
    assert rs._average(values, "ema", 3) == pytest.approx(2.75)


def test_gold_rule_executes_only_after_the_signal_bar() -> None:
    bars = {
        minute: (
            100.0 + minute / 100,
            100.0 + minute / 100,
            100.0 + minute / 100,
            100.0 + minute / 100,
            10_000.0,
        )
        for minute in range(ip.MINUTES)
    }
    day = ip.days_from_rows({"2024-01-02": bars})[0]

    run = rs._gold_rule([day], method="sma", slow=2)

    assert run["evaluation_2024_through_2024_11_30"]["days"] == 1
    assert run["fills"] >= 2, (
        "the screen entered after a completed signal bar and flattened at close"
    )
    assert run["instrument"].startswith("GOLDBEES")


def test_decision_tree_features_require_complete_bars() -> None:
    bars = {
        minute: (100.0, 101.0, 99.0, 100.0 + minute / 1000, 1000.0) for minute in range(ip.MINUTES)
    }
    complete = ip.days_from_rows({"2024-01-02": bars})[0]
    assert len(rs._tree_features(complete, 211) or []) == 9

    del bars[100]
    with_gap = ip.days_from_rows({"2024-01-02": bars})[0]
    assert rs._tree_features(with_gap, 211) is None


def test_gold_confirmation_filter_skips_alternating_whipsaws() -> None:
    bars = {}
    for minute in range(ip.MINUTES):
        bar = minute // 5
        price = 100.1 if bar % 2 else 99.9
        bars[minute] = (price, price, price, price, 1_000.0)
    day = ip.days_from_rows({"2024-01-02": bars})[0]

    unfiltered = optimizer._gold(
        [day], method="sma", slow=2, confirm=1, band_bps=0, start=day.day, end=day.day
    )
    filtered = optimizer._gold(
        [day],
        method="sma",
        slow=2,
        confirm=2,
        band_bps=0,
        start=day.day,
        end=day.day,
        base_trades=unfiltered["trades"],
    )

    assert unfiltered["trades"] > 0
    assert filtered["trades"] < unfiltered["trades"]
    assert filtered["trade_reduction_pct"] > 0
