"""The dashboard's plain-English layer: every card rule and every sentence."""

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


@pytest.mark.parametrize(
    ("share", "words"),
    [
        (16.2, "about 1 in 6"),
        (33.3, "about 1 in 3"),
        (55.0, "about 6 in 10"),
        (100.0, "every"),
        (0.2, "almost no"),
    ],
)
def test_one_in_reads_like_speech(share: float, words: str) -> None:
    assert mp.one_in(share) == words


# --- trend --------------------------------------------------------------------


def test_a_rising_index_above_its_average_is_an_uptrend() -> None:
    card = mp.trend_card(_nifty([100.0 + i for i in range(260)]))
    assert card is not None
    assert (card["word"], card["direction"], card["tone"]) == ("Uptrend", "up", "good")
    assert "above its 200-day average" in card["sentence"]


def test_a_falling_index_below_its_average_is_a_downtrend() -> None:
    card = mp.trend_card(_nifty([400.0 - i for i in range(260)]))
    assert card is not None
    assert card["word"] == "Downtrend"
    assert "lower than 3 months ago" in card["sentence"]


def test_above_the_average_but_down_on_the_quarter_is_sideways() -> None:
    closes = [100.0] * 150 + [200.0] * 46 + [180.0] * 64
    card = mp.trend_card(_nifty(closes))
    assert card is not None
    assert card["word"] == "Sideways"


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


def test_participation_names_which_side_of_highs_and_lows_wins() -> None:
    card = mp.participation_card(_breadth(16.2, highs=16, lows=101))
    assert card is not None
    assert card["sentence"].startswith("About 1 in 6 stocks")
    assert "lows outnumber highs (16 highs, 101 lows)" in card["sentence"]


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
    assert (card["word"], card["tone"]) == (word, tone)


def test_no_vix_rank_no_fear_card() -> None:
    assert mp.fear_card(_strip(None)) is None


# --- big money ------------------------------------------------------------------


def _positions(share: float | None, rank: float | None) -> dict[str, Any]:
    return {
        "available": True,
        "participants": [
            {"participant": "DII", "index_futures_long_share": 0.85, "percentile": 90.0},
            {"participant": "FII", "index_futures_long_share": share, "percentile": rank},
        ],
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


def test_big_money_says_how_many_of_100_are_long() -> None:
    card = mp.money_card(_positions(0.1165, 44.2))
    assert card is not None
    assert "hold 12 of every 100 index-futures contracts as bets on a rise" in card["sentence"]
    assert "normal for them" in card["sentence"]


def test_no_fii_rank_no_money_card() -> None:
    assert mp.money_card(_positions(0.1, None)) is None


# --- pulse ----------------------------------------------------------------------


def test_the_pulse_keeps_order_and_drops_missing_cards() -> None:
    out = mp.pulse(
        _nifty([100.0 + i for i in range(260)]),
        _strip(50.0),
        {"available": False, "reason": "loading"},
        _positions(0.5, 50.0),
    )
    assert [c["key"] for c in out["cards"]] == ["trend", "fear", "money"]
    assert all(c["rule"] for c in out["cards"])
    empty = mp.pulse({}, {"available": False}, {"available": False}, {"available": False})
    assert empty == {**empty, "available": False, "cards": []}


# --- summary ----------------------------------------------------------------------


def _index(name: str, d1: float, m1: float) -> dict[str, Any]:
    return {"name": name, "change": {"1d": d1, "1w": None, "1m": m1, "3m": None, "1y": None}}


STRIP = {
    "available": True,
    "indices": [
        _index("Nifty 50", -0.0002, -0.0136),
        _index("Nifty Midcap 150", 0.0092, -0.0653),
        _index("Nifty Smallcap 250", 0.0219, -0.0673),
    ],
}
SECTORS = {
    "available": True,
    "sectors": [
        {"name": "Nifty IT", "relative": {"3m": 0.15}, "phase": "leading"},
        {"name": "Nifty Pharma", "relative": {"3m": 0.07}, "phase": "leading"},
        {"name": "Nifty Media", "relative": {"3m": 0.09}, "phase": "weakening"},
        {"name": "Nifty Consumer Durables", "relative": {"3m": -0.077}, "phase": "lagging"},
        {"name": "Nifty FMCG", "relative": {"3m": -0.082}, "phase": "lagging"},
    ],
}
VALUATION = {
    "available": True,
    "indices": [{"name": "Nifty 50", "pe": {"value": 19.07, "percentile": 0.4, "median": 22.13}}],
}
OPTIONS = {"available": True, "straddle": 388.1, "spot_forward": 22770.0, "expiry": "2026-11-03"}


def test_the_summary_says_what_happened_in_order() -> None:
    lines = mp.summary(STRIP, SECTORS, VALUATION, _breadth(16.2, 16, 101), OPTIONS)
    text = {line["topic"]: line["text"] for line in lines}
    assert [line["topic"] for line in lines] == [
        "today",
        "month",
        "sectors",
        "participation",
        "options",
        "valuation",
    ]
    assert text["today"] == "Nifty 50 was flat, while midcaps rose 0.9% and smallcaps rose 2.2%."
    assert (
        text["month"]
        == "Over the past month: Nifty 50 down 1.4%, midcaps down 6.5%, smallcaps down 6.7%."
    )
    # Names keep their capitals: str.capitalize turned "IT" into "It".
    assert text["sectors"].startswith("IT and Pharma are beating Nifty")
    assert "FMCG and Consumer Durables are trailing most" in text["sectors"]
    assert (
        text["options"]
        == "Nifty options price a move of about ±1.7% (±388 points) by the 2026-11-03 expiry."
    )
    assert (
        text["valuation"]
        == "Nifty 50's PE of 19.1 is near its cheapest since April 2021 (median 22.1)."
    )


def test_a_missing_figure_drops_its_sentence() -> None:
    lines = mp.summary(
        STRIP,
        {"available": False},
        {"available": False},
        {"available": False},
        {"available": False},
    )
    assert [line["topic"] for line in lines] == ["today", "month"]


@pytest.mark.parametrize(
    ("rank", "phrase"),
    [
        (95.0, "near its most expensive since April 2021"),
        (50.0, "higher than on 50% of days since April 2021"),
    ],
)
def test_valuation_sentence_bands(rank: float, phrase: str) -> None:
    valuation = {
        "available": True,
        "indices": [
            {"name": "Nifty 50", "pe": {"value": 22.0, "percentile": rank, "median": 22.0}}
        ],
    }
    lines = mp.summary(
        {"available": False},
        {"available": False},
        valuation,
        {"available": False},
        {"available": False},
    )
    assert phrase in lines[-1]["text"]


def test_expected_move_needs_a_straddle_and_a_forward() -> None:
    assert mp.expected_move(OPTIONS) == {"points": 388.1, "share": pytest.approx(0.017, abs=1e-4)}
    assert mp.expected_move({"available": True, "straddle": None, "spot_forward": 1.0}) is None
    assert mp.expected_move({"available": False}) is None
