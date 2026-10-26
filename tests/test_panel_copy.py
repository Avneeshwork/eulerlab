"""The panel's columnar copy (`panel.COLUMNS_DIR`) answers exactly as the JSONL does."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from eulerlab.features import panel


def _key(row: panel.PanelRow) -> tuple[object, ...]:
    return tuple((name, type(getattr(row, name)), getattr(row, name)) for name in panel._FIELDS)


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


ROWS: list[dict[str, object]] = [
    # A rename (OLDCO -> NEWCO, same ISIN), a day out of symbol order, and a
    # second day: the copy must hold the renamed, sorted result.
    {"d": "2026-01-05", "s": "ZED", "c": 1.5, "v": 10.0, "t": 15.0, "isin": "INE3", "o": 1.0, "h": 2.0, "l": 0.5},
    {"d": "2026-01-05", "s": "OLDCO", "c": 10.0, "v": 1.0, "t": 10.0, "isin": "INE1", "o": 9.0, "h": 11.0, "l": 8.0},
    {"d": "2026-01-05", "s": "AAA", "c": 2.0, "v": 3.0, "t": 6.0, "isin": "INE2", "o": 2.0, "h": 2.0, "l": 2.0},
    {"d": "2026-01-06", "s": "NEWCO", "c": 11.0, "v": 2.0, "t": 22.0, "isin": "INE1", "o": 10.0, "h": 12.0, "l": 9.5},
    {"d": "2026-01-06", "s": "AAA", "c": 2.5, "v": 4.0, "t": 10.0, "isin": "INE2", "o": 2.1, "h": 2.6, "l": 2.0},
]  # fmt: skip


@pytest.fixture
def source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "price_panel.jsonl"
    _write(path, ROWS)
    monkeypatch.setattr(panel, "PANEL_PATH", path)
    return path


def test_the_copy_gives_the_rows_the_jsonl_gives(source: Path) -> None:
    expected = panel.canonical_symbols(panel._parse_jsonl(source))
    first = panel.read_panel(source)
    assert (panel.COLUMNS_DIR / "price_panel.columns.parquet").exists()
    second = panel.read_panel(source)
    assert [_key(r) for r in first] == [_key(r) for r in expected]
    assert [_key(r) for r in second] == [_key(r) for r in expected]
    assert [r.symbol for r in second] == ["AAA", "NEWCO", "ZED", "AAA", "NEWCO"]
    # One string per symbol, as the JSONL reader keeps.
    assert second[0].symbol is second[3].symbol


def test_a_changed_panel_is_never_answered_from_the_old_copy(source: Path) -> None:
    panel.read_panel(source)
    _write(source, [*ROWS, {**ROWS[-1], "d": "2026-01-07", "c": 3.0}])
    os.utime(source, ns=(1, 2))  # a different time even on a coarse clock
    assert panel.read_panel(source)[-1].day.isoformat() == "2026-01-07"


def test_no_copy_is_made_when_a_value_would_come_back_different(source: Path) -> None:
    _write(source, [{**ROWS[0], "v": 10}])  # an int: it would come back as 10.0
    panel.read_panel(source)
    assert not (panel.COLUMNS_DIR / "price_panel.columns.parquet").exists()


def test_only_the_default_panel_gets_a_copy(tmp_path: Path) -> None:
    other = tmp_path / "elsewhere.jsonl"
    _write(other, ROWS)
    panel.read_panel(other)
    assert not list(panel.COLUMNS_DIR.iterdir())


def test_the_names_as_stored_always_come_from_the_jsonl(source: Path) -> None:
    panel.read_panel(source)
    raw = panel.read_panel(source, canonical=False)
    assert "OLDCO" in {r.symbol for r in raw}


def test_a_renamed_stock_gets_the_days_asked_for_not_its_whole_history(source: Path) -> None:
    """The older name's rows came uncapped (2026-10-27)."""
    rows = panel.read_symbol_rows("NEWCO", 1, source)
    assert [(r.day.isoformat(), r.symbol) for r in rows] == [("2026-01-06", "NEWCO")]
    both = panel.read_symbol_rows("NEWCO", 5, source)
    assert [(r.day.isoformat(), r.close) for r in both] == [
        ("2026-01-05", 10.0),
        ("2026-01-06", 11.0),
    ]


def test_the_in_memory_symbol_rows_match_the_file_and_step_aside_when_it_changes(
    source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab.api import panels

    monkeypatch.setattr(panels, "PANEL_PATH", source)
    monkeypatch.setattr(panels, "read_panel", lambda: panel.read_panel(source))
    held = panels._Panel()
    held.rows()
    for symbol in ("NEWCO", "AAA", "ZED"):
        for days in (1, 2, 5):
            memory = held.symbol_rows(symbol, days)
            assert memory is not None
            assert [_key(r) for r in memory] == [
                _key(r) for r in panel.read_symbol_rows(symbol, days, source)
            ]
    os.utime(source, ns=(5, 5))
    assert held.symbol_rows("AAA", 2) is None  # the caller reads the file instead
