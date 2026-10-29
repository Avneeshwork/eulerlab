"""The data quality contract, quarantine and the grid rule (ADR-086)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from eulerlab.quality import contract, quarantine
from eulerlab.research import grid_rule


def _register() -> contract.Register:
    return contract.Register.model_validate(
        {
            "datasets": [
                {
                    "name": "Cash bhavcopy",
                    "tree": "nse",
                    "segment": "cm",
                    "publisher": "NSE",
                    "url": "https://nsearchives.nseindia.com",
                    "licence": "reviewed",
                    "knowledge_time": "after the close",
                    "critical": True,
                    "min_grade": "C",
                },
                {
                    "name": "Price panel",
                    "derived": "missing/panel.parquet",
                    "built_from": ["Cash bhavcopy"],
                    "publisher": "built here",
                    "url": "local",
                    "licence": "own",
                    "knowledge_time": "inherits",
                    "critical": True,
                    "min_grade": "B",
                },
            ]
        }
    )


def _landing(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    (tmp_path / "nse").mkdir(parents=True)
    (tmp_path / "nse" / "manifest.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return tmp_path


ROW: dict[str, object] = {
    "path": "nse/cm/2026-10-28.csv",
    "segment": "cm",
    "sha256": "a" * 64,
    "knowledge_time": "2026-10-28T13:00:00+00:00",
}


def _grade(tmp_path: Path, rows: list[dict[str, object]]) -> dict[str, contract.Graded]:
    graded = contract.grade_all(
        register=_register(),
        coverage=lambda: [SimpleNamespace(name="Cash bhavcopy", status="ok")],
        findings=list,
        landing=_landing(tmp_path, rows),
    )
    return {g.name: g for g in graded}


def test_a_fingerprinted_source_grades_well_and_a_missing_derived_table_is_d(
    tmp_path: Path,
) -> None:
    grades = _grade(tmp_path, [ROW])
    assert grades["Cash bhavcopy"].grade in ("A", "B")
    assert grades["Cash bhavcopy"].freshness == "ok"
    assert grades["Price panel"].grade == "D" and not grades["Price panel"].usable


def test_a_held_file_lowers_the_grade(tmp_path: Path) -> None:
    before = _grade(tmp_path / "a", [ROW])["Cash bhavcopy"].grade
    quarantine.hold("Cash bhavcopy", "nse/cm/2026-10-28.csv", "sha mismatch")
    after = _grade(tmp_path / "b", [ROW])["Cash bhavcopy"]
    assert after.grade > before
    assert any(c.name == "quarantine" and c.state == "fail" for c in after.checks)


def test_guard_refuses_low_grade_data_unless_asked(tmp_path: Path) -> None:
    grades = list(_grade(tmp_path, [ROW]).values())
    with pytest.raises(contract.LowGrade):
        contract.guard(["Price panel"], grades=grades, log=lambda _: None)
    lines: list[str] = []
    contract.guard(["Price panel"], allow_low=True, grades=grades, log=lines.append)
    assert any("low-grade" in line for line in lines)


def test_quarantine_is_append_only_and_release_needs_a_note() -> None:
    quarantine.hold("Cash bhavcopy", "f.csv", "bad rows")
    assert quarantine.is_held("Cash bhavcopy", "f.csv")
    with pytest.raises(ValueError):
        quarantine.release("Cash bhavcopy", "f.csv", "")
    quarantine.release("Cash bhavcopy", "f.csv", "refetched and checked")
    assert not quarantine.is_held("Cash bhavcopy", "f.csv")
    assert [r.action for r in quarantine.history()] == ["hold", "release"]


def test_the_real_register_loads_and_names_the_panel() -> None:
    names = {s.name for s in contract.load_register().datasets}
    assert {"Cash bhavcopy", "Price panel"} <= names


def test_grades_round_trip_through_the_saved_file(tmp_path: Path) -> None:
    grades = list(_grade(tmp_path, [ROW]).values())
    contract.save(grades)
    assert {g["name"] for g in contract.saved()} == {"Cash bhavcopy", "Price panel"}


GRIDS = {"mom": ("H-0001", {"lookback": [20.0, 60.0, 120.0]})}


def test_a_sweep_inside_the_card_grid_passes_and_outside_is_refused() -> None:
    assert grid_rule.enforce("mom", {"lookback": [20, 60]}, GRIDS) == "H-0001"
    assert grid_rule.enforce("other", {"x": [1]}, GRIDS) == ""
    with pytest.raises(grid_rule.OutsideCard):
        grid_rule.enforce("mom", {"lookback": [20, 90]}, GRIDS)
    with pytest.raises(grid_rule.OutsideCard):
        grid_rule.enforce("mom", {"stop": [0.05]}, GRIDS)


def test_plateau_compares_each_point_with_its_neighbours() -> None:
    space = {"lookback": [20, 60, 120]}
    rows = grid_rule.plateau(
        [({"lookback": 20}, 0.2), ({"lookback": 60}, 2.0), ({"lookback": 120}, 0.3)], space
    )
    peak = next(r for r in rows if r["params"]["lookback"] == 60)
    assert peak["neighbours"] == 2 and peak["plateau"] < peak["value"]
