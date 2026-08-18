"""Fundamentals storage: snapshots, never overwrites."""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq

from eulerlab.fundamentals.screener_fetch import Fetched, FundamentalsStore
from eulerlab.fundamentals.screener_parse import Cell


def _fetched(symbol: str = "RELIANCE") -> Fetched:
    return Fetched(
        symbol=symbol,
        name="Reliance Industries Ltd",
        consolidated=True,
        cells=[
            Cell("quarters", "Sales", "2024-03-31", 1234.0, "1,234"),
            Cell("quarters", "Sales", "2024-06-30", None, "-"),
        ],
        html_bytes=1000,
    )


def test_a_snapshot_is_written_with_knowledge_time(tmp_path: Path) -> None:
    store = FundamentalsStore(tmp_path)
    path = store.write(_fetched(), "2026-08-18")

    table = pq.read_table(path)
    assert table.num_rows == 2
    assert "knowledge_time" in table.column_names
    assert table.to_pydict()["knowledge_time"][0].endswith("+00:00")


def test_a_none_value_survives_the_round_trip(tmp_path: Path) -> None:
    store = FundamentalsStore(tmp_path)
    path = store.write(_fetched(), "2026-08-18")
    assert pq.read_table(path).to_pydict()["value"][1] is None


def test_has_reports_a_same_day_fetch(tmp_path: Path) -> None:
    store = FundamentalsStore(tmp_path)
    assert not store.has("RELIANCE", "2026-08-18")
    store.write(_fetched(), "2026-08-18")
    assert store.has("RELIANCE", "2026-08-18")


def test_a_different_day_is_a_separate_snapshot(tmp_path: Path) -> None:
    """Fundamentals get restated. Keeping each fetch dated is what makes
    point-in-time reconstruction possible; overwriting would destroy it."""
    store = FundamentalsStore(tmp_path)
    store.write(_fetched(), "2026-08-18")
    store.write(_fetched(), "2026-08-19")

    assert store.has("RELIANCE", "2026-08-18")
    assert store.has("RELIANCE", "2026-08-19")
    assert len(list((tmp_path / "RELIANCE").glob("*.parquet"))) == 2


def test_the_manifest_survives_a_reload(tmp_path: Path) -> None:
    FundamentalsStore(tmp_path).write(_fetched(), "2026-08-18")
    assert FundamentalsStore(tmp_path).has("RELIANCE", "2026-08-18")


def test_no_partial_files_are_left_behind(tmp_path: Path) -> None:
    store = FundamentalsStore(tmp_path)
    store.write(_fetched(), "2026-08-18")
    assert list(tmp_path.rglob("*.part")) == []
