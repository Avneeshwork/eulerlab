"""The Trader's read: words from thresholds, numbers only from the inputs (ADR-100)."""

from __future__ import annotations

from typing import Any

from eulerlab.agents import trader_read
from eulerlab.agents.workers import market_brief

LEVELS = trader_read.levels()


def _ctx(
    *, above_50: float = 16.5, vix_pct: float = 71.3, smallcap_1m: float = -0.055
) -> dict[str, Any]:
    return {
        "strip": {
            "indices": [
                {
                    "name": "Nifty 50",
                    "as_of": "2026-10-30",
                    "close": 23053.1,
                    "change": {"1d": 0.005, "1m": 0.015},
                },
                {
                    "name": "Nifty Smallcap 250",
                    "as_of": "2026-10-30",
                    "close": 16764.5,
                    "change": {"1d": -0.02, "1m": smallcap_1m},
                },
            ],
            "vix": {"level": 15.3, "percentile_1y": vix_pct, "median_1y": 13.2},
        },
        "pulse": {"cards": [{"key": "trend", "word": "Downtrend"}]},
        "breadth": {
            "available": True,
            "as_of": "2026-10-30",
            "stocks": 2563,
            "latest": {"above_50": above_50, "new_highs": 26, "new_lows": 206},
        },
        "positioning": {
            "available": True,
            "as_of": "2026-10-30",
            "participants": [
                {
                    "participant": "FII",
                    "index_futures_long_share": 0.111,
                    "usual": 0.12,
                    "percentile": 38.6,
                }
            ],
        },
        "valuation": {
            "indices": [
                {
                    "name": "Nifty 50",
                    "pe": {"value": 19.3, "percentile": 1.3, "median": 22.1, "since": "2021-04-01"},
                }
            ]
        },
        "options": {
            "available": True,
            "as_of": "2026-10-28",
            "expiry": "2026-11-03",
            "pcr_oi": 1.04,
            "pcr_oi_before": 0.7,
            "max_pain": 22700.0,
            "expected_move": {"low": 22351.5, "high": 23063.7},
        },
    }


FLOWS = {
    "available": True,
    "as_of": "2026-10-30",
    "fii": {"net": -944.0, "net_5d": 3594.0},
    "dii": {"net_5d": 7163.0},
}
CLOSES = [24000.0] * 150 + [23300.0] * 30 + [22700.0] * 19 + [23053.1]


def _read(ctx: dict[str, Any], **kw: Any) -> trader_read.Read:
    args: dict[str, Any] = {
        "closes": CLOSES,
        "flows": FLOWS,
        "books": [],
        "day": "2026-10-31",
        "lv": LEVELS,
    }
    args.update(kw)
    return trader_read.build(ctx, **args)


def test_the_bottom_line_says_what_the_numbers_add_up_to() -> None:
    read = _read(_ctx())
    words = {r.signal: r.word for r in read.rows}
    assert words["Trend"] == words["Breadth"] == words["Volatility"] == "weak"
    assert words["Valuation"] == "supportive" and words["Cash flows"] == "neutral"
    assert read.bottom_line.startswith(
        "Risk-off: large caps holding while the broad market sells off"
    )
    assert "3 of 7 signals weak, 1 supportive" in read.bottom_line


def test_every_row_says_what_is_normal() -> None:
    for row in _read(_ctx()).rows:
        assert row.normal, row.signal


def test_the_words_follow_the_thresholds() -> None:
    calm = _read(_ctx(above_50=70.0, vix_pct=10.0, smallcap_1m=0.015))
    words = {r.signal: r.word for r in calm.rows}
    assert words["Breadth"] == "supportive" and words["Volatility"] == "supportive"
    assert "large caps holding" not in calm.bottom_line


def test_the_map_and_triggers_carry_levels() -> None:
    read = _read(_ctx())
    text = trader_read.render(read)
    assert "50-day average 23," in text and "Max pain 22,700" in text
    assert any(t.startswith("Trend: Nifty 50 closes above its 50-day") for t in read.triggers)
    assert any("rises past 30%" in t for t in read.triggers)
    # Old option data is named, not used for the range.
    stale = _read(_ctx(), day="2026-11-05")
    assert not any("straddle" in m for m in stale.map)
    assert any("option data is 8 days old" in g for g in stale.gaps)


def test_nothing_held_says_so_and_does_not_guess() -> None:
    read = _read({}, closes=[], flows={"available": False, "reason": "no day captured yet"})
    assert read.bottom_line == "No read: none of the signals is held."
    assert all(r.word == "not held" for r in read.rows)
    assert "Cash flows: no day captured yet" in read.gaps


def test_books_show_day_drawdown_and_invested() -> None:
    books = [
        {
            "strategy": "s1",
            "mode": "paper",
            "status": "active",
            "day_change": -0.013,
            "drawdown": 0.017,
            "invested": 0.81,
        },
        {"strategy": "s2", "mode": "paper", "status": "halted"},
    ]
    read = _read(_ctx(), books=books)
    assert read.books == [
        "s1 (paper), day -1.3%, 1.7% below its peak, 81% invested",
        "Not active: s2",
    ]


def test_the_brief_opens_with_the_read() -> None:
    read_text = trader_read.render(_read(_ctx()))
    sections = market_brief.compose(
        "pre-open", {"context": _ctx(), "world": [], "events": [], "books": [], "data": []}
    )
    text = market_brief.render("pre-open", "2026-10-31", sections, "", read_text)
    assert text.index("TRADER'S READ") < text.index("— DETAIL —") < text.index("WORLD")
    assert text.count("- India VIX: ") == 1  # the detail no longer lists it twice


def test_a_book_shows_its_loss_limit_beside_the_drawdown() -> None:
    books = [
        {"strategy": "s", "mode": "paper", "status": "active", "drawdown": 0.0367, "reduce_at": 0.1}
    ]
    assert _read(_ctx(), books=books).books == [
        "s (paper), 3.7% below its peak (reduce-only at 10%)"
    ]
