"""The headline Sharpe at fills an order could get, and the page's luck bar from it (ADR-205)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from eulerlab.research import realistic_sharpe as rs
from eulerlab.validation import search_bar as sb
from test_search_bar import RULES, _series, _store

GATED: dict[str, dict[str, Any]] = {
    "H-0202": {
        "id": "H-0202",
        "sharpe": 12.75,
        "verdict": "PROMOTE",
        "first": "2005-01-03",
        "last": "2024-11-29",
    },
    "H-0162": {
        "id": "H-0162",
        "sharpe": 1.77,
        "verdict": "PROMOTE",
        "first": "2021-07-01",
        "last": "2024-11-29",
    },
    "H-0111": {"id": "H-0111", "sharpe": None, "verdict": "KILL"},
}
REPRICE: list[dict[str, Any]] = [
    {
        "id": "H-0202",
        "kind": "intraday",
        "window": "2018-11-01..2024-11-29",
        "coverage": 0.335,
        "sharpe_official": 4.435,
        "sharpe_0925_1510": 0.821,
        "sharpe_executable": -0.318,
    },
    # A swing card's reprice is not its headline: its fills are already realistic.
    {"id": "H-0162", "kind": "swing", "window": "2021-07-01..2024-11-29", "sharpe_executable": 0.9},
]


def test_an_intraday_card_leads_with_its_reprice_and_keeps_the_official_figure() -> None:
    figures = rs.build(GATED, REPRICE)
    h = figures["H-0202"]
    assert h.basis == "0925_1510_spread_impact"
    assert h.sharpe == -0.318
    assert (h.official_sharpe, h.official_window) == (4.435, "2018-11-01..2024-11-29")
    assert (h.gate_sharpe, h.gate_window) == (12.75, "2005-01-03..2024-11-29")
    assert h.coverage == 0.335


def test_swing_and_unrepriced_cards_lead_with_the_gate_and_unscored_ones_are_absent() -> None:
    figures = rs.build(GATED, REPRICE)
    assert figures["H-0162"].basis == "gated"
    assert figures["H-0162"].sharpe == 1.77
    assert "H-0111" not in figures


def test_a_reprice_that_failed_is_ignored() -> None:
    figures = rs.build(GATED, [{"id": "H-0202", "kind": "intraday", "error": "boom"}])
    assert figures["H-0202"].basis == "gated"


def test_the_final_gated_run_is_the_latest_pass() -> None:
    first = [{"id": "A", "sharpe": 5.0}, {"id": "B", "sharpe": 1.0}]
    at_1x = [{"id": "A", "sharpe": 2.0}]
    portfolio = [{"id": "P", "sharpe": 0.8}, {"id": "P", "sharpe": 0.9}]
    final = rs.final_gated(first, (), at_1x, portfolio)
    assert {k: v["sharpe"] for k, v in final.items()} == {"A": 2.0, "B": 1.0, "P": 0.9}


def test_write_and_load_round_trip(tmp_path: Path) -> None:
    target = rs.write(rs.build(GATED, REPRICE), tmp_path / "r.json")
    assert rs.load(target)["H-0202"].sharpe == -0.318
    assert rs.load(tmp_path / "missing.json") == {}


def test_shift_to_sets_the_sharpe_and_keeps_the_volatility() -> None:
    returns = _series(7, drift=0.002)
    shifted = rs.shift_to(returns, 0.5)
    values = list(shifted.values())
    mean = sum(values) / len(values)
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))
    assert abs(mean / sd * math.sqrt(252) - 0.5) < 1e-9
    before = list(returns.values())
    assert all(
        abs((a - b) - (values[0] - before[0])) < 1e-12 for a, b in zip(values, before, strict=True)
    )


def test_the_page_bar_counts_realistic_sharpes_and_the_default_is_untouched(tmp_path: Path) -> None:
    # Four unrelated strategies, one of them with a large official-fill Sharpe.
    for k in range(4):
        _store(tmp_path, f"s{k}", _series(400 + k, drift=0.006 if k == 0 else 0.0002 * k))
    gate_bar = sb.shown_bar(RULES, ledger_bar=9.99, root=tmp_path)
    page_bar = sb.shown_bar(RULES, ledger_bar=9.99, root=tmp_path, sharpes={"s0": 0.3})
    again = sb.shown_bar(RULES, ledger_bar=9.99, root=tmp_path)
    assert gate_bar.families is not None and page_bar.families is not None
    # The outlier pulled to a realistic Sharpe narrows the spread, so the bar falls.
    assert page_bar.families.sigma < gate_bar.families.sigma
    assert page_bar.value < gate_bar.value
    assert page_bar.families.families == gate_bar.families.families
    assert "realistic fills" in page_bar.basis
    # The gate's default call returns the same bar as before.
    assert again.value == gate_bar.value
    assert "The gate's bar" in again.basis
