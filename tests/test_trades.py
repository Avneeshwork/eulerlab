"""Closed trades from a fill ledger.

Hand-checked against the same five-fill ledger `web/lib/backtestStats.ts` was
checked on: a partial exit, a full exit, and a short. The stored list and the
one the report page draws must agree.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from eulerlab import trades
from eulerlab.costs.schedule import Side


@dataclass(frozen=True)
class _Fill:
    day: date
    symbol: str
    side: Side
    quantity: int
    price: float
    cost: float


def d(day: int) -> date:
    return date(2026, 1, day)


LEDGER = [
    _Fill(d(2), "AAA", Side.BUY, 100, 10.0, 10.0),
    _Fill(d(5), "AAA", Side.SELL, 40, 12.0, 4.0),
    _Fill(d(9), "AAA", Side.SELL, 60, 9.0, 6.0),
    _Fill(d(3), "BBB", Side.SELL, 10, 50.0, 1.0),
    _Fill(d(6), "BBB", Side.BUY, 10, 45.0, 1.0),
]


def test_a_partial_exit_is_its_own_trade() -> None:
    book = trades.round_trips(LEDGER)
    aaa = [t for t in book if t["symbol"] == "AAA"]
    assert [t["quantity"] for t in aaa] == [40, 60]
    # 40 * (12 - 10) - 40 * 0.10 entry cost - 4 exit cost
    assert aaa[0]["net"] == pytest.approx(72.0)
    # 60 * (9 - 10) - 60 * 0.10 - 6
    assert aaa[1]["net"] == pytest.approx(-72.0)
    assert aaa[1]["entry_day"] == "2026-01-02"


def test_a_short_profits_when_the_price_falls() -> None:
    bbb = [t for t in trades.round_trips(LEDGER) if t["symbol"] == "BBB"]
    assert len(bbb) == 1
    assert bbb[0]["side"] == "short"
    assert bbb[0]["net"] == pytest.approx(10 * 5.0 - 2.0)


def test_trades_are_listed_in_the_order_they_closed() -> None:
    book = trades.round_trips(LEDGER)
    assert [t["exit_day"] for t in book] == ["2026-01-05", "2026-01-06", "2026-01-09"]
    assert [t["id"] for t in book] == [1, 2, 3]


def test_what_is_still_open_is_listed_as_open() -> None:
    book = trades.round_trips([_Fill(d(2), "AAA", Side.BUY, 10, 10.0, 1.0)])
    assert len(book) == 1
    assert book[0]["open"] is True
    assert book[0]["net"] == pytest.approx(-1.0)
    assert book[0]["mae"] is None


def test_a_fill_larger_than_the_position_flips_it() -> None:
    book = trades.round_trips(
        [
            _Fill(d(2), "AAA", Side.BUY, 10, 10.0, 0.0),
            _Fill(d(4), "AAA", Side.SELL, 15, 11.0, 0.0),
        ]
    )
    assert [(t["side"], t["quantity"], t["open"]) for t in book] == [
        ("long", 10, False),
        ("short", 5, True),
    ]


def test_excursions_read_the_closes_while_the_trade_was_open() -> None:
    closes = {"AAA": {d(1): 5.0, d(2): 10.0, d(3): 8.0, d(4): 13.0, d(5): 12.0, d(6): 1.0}}
    book = trades.round_trips(
        [
            _Fill(d(2), "AAA", Side.BUY, 10, 10.0, 0.0),
            _Fill(d(5), "AAA", Side.SELL, 10, 12.0, 0.0),
        ],
        closes,
    )
    # Day 1 and day 6 are outside the trade and must not count.
    assert book[0]["mae"] == pytest.approx(-20.0)
    assert book[0]["mfe"] == pytest.approx(30.0)


def test_without_closes_excursions_are_unknown_not_zero() -> None:
    book = trades.round_trips(LEDGER)
    assert all(t["mae"] is None and t["mfe"] is None for t in book)


def test_summary_matches_the_report_page() -> None:
    stats = trades.summary(trades.round_trips(LEDGER))
    assert stats["closed"] == 3
    assert stats["wins"] == 2
    assert stats["losses"] == 1
    assert stats["gross_profit"] == pytest.approx(120.0)
    assert stats["gross_loss"] == pytest.approx(-72.0)
    assert stats["profit_factor"] == pytest.approx(120.0 / 72.0, abs=1e-4)
    assert stats["expectancy"] == pytest.approx(16.0)
