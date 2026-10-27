"""The dashboard's plain-English layer: four verdict cards and a short summary.

Research 121: retail platforms lead with a word, not a number (Tickertape
opens with "The market is in Fear zone"), explain each figure where it
stands, and never show a fall without something to compare it to. This turns
the figures `market_context` computes into that.

Every word comes from a fixed rule over a figure, printed beside it. There is
no combined score and no language model: each sentence traces to a number,
and the thresholds are ours, not a standard. None of it has passed the gate.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from eulerlab.market_context import BENCHMARK, IndexDay

UP, DOWN, FLAT = "up", "down", "flat"
"""Card direction, drawn as an arrow beside the colour (research 121 [3])."""

GOOD, BAD, NEUTRAL = "good", "bad", "neutral"
"""Card tone: how a long-only holder would feel about it, nothing more."""

SIZES = (
    ("Large", BENCHMARK),
    ("Mid", "Nifty Midcap 150"),
    ("Small", "Nifty Smallcap 250"),
)


def _card(
    key: str, title: str, word: str, direction: str, tone: str, sentence: str, rule: str
) -> dict[str, str]:
    return {
        "key": key,
        "title": title,
        "word": word,
        "direction": direction,
        "tone": tone,
        "sentence": sentence,
        "rule": rule,
    }


def _pct(value: float, digits: int = 1) -> str:
    return f"{abs(value) * 100:.{digits}f}%"


def one_in(share: float) -> str:
    """A share of 100 as words a reader can picture: 16.2 -> "about 1 in 6",
    55 -> "about 5 in 10", 100 -> "every"."""
    if share >= 99.5:
        return "every"
    if share <= 0.5:
        return "almost no"
    if share < 50:
        return f"about 1 in {round(100 / share)}"
    return f"about {round(share / 10)} in 10"


def trend_card(series: Mapping[str, Sequence[IndexDay]]) -> dict[str, str] | None:
    """Nifty 50 against its 200-day average and its 3-month change."""
    nifty = series.get(BENCHMARK, ())
    if len(nifty) < 200 + 1 or len(nifty) <= 63:
        return None
    close = nifty[-1].close
    average = sum(row.close for row in nifty[-200:]) / 200
    change = close / nifty[-64].close - 1.0
    above = close > average
    rule = (
        "Uptrend: Nifty 50 above its 200-day average and higher than 3 months ago. "
        "Downtrend: below and lower. Sideways: anything else."
    )
    where = "above" if above else "below"
    moved = f"{'higher' if change >= 0 else 'lower'} than 3 months ago"
    sentence = (
        f"Nifty 50 is {_pct(change)} {moved} and {where} its 200-day average ({average:,.0f})."
    )
    if above and change > 0:
        return _card("trend", "Trend", "Uptrend", UP, GOOD, sentence, rule)
    if not above and change < 0:
        return _card("trend", "Trend", "Downtrend", DOWN, BAD, sentence, rule)
    return _card("trend", "Trend", "Sideways", FLAT, NEUTRAL, sentence, rule)


def participation_card(breadth: Mapping[str, Any]) -> dict[str, str] | None:
    """How many stocks take part, from the share above their 50-day average."""
    if not breadth.get("available"):
        return None
    latest = breadth["latest"]
    share = latest.get("above_50")
    if share is None:
        return None
    highs, lows = latest.get("new_highs", 0), latest.get("new_lows", 0)
    sentence = f"{_first_upper(one_in(share))} stocks is above its 50-day average"
    if highs or lows:
        more = (
            "lows outnumber highs"
            if lows > highs
            else "highs outnumber lows"
            if highs > lows
            else "highs equal lows"
        )
        sentence += f"; new 52-week {more} ({highs} highs, {lows} lows)."
    else:
        sentence += "."
    rule = "Share of NSE stocks above their 50-day average: 60% or more Broad, 40-60% Mixed, under 40% Narrow."
    if share >= 60:
        return _card("participation", "Participation", "Broad", UP, GOOD, sentence, rule)
    if share >= 40:
        return _card("participation", "Participation", "Mixed", FLAT, NEUTRAL, sentence, rule)
    return _card("participation", "Participation", "Narrow", DOWN, BAD, sentence, rule)


def fear_card(strip: Mapping[str, Any]) -> dict[str, str] | None:
    """India VIX against its own past year."""
    vix = strip.get("vix") if strip.get("available") else None
    if not vix or vix.get("percentile_1y") is None:
        return None
    rank = float(vix["percentile_1y"])
    sentence = (
        f"India VIX at {vix['level']:.1f} is higher than on {rank:.0f}% of days in the past "
        f"year (median {vix['median_1y']:.1f}). High VIX means options cost more."
    )
    rule = "VIX against its last year: under the 30th percentile Calm, 30th-70th Normal, above the 70th Elevated."
    if rank > 70:
        return _card("fear", "Fear", "Elevated", UP, BAD, sentence, rule)
    if rank < 30:
        return _card("fear", "Fear", "Calm", DOWN, GOOD, sentence, rule)
    return _card("fear", "Fear", "Normal", FLAT, NEUTRAL, sentence, rule)


def money_card(positioning: Mapping[str, Any]) -> dict[str, str] | None:
    """FII index-futures long share against FII's own past year."""
    if not positioning.get("available"):
        return None
    fii = next((p for p in positioning["participants"] if p["participant"] == "FII"), None)
    if not fii or fii.get("index_futures_long_share") is None or fii.get("percentile") is None:
        return None
    share = float(fii["index_futures_long_share"]) * 100
    rank = float(fii["percentile"])
    if rank < 25:
        word, direction, tone, versus = (
            "More bearish than usual",
            DOWN,
            BAD,
            "fewer than usual for them",
        )
    elif rank > 75:
        word, direction, tone, versus = (
            "More bullish than usual",
            UP,
            GOOD,
            "more than usual for them",
        )
    else:
        word, direction, tone, versus = "Usual", FLAT, NEUTRAL, "normal for them"
    sentence = (
        f"Foreign institutions hold {share:.0f} of every 100 index-futures contracts as bets "
        f"on a rise: {versus} over the past year ({rank:.0f}th percentile)."
    )
    rule = (
        "FII long share of index futures against its last year: under the 25th percentile "
        "More bearish than usual, above the 75th More bullish than usual, else Usual."
    )
    return _card("money", "Big money", word, direction, tone, sentence, rule)


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
    return {
        "available": bool(cards),
        "cards": cards,
        "note": "Each word comes from the rule printed on its card. The thresholds are ours, "
        "not a standard, and the four are not added into one score. Context, not a signal.",
    }


def expected_move(options: Mapping[str, Any]) -> dict[str, float] | None:
    """The at-the-money straddle as a share of the forward: roughly the move,
    either way, the options market prices by expiry."""
    straddle, forward = options.get("straddle"), options.get("spot_forward")
    if not options.get("available") or not straddle or not forward:
        return None
    return {
        "points": round(float(straddle), 1),
        "share": round(float(straddle) / float(forward), 4),
    }


def _first_upper(text: str) -> str:
    """Capitalise the first letter only: `str.capitalize` turned "IT" into "It"."""
    return text[:1].upper() + text[1:]


def _move(name: str, change: float | None) -> str | None:
    if change is None:
        return None
    if abs(change) < 0.001:
        return f"{name} was flat"
    return f"{name} {'rose' if change > 0 else 'fell'} {_pct(change)}"


def summary(
    strip: Mapping[str, Any],
    sectors: Mapping[str, Any],
    valuation: Mapping[str, Any],
    breadth: Mapping[str, Any],
    options: Mapping[str, Any],
) -> list[dict[str, str]]:
    """ "What happened today" as a few sentences, each from one figure.

    A sentence whose figure is missing is dropped rather than guessed.
    """
    out: list[dict[str, str]] = []
    by_name = (
        {row["name"]: row for row in strip.get("indices", [])} if strip.get("available") else {}
    )
    sizes = [(label, by_name.get(name)) for label, name in SIZES]

    moves = [
        _move(f"{label.lower()}caps" if label != "Large" else "Nifty 50", row["change"]["1d"])
        for label, row in sizes
        if row is not None
    ]
    today = [move for move in moves if move]
    if today:
        lead, *rest = today
        text = _first_upper(lead)
        if rest:
            text += ", while " + " and ".join(rest)
        out.append({"topic": "today", "text": text + "."})

    month = [
        (label, row["change"]["1m"])
        for label, row in sizes
        if row is not None and row["change"]["1m"] is not None
    ]
    if month:
        parts = [
            f"{'Nifty 50' if label == 'Large' else label.lower() + 'caps'} {'up' if v >= 0 else 'down'} {_pct(v)}"
            for label, v in month
        ]
        out.append({"topic": "month", "text": "Over the past month: " + ", ".join(parts) + "."})

    if sectors.get("available") and sectors.get("sectors"):
        ranked = [s for s in sectors["sectors"] if s["relative"]["3m"] is not None]
        leaders = [s["name"].replace("Nifty ", "") for s in ranked if s["phase"] == "leading"][:2]
        laggards = [
            s["name"].replace("Nifty ", "") for s in reversed(ranked) if s["phase"] == "lagging"
        ][:2]
        if leaders or laggards:
            bits = []
            if leaders:
                bits.append(
                    f"{' and '.join(leaders)} {'are' if len(leaders) > 1 else 'is'} beating Nifty and gaining"
                )
            if laggards:
                bits.append(
                    f"{' and '.join(laggards)} {'are' if len(laggards) > 1 else 'is'} trailing most over 3 months"
                )
            out.append({"topic": "sectors", "text": _first_upper("; ".join(bits)) + "."})

    if breadth.get("available"):
        latest = breadth["latest"]
        share = latest.get("above_50")
        if share is not None:
            out.append(
                {
                    "topic": "participation",
                    "text": f"{_first_upper(one_in(share))} stocks is above its 50-day average, with "
                    f"{latest['new_highs']} new 52-week highs and {latest['new_lows']} new lows.",
                }
            )

    move = expected_move(options)
    if move is not None:
        out.append(
            {
                "topic": "options",
                "text": f"Nifty options price a move of about ±{_pct(move['share'])} "
                f"(±{move['points']:,.0f} points) by the {options.get('expiry')} expiry.",
            }
        )

    if valuation.get("available"):
        nifty = next((row for row in valuation["indices"] if row["name"] == BENCHMARK), None)
        pe = nifty.get("pe") if nifty else None
        if pe and pe.get("percentile") is not None:
            rank = float(pe["percentile"])
            since = "April 2021"
            if rank < 10:
                where = f"near its cheapest since {since}"
            elif rank > 90:
                where = f"near its most expensive since {since}"
            else:
                where = f"higher than on {rank:.0f}% of days since {since}"
            out.append(
                {
                    "topic": "valuation",
                    "text": f"Nifty 50's PE of {pe['value']:.1f} is {where} (median {pe['median']:.1f}).",
                }
            )
    return out
