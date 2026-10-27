"""The dashboard's verdict cards: every rule, and what each gauge is sent.

ADR-082: no generated text. A card carries a word from a fixed rule, the
numbers its gauge draws, and a fixed definition for its info button.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from eulerlab import market_pulse as mp
from eulerlab.market_context import IndexDay


def _nifty(closes: list[float]) -> dict[str, list[IndexDay]]:
    start = date(2025, 1, 1)
    return {
        "Nifty 50": [
            IndexDay(start + timedelta(days=i), c, None, None, None) for i, c in enumerate(closes)
        ]
    }


def test_no_summary_is_generated() -> None:
    assert not hasattr(mp, "summary")


# --- trend: Faber's 10-month rule (research 122) ------------------------------------


def _daily(month_closes: list[float], *, current: float | None = None) -> dict[str, list[IndexDay]]:
    """Twenty trading days a month at each month's close, plus an unfinished month."""
    rows: list[IndexDay] = []
    year, month = 2023, 1
    for close in month_closes:
        for k in range(20):
            rows.append(IndexDay(date(year, month, 1 + k), close, None, None, None))
        month += 1
        if month == 13:
            year, month = year + 1, 1
    if current is not None:
        rows.append(IndexDay(date(year, month, 1), current, None, None, None))
    return {"Nifty 50": rows}


def test_month_ends_leave_out_the_unfinished_month() -> None:
    series = _daily([100.0, 101.0, 102.0], current=50.0)["Nifty 50"]
    ends = mp.month_ends(series)
    assert [row.close for row in ends] == [100.0, 101.0, 102.0]
    assert ends[-1].day == date(2023, 3, 20)


def test_above_the_ten_month_average_is_an_uptrend() -> None:
    card = mp.trend_card(_daily([100.0 + i for i in range(30)], current=50.0))
    assert card is not None
    assert (card["word"], card["direction"], card["tone"]) == ("Uptrend", "up", "good")
    # The unfinished month (50) is not read: the last month-end is 129.
    assert card["close"] == 129.0
    assert card["average"] == pytest.approx(sum(range(120, 130)) / 10)
    # 30 month-ends give 21 with a 10-month average; both lines get the same 21.
    assert len(card["spark"]) == len(card["spark_average"]) == 21
    longer = mp.trend_card(_daily([100.0 + i for i in range(40)]))
    assert longer is not None
    assert len(longer["spark"]) == len(longer["spark_average"]) == 24


def test_below_the_ten_month_average_is_a_downtrend() -> None:
    card = mp.trend_card(_daily([200.0 - i for i in range(30)]))
    assert card is not None and card["word"] == "Downtrend"
    assert card["value"] < 0


def test_exactly_on_the_average_is_not_above_it() -> None:
    card = mp.trend_card(_daily([100.0] * 12))
    assert card is not None and card["word"] == "Downtrend"


def test_fewer_than_ten_month_ends_has_no_trend_card() -> None:
    assert mp.trend_card(_daily([100.0] * 9, current=100.0)) is None


@pytest.mark.parametrize(
    ("last", "badge"),
    [(91.0, None), (90.0, "Correction"), (80.01, "Correction"), (80.0, "Bear market")],
)
def test_the_drawdown_badge_uses_the_conventional_bands(last: float, badge: str | None) -> None:
    series = _daily([100.0] * 12, current=last)
    fall, name = mp.drawdown_badge(series["Nifty 50"])
    assert fall == pytest.approx(last / 100.0 - 1.0)
    assert name == badge


def test_no_card_carries_generated_text_faber() -> None:
    up = mp.trend_card(_daily([100.0 + i for i in range(30)]))
    down = mp.trend_card(_daily([200.0 - i for i in range(30)]))
    assert up is not None and down is not None
    assert up["info"] == down["info"] == mp.INFO["trend"]


# --- participation: 200-day share and the High-Low Index (research 122) -------------


def _breadth(
    above_200: float | None, high_low: float | None = 50.0, above_50: float | None = 50.0
) -> dict[str, Any]:
    return {
        "available": True,
        "latest": {
            "above_200": above_200,
            "high_low_index": high_low,
            "above_50": above_50,
            "new_highs": 16,
            "new_lows": 101,
        },
    }


@pytest.mark.parametrize(
    ("above_200", "high_low", "word"),
    [
        (50.0, 50.0, "Broad"),
        (80.0, 70.0, "Broad"),
        (49.9, 49.9, "Narrow"),
        (33.3, 21.7, "Narrow"),
        (60.0, 40.0, "Mixed"),
        (40.0, 60.0, "Mixed"),
    ],
)
def test_participation_needs_both_lines_to_agree(
    above_200: float, high_low: float, word: str
) -> None:
    card = mp.participation_card(_breadth(above_200, high_low))
    assert card is not None and card["word"] == word
    assert card["value"] == above_200 and card["high_low"] == high_low


@pytest.mark.parametrize(
    ("above_50", "tag"),
    [(29.9, "Washed out"), (30.0, None), (70.0, None), (70.1, "Stretched"), (None, None)],
)
def test_the_fifty_day_tag_uses_stockcharts_levels(above_50: float | None, tag: str | None) -> None:
    card = mp.participation_card(_breadth(60.0, 60.0, above_50))
    assert card is not None and card["tag"] == tag


def test_no_breadth_no_participation_card() -> None:
    assert mp.participation_card({"available": False, "reason": "loading"}) is None
    assert mp.participation_card(_breadth(None)) is None
    assert mp.participation_card(_breadth(60.0, None)) is None


# --- fear ---------------------------------------------------------------------


def _strip(rank: float | None) -> dict[str, Any]:
    return {
        "available": True,
        "indices": [],
        "vix": {"level": 16.4, "percentile_1y": rank, "median_1y": 13.05, "note": ""},
    }


@pytest.mark.parametrize(
    ("rank", "word", "tone"),
    [
        (76.5, "Elevated", "bad"),
        (70.0, "Normal", "neutral"),
        (30.0, "Normal", "neutral"),
        (29.9, "Calm", "good"),
    ],
)
def test_fear_thresholds(rank: float, word: str, tone: str) -> None:
    card = mp.fear_card(_strip(rank))
    assert card is not None
    assert (card["word"], card["tone"], card["value"], card["level"]) == (word, tone, rank, 16.4)


def test_no_vix_rank_no_fear_card() -> None:
    assert mp.fear_card(_strip(None)) is None


# --- big money ------------------------------------------------------------------


def _positions(share: float | None, rank: float | None) -> dict[str, Any]:
    return {
        "available": True,
        "participants": [
            {
                "participant": "DII",
                "index_futures_long_share": 0.85,
                "percentile": 90.0,
                "usual": 0.8,
            },
            {
                "participant": "FII",
                "index_futures_long_share": share,
                "percentile": rank,
                "usual": 0.14,
            },
        ],
        "series": {"days": ["a", "b", "c"], "FII": [0.12, None, 0.1165]},
    }


@pytest.mark.parametrize(
    ("rank", "word"),
    [
        (10.0, "More bearish than usual"),
        (25.0, "Usual"),
        (75.0, "Usual"),
        (80.0, "More bullish than usual"),
    ],
)
def test_big_money_is_read_against_fii_own_year(rank: float, word: str) -> None:
    card = mp.money_card(_positions(0.1165, rank))
    assert card is not None and card["word"] == word


def test_big_money_sends_the_share_its_usual_tick_and_line() -> None:
    card = mp.money_card(_positions(0.1165, 44.2))
    assert card is not None
    assert (card["value"], card["usual"], card["percentile"]) == (0.1165, 0.14, 44.2)
    assert card["spark"] == [12.0, 11.65]  # gaps dropped, as a share of 100


def test_no_fii_rank_no_money_card() -> None:
    assert mp.money_card(_positions(0.1, None)) is None


# --- pulse and options ------------------------------------------------------------


def test_the_pulse_keeps_order_and_drops_missing_cards() -> None:
    out = mp.pulse(
        _daily([100.0 + i for i in range(30)]),
        _strip(50.0),
        {"available": False, "reason": "loading"},
        _positions(0.5, 50.0),
    )
    assert [c["key"] for c in out["cards"]] == ["trend", "fear", "money"]
    assert all(c["info"] for c in out["cards"])
    empty = mp.pulse({}, {"available": False}, {"available": False}, {"available": False})
    assert empty["available"] is False and empty["cards"] == []


def test_expected_move_gives_the_range_for_the_number_line() -> None:
    options = {"available": True, "straddle": 388.1, "spot_forward": 22770.0}
    move = mp.expected_move(options)
    assert move == {
        "points": 388.1,
        "share": pytest.approx(0.017, abs=1e-4),
        "low": 22381.9,
        "high": 23158.1,
    }
    assert mp.expected_move({"available": True, "straddle": None, "spot_forward": 1.0}) is None
    assert mp.expected_move({"available": False}) is None
