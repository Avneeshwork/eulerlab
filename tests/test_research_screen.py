"""Focused checks for the fixed candidate screen and its data cutoff."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from eulerlab.intraday import india_papers as ip
from eulerlab.intraday import strategy_optimizer as optimizer
from eulerlab.strategies.studies import research as rs


def test_archive_file_crossing_cutoff_is_not_opened(tmp_path: Path) -> None:
    root = tmp_path / "bars"
    folder = root / "GOLDBEES"
    folder.mkdir(parents=True)
    end = rs.DATA_END
    allowed = folder / f"{end - timedelta(days=59)}_{end}.parquet"
    crossing = folder / f"{end - timedelta(days=29)}_{end + timedelta(days=30)}.parquet"
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


def _minute_parquet(rows: list[tuple[str, float]]) -> bytes:
    import io

    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.table(
        {
            "ts": [ts for ts, _ in rows],
            "open": [p for _, p in rows],
            "high": [p for _, p in rows],
            "low": [p for _, p in rows],
            "close": [p for _, p in rows],
            "volume": [100 for _ in rows],
        }
    )
    buf = io.BytesIO()
    pq.write_table(table, buf)
    return buf.getvalue()


def test_history_adds_rescaled_angel_bars_before_kite(monkeypatch: pytest.MonkeyPatch) -> None:
    """T-4634: Angel bars from 2018-11 to Kite's first day, times the ADR-185 factor."""
    from types import SimpleNamespace

    from eulerlab.ingest import angel_rescale, landing_reader

    angel = "angel_minute_history/AAA/2018-10-20_2018-11-05.parquet"

    def session(day: str) -> list[tuple[str, float]]:
        return [
            (f"{day}T{9 + (15 + m) // 60:02d}:{(15 + m) % 60:02d}:00+0530", 50.0)
            for m in range(375)
        ]

    blobs = {angel: _minute_parquet(session("2018-10-31") + session("2018-11-01"))}
    monkeypatch.setattr(
        landing_reader,
        "available",
        lambda tree, pattern="**/*", **_: [angel] if tree == "angel_minute_history" else [],
    )
    monkeypatch.setattr(landing_reader, "read", lambda name, **_: blobs[name])
    monkeypatch.setattr(ip, "archive_files", lambda symbol: [])
    factor = SimpleNamespace(factor=2.0, volume_factor=0.5)
    monkeypatch.setattr(angel_rescale, "load_factors", lambda: {"AAA": factor})

    days = rs.load_days("AAA", cache=False, history=True)
    assert [d.day for d in days] == [date(2018, 11, 1)]  # 31 Oct is before the floor
    assert days[0].open_[0] == 100.0  # rescaled to Kite's basis
    assert rs.load_days("AAA", cache=False) == []  # off by default

    monkeypatch.setattr(angel_rescale, "load_factors", dict)
    assert rs.load_days("AAA", cache=False, history=True) == []  # no factor, no history


def test_index_history_is_opt_in_and_stops_at_kite(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-201: Angel's NIFTY50 minutes before Kite's index start, only when asked."""
    from eulerlab.ingest import landing_reader
    from eulerlab.strategies.studies import cash_five as five

    def session(day: str, price: float) -> list[tuple[str, float]]:
        return [
            (f"{day}T{9 + (15 + m) // 60:02d}:{(15 + m) % 60:02d}:00+0530", price)
            for m in range(375)
        ]

    angel = "angel_minute_history/NIFTY50/2018-11-01_2021-11-05.parquet"
    kite = "kite_index_minute/NIFTY50/2021-11-01_2021-11-05.parquet"
    blobs = {
        angel: _minute_parquet(session("2018-11-01", 10.0) + session("2021-11-01", 99.0)),
        kite: _minute_parquet(session("2021-11-01", 20.0)),
    }
    monkeypatch.setattr(
        landing_reader,
        "available",
        lambda tree, pattern="**/*", **_: [angel] if tree == "angel_minute_history" else [kite],
    )
    monkeypatch.setattr(landing_reader, "read", lambda name, **_: blobs[name])
    assert [d.day for d in five.load_index(history=False)] == [date(2021, 11, 1)]
    days = five.load_index(history=True)
    assert [d.day for d in days] == [date(2018, 11, 1), date(2021, 11, 1)]
    assert days[1].close[0] == 20.0  # Kite's day, not Angel's overlap
    monkeypatch.setenv(rs.HISTORY_ENV, "1")
    assert len(five.load_index()) == 2


def test_the_research_1x_switch_sizes_the_mft_screens_at_1x(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-202: ₹1 lakh a position with the switch, ₹5 lakh (5x MIS, as registered) without."""
    import importlib

    from eulerlab.strategies.studies import mft as mft_screen

    monkeypatch.delenv(rs.ONE_X_ENV, raising=False)
    assert importlib.reload(mft_screen).TRADE == 500_000.0
    monkeypatch.setenv(rs.ONE_X_ENV, "1")
    one_x = importlib.reload(mft_screen)
    assert one_x.TRADE * one_x.MAX_OPEN <= one_x.CAPITAL  # never more exposure than capital
    monkeypatch.delenv(rs.ONE_X_ENV)
    importlib.reload(mft_screen)
