"""The dashboard's four verdict cards: Trend, Participation, Fear, Big money.

Research 121: platforms lead with a word, not a paragraph. Each card here is
a word from a fixed rule over one figure, plus what its gauge needs to draw
that figure. There is no generated text: the operator asked for numbers and
pictures on the page and explanations only behind an info button
(ADR-082), so `info` is a fixed definition of the rule with no numbers filled
in. The thresholds are ours, not a standard; the four are not added into one
score. None of it has passed the gate.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from eulerlab.market_context import BENCHMARK, SPARK_POINTS, IndexDay, thin

UP, DOWN, FLAT = "up", "down", "flat"
"""Card direction, drawn as an arrow beside the colour (research 121 [3])."""

GOOD, BAD, NEUTRAL = "good", "bad", "neutral"
"""Card tone: how a long-only holder would feel about it, nothing more."""

TREND_AVERAGE = 200
TREND_LOOKBACK = 63

PARTICIPATION_ZONES = (40.0, 60.0)
FEAR_ZONES = (30.0, 70.0)
MONEY_ZONES = (25.0, 75.0)

INFO = {
    "trend": "Nifty 50 against its 200-day average and against its close 3 months (63 sessions) "
    "ago. Uptrend: above the average and higher. Downtrend: below and lower. Sideways: "
    "anything else. The line is the past year; the dashed line is the 200-day average.",
    "participation": "The share of NSE stocks closing above their own 50-day average, on "
    "split-adjusted closes, funds and ETFs excluded. 60% or more: Broad. 40-60%: Mixed. "
    "Under 40%: Narrow. StockCharts reads above 70% as stretched and below 30% as washed out.",
    "fear": "India VIX is NSE's 30-day implied volatility of Nifty options: what traders pay "
    "for protection. The dial ranks today's close against the previous year's closes. Above "
    "the 70th percentile: Elevated. Under the 30th: Calm. Else Normal.",
    "money": "Of every 100 Nifty and Bank Nifty futures contracts foreign institutions hold, "
    "how many are bets on a rise. The tick marks their median over the past year; the line is the last 60 sessions. Ranked "
    "against that year: under the 25th percentile More bearish than usual, above the 75th "
    "More bullish than usual, else Usual. From NSE's end-of-day participant-wise open interest.",
}

NOTE = (
    "Each word comes from the rule in its info button. The thresholds are ours, not a "
    "standard, and the four are not added into one score. Context, not a signal."
)


def _card(
    key: str, title: str, word: str, direction: str, tone: str, **gauge: Any
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "word": word,
        "direction": direction,
        "tone": tone,
        "info": INFO[key],
        **gauge,
    }


def _band(value: float, zones: tuple[float, float]) -> int:
    """0 below the low zone edge, 1 between, 2 at or above the high edge."""
    low, high = zones
    return 0 if value < low else 2 if value >= high else 1


def trend_card(series: Mapping[str, Sequence[IndexDay]]) -> dict[str, Any] | None:
    """Nifty 50 against its 200-day average and its 3-month change."""
    nifty = series.get(BENCHMARK, ())
    if len(nifty) < TREND_AVERAGE + 1:
        return None
    closes = [row.close for row in nifty]
    close = closes[-1]
    average = sum(closes[-TREND_AVERAGE:]) / TREND_AVERAGE
    change = close / closes[-1 - TREND_LOOKBACK] - 1.0
    # The average for each of the last year's days, so the gauge can draw it.
    year = min(252, len(closes) - TREND_AVERAGE + 1)
    averages = [
        sum(closes[i - TREND_AVERAGE + 1 : i + 1]) / TREND_AVERAGE
        for i in range(len(closes) - year, len(closes))
    ]
    above = close > average
    if above and change > 0:
        word, direction, tone = "Uptrend", UP, GOOD
    elif not above and change < 0:
        word, direction, tone = "Downtrend", DOWN, BAD
    else:
        word, direction, tone = "Sideways", FLAT, NEUTRAL
    return _card(
        "trend",
        "Trend",
        word,
        direction,
        tone,
        value=round(change, 4),
        close=round(close, 2),
        average=round(average, 2),
        spark=thin(closes[-year:], SPARK_POINTS),
        spark_average=thin(averages, SPARK_POINTS),
    )


def participation_card(breadth: Mapping[str, Any]) -> dict[str, Any] | None:
    """How many stocks take part, from the share above their 50-day average."""
    if not breadth.get("available"):
        return None
    latest = breadth["latest"]
    share = latest.get("above_50")
    if share is None:
        return None
    word, direction, tone = (
        ("Narrow", DOWN, BAD),
        ("Mixed", FLAT, NEUTRAL),
        ("Broad", UP, GOOD),
    )[_band(float(share), PARTICIPATION_ZONES)]
    return _card(
        "participation",
        "Participation",
        word,
        direction,
        tone,
        value=share,
        zones=list(PARTICIPATION_ZONES),
        new_highs=latest.get("new_highs", 0),
        new_lows=latest.get("new_lows", 0),
    )


def fear_card(strip: Mapping[str, Any]) -> dict[str, Any] | None:
    """India VIX against its own past year."""
    vix = strip.get("vix") if strip.get("available") else None
    if not vix or vix.get("percentile_1y") is None:
        return None
    rank = float(vix["percentile_1y"])
    word, direction, tone = (
        ("Calm", DOWN, GOOD),
        ("Normal", FLAT, NEUTRAL),
        ("Elevated", UP, BAD),
    )[0 if rank < FEAR_ZONES[0] else 2 if rank > FEAR_ZONES[1] else 1]
    return _card(
        "fear",
        "Fear",
        word,
        direction,
        tone,
        value=rank,
        zones=list(FEAR_ZONES),
        level=vix["level"],
        median=vix["median_1y"],
    )


def money_card(positioning: Mapping[str, Any]) -> dict[str, Any] | None:
    """FII index-futures long share against FII's own past year."""
    if not positioning.get("available"):
        return None
    fii = next((p for p in positioning["participants"] if p["participant"] == "FII"), None)
    if not fii or fii.get("index_futures_long_share") is None or fii.get("percentile") is None:
        return None
    rank = float(fii["percentile"])
    if rank < MONEY_ZONES[0]:
        word, direction, tone = "More bearish than usual", DOWN, BAD
    elif rank > MONEY_ZONES[1]:
        word, direction, tone = "More bullish than usual", UP, GOOD
    else:
        word, direction, tone = "Usual", FLAT, NEUTRAL
    return _card(
        "money",
        "Big money",
        word,
        direction,
        tone,
        value=fii["index_futures_long_share"],
        usual=fii.get("usual"),
        percentile=rank,
        spark=[
            round(v * 100, 2) for v in positioning.get("series", {}).get("FII", []) if v is not None
        ],
    )


def pulse(
    series: Mapping[str, Sequence[IndexDay]],
    strip: Mapping[str, Any],
    breadth: Mapping[str, Any],
    positioning: Mapping[str, Any],
) -> dict[str, Any]:
    """The four cards, in a fixed order; a card whose figure is missing is left out."""
    cards = [
        card
        for card in (
            trend_card(series),
            participation_card(breadth),
            fear_card(strip),
            money_card(positioning),
        )
        if card is not None
    ]
    return {"available": bool(cards), "cards": cards, "note": NOTE}


def expected_move(options: Mapping[str, Any]) -> dict[str, float] | None:
    """The at-the-money straddle as a share of the forward: roughly the move,
    either way, the options market prices by expiry."""
    straddle, forward = options.get("straddle"), options.get("spot_forward")
    if not options.get("available") or not straddle or not forward:
        return None
    return {
        "points": round(float(straddle), 1),
        "share": round(float(straddle) / float(forward), 4),
        "low": round(float(forward) - float(straddle), 1),
        "high": round(float(forward) + float(straddle), 1),
    }
