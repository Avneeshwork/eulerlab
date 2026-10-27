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


def test_no_card_carries_generated_text() -> None:
    """The info text is the same whatever the numbers: a definition, not a sentence about today."""
    up = mp.trend_card(_nifty([100.0 + i for i in range(260)]))
    down = mp.trend_card(_nifty([400.0 - i for i in range(260)]))
    assert up is not None and down is not None
    assert up["info"] == down["info"] == mp.INFO["trend"]
    assert "sentence" not in up and "rule" not in up
    assert not hasattr(mp, "summary")


# --- trend --------------------------------------------------------------------


def test_a_rising_index_above_its_average_is_an_uptrend() -> None:
    card = mp.trend_card(_nifty([100.0 + i for i in range(260)]))
    assert card is not None
    assert (card["word"], card["direction"], card["tone"]) == ("Uptrend", "up", "good")
    assert card["value"] == pytest.approx(359 / 296 - 1, abs=1e-4)
    assert card["average"] == pytest.approx(sum(range(160, 360)) / 200, abs=0.01)


def test_the_trend_gauge_gets_a_year_of_closes_and_averages_on_one_scale() -> None:
    card = mp.trend_card(_nifty([100.0 + i for i in range(500)]))
    assert card is not None
    assert len(card["spark"]) == len(card["spark_average"]) == 64
    assert card["spark"][-1] == 599.0
    assert card["spark_average"][-1] == pytest.approx(sum(range(400, 600)) / 200, abs=0.01)


def test_a_falling_index_below_its_average_is_a_downtrend() -> None:
    card = mp.trend_card(_nifty([400.0 - i for i in range(260)]))
    assert card is not None and card["word"] == "Downtrend"


def test_above_the_average_but_down_on_the_quarter_is_sideways() -> None:
    closes = [100.0] * 150 + [200.0] * 46 + [180.0] * 64
    card = mp.trend_card(_nifty(closes))
    assert card is not None and card["word"] == "Sideways"


def test_too_short_a_history_has_no_trend_card() -> None:
    assert mp.trend_card(_nifty([100.0] * 150)) is None


# --- participation ------------------------------------------------------------


def _breadth(above_50: float | None, highs: int = 0, lows: int = 0) -> dict[str, Any]:
    return {
        "available": True,
        "latest": {"above_50": above_50, "new_highs": highs, "new_lows": lows},
    }


@pytest.mark.parametrize(
    ("share", "word"), [(60.0, "Broad"), (59.9, "Mixed"), (40.0, "Mixed"), (39.9, "Narrow")]
)
def test_participation_thresholds(share: float, word: str) -> None:
    card = mp.participation_card(_breadth(share))
    assert card is not None and card["word"] == word
    assert card["zones"] == [40.0, 60.0]


def test_participation_sends_the_dial_its_value_and_the_counts() -> None:
    card = mp.participation_card(_breadth(16.2, highs=16, lows=101))
    assert card is not None
    assert (card["value"], card["new_highs"], card["new_lows"]) == (16.2, 16, 101)


def test_no_breadth_no_participation_card() -> None:
    assert mp.participation_card({"available": False, "reason": "loading"}) is None
    assert mp.participation_card(_breadth(None)) is None


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
        _nifty([100.0 + i for i in range(260)]),
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
