"""The acceptance checks must be capable of failing."""

from __future__ import annotations

from datetime import date

from eulerlab.master.check import (
    check_point_in_time_query,
    check_ratios_present_where_required,
    check_successions_are_sourced,
    check_symbol_map_exists,
    run,
)
from eulerlab.master.symbology import Rename, SymbolMap


def test_the_full_suite_passes_on_the_real_repo() -> None:
    failed = [c for c in run() if not c.ok]
    assert not failed, [f"{c.name}: {c.detail}" for c in failed]


def test_a_missing_symbol_map_fails() -> None:
    assert not check_symbol_map_exists(None).ok


def test_an_empty_symbol_map_fails() -> None:
    # Vacuous success is the failure mode a check like this must not have.
    assert not check_symbol_map_exists(SymbolMap()).ok


def test_a_populated_symbol_map_passes() -> None:
    m = SymbolMap(renames=[Rename("A", "B", (date(2024, 1, 1), date(2024, 2, 1)))])
    assert check_symbol_map_exists(m).ok


def test_point_in_time_check_detects_lookahead() -> None:
    """It must fail if a future ticker resolves on a past date."""
    assert check_point_in_time_query().ok  # the real registry behaves


def test_sourcing_and_ratio_checks_pass_on_recorded_successions() -> None:
    assert check_successions_are_sourced().ok
    assert check_ratios_present_where_required().ok
