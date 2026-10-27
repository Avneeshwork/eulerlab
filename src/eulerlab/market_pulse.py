"""The dashboard's four verdict cards: Trend, Participation, Fear, Big money.

Research 121: platforms lead with a word, not a paragraph. Each card here is
a word from a fixed rule over one figure, plus what its gauge needs to draw
that figure. There is no generated text: the operator asked for numbers and
pictures on the page and explanations only behind an info button
(ADR-082), so `info` is a fixed definition of the rule with no numbers filled
in. Trend and Participation use published rules (research 122, ADR-083):
Faber's 10-month average, and the share of stocks above their 200-day average
against StockCharts' 50% line. Fear and Big money thresholds are still ours.
The four are not added into one score. None of it has passed the gate.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from eulerlab.market_context import BENCHMARK, IndexDay

UP, DOWN, FLAT = "up", "down", "flat"
"""Card direction, drawn as an arrow beside the colour (research 121 [3])."""

GOOD, BAD, NEUTRAL = "good", "bad", "neutral"
"""Card tone: how a long-only holder would feel about it, nothing more."""

TREND_MONTHS = 10
"""Faber's rule (research 122 [1]): the month-end close against the mean of the
last 10 month-end closes."""

CORRECTION, BEAR = -0.10, -0.20
"""Drawdown from the 52-week high: the conventional bands (research 122 [7])."""

BREADTH_LINE = 50.0
"""StockCharts' bias line for the share of stocks above their 200-day average,
and the High-Low Index's midpoint (research 122 [4], [5])."""

WASHED_OUT, STRETCHED = 30.0, 70.0
"""StockCharts' oversold and overbought levels for the 50-day share (research 122 [4])."""

FEAR_ZONES = (30.0, 70.0)
MONEY_ZONES = (25.0, 75.0)

INFO = {
    "trend": "Faber's rule (Journal of Wealth Management, 2007; tested on US stocks from "
    "1900): the last month-end close of Nifty 50 against the mean of the last 10 month-end "
    "closes. Above: Uptrend. Below: Downtrend. It changes only at a month's end. Brock, "
    "Lakonishok & LeBaron (1992) found returns after a fall below a moving average negative "
    "and more volatile; Gunasekarage & Power (2001) found such rules predictive in India, "
    "1990-2000. The badge is the daily fall from the 52-week high: 10-20% is a Correction, "
    "20% or more a Bear market, by convention. The line is 24 month-ends with the 10-month "
    "average dashed. On 2016-2026 Nifty it changed word twice a year. Research 122.",
    "participation": "The share of NSE stocks closing above their own 200-day average "
    "(split-adjusted, funds and ETFs excluded), confirmed by the High-Low Index (10-day "
    "mean of new highs / (highs + lows) x 100). Both at 50 or above: Broad. Both below "
    "50: Narrow. Otherwise Mixed. StockCharts: the 50% line works best with the 200-day "
    "share. The tag uses StockCharts' levels for the 50-day share: under 30 Washed out, "
    "over 70 Stretched. Zaremba et al. (2021) found breadth predicts market returns in 64 "
    "countries. Research 122.",
    "fear": "India VIX is NSE's 30-day implied volatility of Nifty options: what traders pay "
    "for protection. The dial ranks today's close against the previous year's closes. Above "
    "the 70th percentile: Elevated. Under the 30th: Calm. Else Normal.",
    "money": "Of every 100 Nifty and Bank Nifty futures contracts foreign institutions hold, "
    "how many are bets on a rise. The tick marks their median over the past year; the line is the last 60 sessions. Ranked "
    "against that year: under the 25th percentile More bearish than usual, above the 75th "
    "More bullish than usual, else Usual. From NSE's end-of-day participant-wise open interest.",
}

NOTE = (
    "Each word comes from the rule in its info button. Trend and Participation use published "
    "rules (Faber 2007; StockCharts); the Fear and Big money thresholds are ours. The four "
    "are not added into one score, and none is a guarantee. Context, not a signal."
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


def month_ends(series: Sequence[IndexDay]) -> list[IndexDay]:
    """The last trading day of each completed month, oldest first.

    The month of the latest row is left out: it has not ended, and Faber's
    rule reads only month-end closes."""
    if not series:
        return []
    out: list[IndexDay] = []
    for row in series:
        if out and (out[-1].day.year, out[-1].day.month) == (row.day.year, row.day.month):
            out[-1] = row
        else:
            out.append(row)
    latest = series[-1].day
    if (out[-1].day.year, out[-1].day.month) == (latest.year, latest.month):
        out.pop()
    return out


def drawdown_badge(series: Sequence[IndexDay]) -> tuple[float, str | None]:
    """Today's fall from the 52-week high, and its conventional name."""
    year = [row.close for row in series[-252:]]
    fall = series[-1].close / max(year) - 1.0
    # Rounded before the comparison: 90 / 100 - 1 is -0.09999999999999998.
    band = round(fall, 9)
    return fall, "Bear market" if band <= BEAR else "Correction" if band <= CORRECTION else None


def trend_card(series: Mapping[str, Sequence[IndexDay]]) -> dict[str, Any] | None:
    """Faber's 10-month rule on Nifty 50, with the drawdown band as a badge."""
    nifty = series.get(BENCHMARK, ())
    ends = month_ends(nifty)
    if len(ends) < TREND_MONTHS:
        return None
    closes = [row.close for row in ends]
    average = sum(closes[-TREND_MONTHS:]) / TREND_MONTHS
    last = closes[-1]
    up = last > average
    # The same months for both lines: the average exists only from the tenth
    # month-end, and a shorter average line would be stretched across the chart.
    span = min(24, len(closes) - TREND_MONTHS + 1)
    shown = closes[-span:]
    averages = [
        sum(closes[i - TREND_MONTHS + 1 : i + 1]) / TREND_MONTHS
        for i in range(len(closes) - span, len(closes))
    ]
    fall, badge = drawdown_badge(nifty)
    return _card(
        "trend",
        "Trend",
        "Uptrend" if up else "Downtrend",
        UP if up else DOWN,
        GOOD if up else BAD,
        value=round(last / average - 1.0, 4),
        month_end=ends[-1].day.isoformat(),
        close=round(last, 2),
        average=round(average, 2),
        spark=[round(v, 2) for v in shown],
        spark_average=[round(v, 2) for v in averages],
        drawdown=round(fall, 4),
        badge=badge,
    )


def participation_card(breadth: Mapping[str, Any]) -> dict[str, Any] | None:
    """Share of stocks above their 200-day average, confirmed by the High-Low Index."""
    if not breadth.get("available"):
        return None
    latest = breadth["latest"]
    share, high_low = latest.get("above_200"), latest.get("high_low_index")
    if share is None or high_low is None:
        return None
    above = float(share) >= BREADTH_LINE
    highs_lead = float(high_low) >= BREADTH_LINE
    if above and highs_lead:
        word, direction, tone = "Broad", UP, GOOD
    elif not above and not highs_lead:
        word, direction, tone = "Narrow", DOWN, BAD
    else:
        word, direction, tone = "Mixed", FLAT, NEUTRAL
    short = latest.get("above_50")
    tag = (
        None
        if short is None
        else "Washed out"
        if short < WASHED_OUT
        else "Stretched"
        if short > STRETCHED
        else None
    )
    return _card(
        "participation",
        "Participation",
        word,
        direction,
        tone,
        value=share,
        zones=[BREADTH_LINE, BREADTH_LINE],
        high_low=high_low,
        above_50=short,
        tag=tag,
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
