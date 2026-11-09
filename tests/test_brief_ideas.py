"""The brief's stock ideas, drawn from the screener page (research 182)."""

from __future__ import annotations

from eulerlab.agents import brief_content


def test_no_screener_says_why() -> None:
    got = brief_content.ideas({})
    assert got == {"available": False, "why": "the screener has not been built (`make screener`)"}


def test_ideas_show_sectors_lists_and_movers_with_their_evidence() -> None:
    bt = {
        "sharpe": 1.0,
        "total_return": 1.0,
        "max_drawdown": -0.3,
        "window": ["2016-01-01", "2021-01-01"],
    }
    screen = {
        "as_of": "2026-11-06",
        "lists": [
            {"id": "L", "title": "Long", "picks": ["AAA", "BBB"], "backtest": bt},
            {"id": "S", "title": "Swing", "picks": [], "backtest": {}},
        ],
        "choice": {"main_long": "L", "chosen_swing": "S"},
        "stocks": {"AAA": {"sector": "Banks", "top_sector": True, "pe": 12.0}},
        "topdown": {
            "sectors": [{"sector": "Banks", "return_6m": 0.2, "top": True}],
            "industries": [{"industry": "Private Banks", "return_6m": 0.25, "strong": True}],
        },
        "movers": {
            "results_due": [{"symbol": "AAA", "meeting": "2026-11-10", "typical_move": 0.04}],
            "fresh_reactions": [],
            "breakouts": [{"symbol": "BBB", "top_sector": False}],
            "evidence": {"breakouts": "B evidence"},
        },
    }
    got = brief_content.ideas(screen)
    text = "\n".join(x for s in got["sections"] for x in s["lines"])
    assert "Banks +20%" in text and "Private Banks +25%" in text
    # 100% over five years is about 15% a year.
    assert "+15% a year, Sharpe 1.00, worst fall -30%" in text
    assert "1. AAA (Banks (top sector), P/E 12)" in text
    assert "holds nothing today (cash)" in text
    assert "AAA 11-10 (±4.0%)" in text and "BBB" in text and "B evidence" in text
    assert "not advice" in got["caveat"]
