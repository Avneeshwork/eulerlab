"""Where a report's return came from (`attribution.py`)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from eulerlab import attribution

CONSTITUENTS = [
    {"symbol": "BIG", "contribution": 600.0, "open_qty": 0, "open_value": 0.0},
    {"symbol": "MID", "contribution": 300.0, "open_qty": 10, "open_value": 1300.0},
    {"symbol": "SMALL", "contribution": 200.0, "open_qty": 0, "open_value": 0.0},
    {"symbol": "LOSS", "contribution": -100.0, "open_qty": 0, "open_value": 0.0},
]


def test_concentration_and_the_return_without_the_best() -> None:
    found = attribution.holdings(CONSTITUENTS, starting_cash=1000.0, years=1.0)
    assert found["net_profit"] == 1000.0 and (found["winners"], found["losers"]) == (3, 1)
    assert found["share_of_profit"]["top_1"] == pytest.approx(0.6)
    assert found["names_for_half"] == 1 and found["names_for_four_fifths"] == 2
    assert found["without_top_1"]["total_return"] == pytest.approx(0.4)
    # Only the three winners are removed; the loser stays: -100 / 1000.
    assert found["without_top_5"]["total_return"] == pytest.approx(-0.1)
    assert [w["symbol"] for w in found["worst"]] == ["LOSS"]


def test_sectors_add_up_and_unknowns_are_said() -> None:
    found = attribution.sectors(
        CONSTITUENTS, {"BIG": ("IT", "Software"), "MID": ("IT", "Services")}
    )
    rows = {r["name"]: r for r in found["sector"]}
    assert rows["IT"]["contribution"] == 900.0 and rows["IT"]["names"] == 2
    assert rows["Unclassified"]["contribution"] == 100.0
    assert sum(r["contribution"] for r in found["industry"]) == pytest.approx(1000.0)


def test_years_count_closed_trades_and_open_positions_last() -> None:
    trades = [
        {"symbol": "BIG", "exit_day": "2020-06-01", "net": 600.0, "open": False},
        {"symbol": "SMALL", "exit_day": "2021-03-01", "net": 200.0, "open": False},
        {"symbol": "MID", "entry_price": 100.0, "quantity": 10, "open": True},
    ]
    equity: dict[str, list[object]] = {
        "days": ["2020-01-02", "2020-12-31", "2021-12-31"],
        "values": [1000.0, 1600.0, 2000.0],
    }
    rows = {r["year"]: r for r in attribution.by_year(trades, CONSTITUENTS, equity, 1000.0)}
    assert rows["2020"]["return"] == pytest.approx(0.6) and rows["2020"]["top_symbol"] == "BIG"
    assert rows["2021"]["trading_profit"] == pytest.approx(200.0 + 300.0), "MID open: 1300 - 1000"
    assert rows["2021"]["top_symbol"] == "MID"


def test_a_strategy_that_is_twice_the_market_has_beta_two() -> None:
    start = date(2020, 1, 1)
    days = [start + timedelta(days=i) for i in range(200)]
    index, equity, level, value = {}, [], 100.0, 1000.0
    for i, d in enumerate(days):
        move = 0.01 if i % 3 else -0.012
        level *= 1 + move
        value *= 1 + 2 * move
        index[d] = level
        equity.append(value)
    found = attribution.market({"days": [d.isoformat() for d in days], "values": equity}, index)
    assert found is not None
    assert found["beta"] == pytest.approx(2.0, abs=1e-3) and found["r_squared"] == pytest.approx(
        1.0, abs=1e-3
    )
    assert found["alpha_annual"] == pytest.approx(0.0, abs=1e-6)


def test_a_missing_classification_leaves_sectors_out_not_the_report() -> None:
    def broken() -> dict[str, tuple[str, str]]:
        raise FileNotFoundError("no digest")

    report = {
        "constituents": CONSTITUENTS,
        "equity": {"days": [], "values": []},
        "starting_cash": 1000.0,
    }
    found = attribution.analyse(report, classify=broken, index=dict)
    assert found["sectors"] is None and found["holdings"]["net_profit"] == 1000.0
