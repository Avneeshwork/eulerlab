"""The market brief's content beyond the scorecard (ADR-105, research 134).

Pure functions over what the brief already gathered. Each answers one of the
questions a trader's morning note answers, in the order research 134 found
professional notes use:

- `matters`: the three things that matter today, ranked by how unusual they
  are against their own history. Each is a fact with its number against
  normal, then what it means, written by rule (the metric page's reading),
  never by a model.
- `coming_up`: expiry, the F&O ban list, IPOs open, economic releases, and
  what is not covered.
- `attention`: what in the paper books needs the operator first.
- `underneath`: sector rotation, new highs and lows by name, delivery spikes,
  large deals, FII/DII run.
- `review`: after the close, this morning's read against what happened.
- `telegram`: the whole thing in at most eight lines.

Nothing here predicts a price or advises a trade. Conditions ("a close above
X flips the trend read") are allowed; instructions are not.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from eulerlab.agents.trader_read import Read, ReadLevels, averages

IST = ZoneInfo("Asia/Kolkata")
LIBRARY = "docs/METRICS"


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and math.isfinite(value) else None


def _percentile(value: float, history: Sequence[float]) -> float | None:
    held = sorted(h for h in history if isinstance(h, int | float))
    if not held:
        return None
    below = sum(1 for h in held if h < value)
    equal = sum(1 for h in held if h == value)
    # Mid-rank: a value equal to every past value sits at the 50th, not the 0th.
    return 100.0 * (below + equal / 2) / len(held)


def _ordinal(p: float) -> str:
    n = round(p)
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _crore(value: float) -> str:
    return f"{'-' if value < 0 else '+'}₹{abs(value):,.0f} cr"


# --- the three things that matter ---------------------------------------------------------------

MEANING = {
    (
        "volatility",
        "high",
    ): "Option buyers are paying up for protection, so swings are expected to be larger than usual. It says nothing about direction.",
    (
        "volatility",
        "low",
    ): "The market expects calm; protection is cheap. Calm can end abruptly, but VIX says nothing about direction.",
    (
        "breadth",
        "low",
    ): "Most stocks are in their own short-term downtrends. If Nifty is steady, a few large caps are holding it up.",
    (
        "breadth",
        "high",
    ): "Most stocks are above their 50-day averages: the move is broad, not carried by a few names.",
    (
        "fii_futures",
        "low",
    ): "FIIs hold fewer index futures long than they usually do: more bearish positioning than their own norm.",
    (
        "fii_futures",
        "high",
    ): "FIIs hold more index futures long than they usually do: more bullish positioning than their own norm.",
    (
        "flows",
        "low",
    ): "FII cash selling over the week is heavy even by this year's standard, when selling was the norm.",
    (
        "flows",
        "high",
    ): "FIIs have bought more in cash over the week than in most weeks this year, when selling was the norm.",
    (
        "valuation",
        "low",
    ): "Nifty is cheap against its own recent history. That matters over months, not this session.",
    (
        "valuation",
        "high",
    ): "Nifty is expensive against its own recent history. That matters over months, not this session.",
    (
        "options",
        "up",
    ): "Far more puts are open than a week ago. Traders read that as put writers defending a level or as hedging; on index options it has no proven forecasting power.",
    (
        "options",
        "down",
    ): "Put open interest has fallen against calls since a week ago. Treat it as positioning, not a signal.",
    (
        "divergence",
        "large",
    ): "Large caps are holding while small and mid caps fall: the index hides a broad sell-off.",
    ("divergence", "small"): "Small caps are leading large caps: risk appetite is broad.",
    (
        "trend",
        "down",
    ): "Nifty is below its long-run averages and its monthly trend rule reads Downtrend. That rule changes about twice a year.",
    (
        "trend",
        "up",
    ): "Nifty is above its long-run averages and its monthly trend rule reads Uptrend.",
}
PAGE = {
    "volatility": "india-vix",
    "breadth": "breadth-above-average",
    "fii_futures": "participant-long-share",
    "flows": "fii-dii-cash-flows",
    "valuation": "valuation",
    "options": "put-call-ratio",
    "divergence": "index-returns",
    "trend": "pulse-trend",
}


def _item(key: str, side: str, score: float, title: str, fact: str) -> dict[str, Any]:
    return {
        "key": key,
        "score": round(score, 1),
        "title": title,
        "fact": fact,
        "meaning": MEANING[(key, side)],
        "page": f"{LIBRARY}/{PAGE[key]}.md",
    }


def matters(
    ctx: Mapping[str, Any],
    *,
    fii_nets: Sequence[float],
    closes: Sequence[float],
    lv: ReadLevels,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Candidates scored 0-50 by distance from their usual level; the top `limit` above 25."""
    out: list[dict[str, Any]] = []
    strip = ctx.get("strip") or {}
    vix = strip.get("vix") or {}
    pct = _num(vix.get("percentile_1y"))
    if pct is not None:
        side = "high" if pct >= 50 else "low"
        out.append(
            _item(
                "volatility",
                side,
                abs(pct - 50),
                f"Volatility {'above' if side == 'high' else 'below'} normal",
                f"India VIX {vix.get('level')}, {_ordinal(pct)} percentile of the past year (median {vix.get('median_1y')}).",
            )
        )
    breadth = ctx.get("breadth") or {}
    latest = breadth.get("latest") or {}
    share = _num(latest.get("above_50"))
    series = (breadth.get("series") or {}).get("above_50") or []
    if share is not None and series:
        bp = _percentile(share, series[:-1] or series)
        if bp is not None:
            side = "high" if bp >= 50 else "low"
            usual = sorted(series)[len(series) // 2]
            out.append(
                _item(
                    "breadth",
                    side,
                    abs(bp - 50),
                    "Breadth " + ("wide" if side == "high" else "narrow"),
                    f"{share:.0f}% of NSE stocks are above their 50-day average (past-year median {usual:.0f}%); "
                    f"{latest.get('new_highs')} new 52-week highs against {latest.get('new_lows')} new lows.",
                )
            )
    positioning = ctx.get("positioning") or {}
    fii = next(
        (p for p in positioning.get("participants") or [] if p.get("participant") == "FII"), None
    )
    if fii and _num(fii.get("percentile")) is not None:
        fp = float(fii["percentile"])
        side = "high" if fp >= 50 else "low"
        out.append(
            _item(
                "fii_futures",
                side,
                abs(fp - 50),
                "FII futures positioning "
                + ("more bullish" if side == "high" else "more bearish")
                + " than usual",
                f"{float(fii['index_futures_long_share']) * 100:.0f}% of FII index futures held long, "
                f"{_ordinal(fp)} percentile of their past year (usual {float(fii.get('usual') or 0) * 100:.0f}%).",
            )
        )
    if len(fii_nets) >= 10:
        sums = [sum(fii_nets[i - 5 : i]) for i in range(5, len(fii_nets) + 1)]
        now = sums[-1]
        cp = _percentile(now, sums[:-1])
        if cp is not None:
            side = "high" if cp >= 50 else "low"
            out.append(
                _item(
                    "flows",
                    side,
                    abs(cp - 50),
                    "FII cash " + ("buying" if now > 0 else "selling") + " over five sessions",
                    f"FII net {_crore(now)} over the last 5 sessions, {_ordinal(cp)} percentile of the 5-day sums "
                    f"in the last {len(fii_nets)} sessions (median {_crore(sorted(sums)[len(sums) // 2])}).",
                )
            )
    valuation = next(
        (
            v
            for v in (ctx.get("valuation") or {}).get("indices") or []
            if v.get("name") == "Nifty 50"
        ),
        None,
    )
    pe = (valuation or {}).get("pe") or {}
    vp = _num(pe.get("percentile"))
    if vp is not None:
        side = "high" if vp >= 50 else "low"
        # Slow: it is halved so a cheap market does not crowd out what matters this week.
        out.append(
            _item(
                "valuation",
                side,
                abs(vp - 50) / 2,
                "Nifty " + ("expensive" if side == "high" else "cheap") + " against its history",
                f"Nifty 50 P/E {pe.get('value')}, {_ordinal(vp)} percentile since {pe.get('since')} (median {pe.get('median')}).",
            )
        )
    options = ctx.get("options") or {}
    pcr, before = _num(options.get("pcr_oi")), _num(options.get("pcr_oi_before"))
    if pcr is not None and before:
        change = (pcr / before - 1) * 100
        side = "up" if change > 0 else "down"
        out.append(
            _item(
                "options",
                side,
                min(50.0, abs(change)),
                "Put open interest " + ("jumped" if side == "up" else "fell") + " against calls",
                f"Nifty put-call ratio {pcr:.2f}, from {before:.2f} five sessions earlier (expiry {options.get('expiry')}, data of {options.get('as_of')}).",
            )
        )
    large = next((r for r in strip.get("indices") or [] if r.get("name") == "Nifty 50"), None)
    small = next(
        (r for r in strip.get("indices") or [] if r.get("name") == "Nifty Smallcap 250"), None
    )
    if large and small:
        a, b = (
            _num((large.get("change") or {}).get("1m")),
            _num((small.get("change") or {}).get("1m")),
        )
        if a is not None and b is not None and abs(a - b) * 100 > lv.divergence_points:
            points = (a - b) * 100
            out.append(
                _item(
                    "divergence",
                    "large" if points > 0 else "small",
                    min(50.0, abs(points) * 5),
                    "Large caps and small caps split",
                    f"Over a month Nifty 50 moved {a * 100:+.1f}% and Smallcap 250 {b * 100:+.1f}%, a {abs(points):.1f}-point gap.",
                )
            )
    cards = (ctx.get("pulse") or {}).get("cards") or []
    faber = next((str(c.get("word")) for c in cards if c.get("key") == "trend"), None)
    avg = averages(closes)
    close = _num(large.get("close")) if large else None
    if faber and close is not None and 200 in avg:
        below = close < avg[200]
        if (faber == "Downtrend") == below:
            out.append(
                _item(
                    "trend",
                    "down" if below else "up",
                    25.0,
                    "Trend " + ("down" if below else "up"),
                    f"Nifty 50 at {close:,.0f} is {abs(close / avg[200] - 1) * 100:.1f}% {'below' if below else 'above'} "
                    f"its 200-day average ({avg[200]:,.0f}); monthly rule: {faber}.",
                )
            )
    out.sort(key=lambda m: m["score"], reverse=True)
    return [m for m in out if m["score"] >= 25][:limit]


# --- coming up ------------------------------------------------------------------------------------


def _ist(stamp: str) -> datetime | None:
    try:
        return datetime.fromisoformat(stamp).astimezone(IST)
    except ValueError:
        return None


def coming_up(
    *,
    today: date,
    ctx: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    reports: Mapping[str, Any],
    held: set[str],
    results: Sequence[Mapping[str, Any]] = (),
    results_since: str = "",
) -> dict[str, Any]:
    """What is scheduled, from what is held, and what is not covered."""
    items: list[dict[str, str]] = []
    options = ctx.get("options") or {}
    if options.get("expiry"):
        try:
            days = (date.fromisoformat(str(options["expiry"])) - today).days
            when = "today" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
            items.append(
                {
                    "when": str(options["expiry"]),
                    "what": f"Nifty options expiry ({when})",
                    "why": "Open interest and straddle prices shift into expiry; VIX rolls 3 trading days before.",
                }
            )
        except ValueError:
            pass
    for e in sorted(events, key=lambda e: str(e.get("time"))):
        at = _ist(str(e.get("time")))
        if at is None or not 0 <= (at.date() - today).days <= 1:
            continue
        items.append(
            {
                "when": at.strftime("%a %d %b %H:%M IST"),
                "what": f"{e.get('country')} {e.get('title')}",
                "why": f"{e.get('impact')} impact on the economic calendar.",
            }
        )
    ban = reports.get("ban") or {}
    if ban.get("available"):
        symbols = list(ban.get("symbols") or [])
        mine = sorted(set(symbols) & held)
        text = ", ".join(symbols) if symbols else "none"
        items.append(
            {
                "when": f"from {ban.get('as_of')}",
                "what": f"F&O ban list: {text}",
                "why": ("You hold " + ", ".join(mine) + ". " if mine else "")
                + "New derivative positions are barred until open interest falls below 80% of the limit.",
            }
        )
    ipos = (reports.get("ipos") or {}).get("open") or []
    if ipos:
        names = ", ".join(str(i.get("company") or i.get("symbol")) for i in ipos[:4])
        items.append(
            {
                "when": "open now",
                "what": f"IPOs open: {names}",
                "why": "New supply draws money, mostly from small and mid caps.",
            }
        )
    if results:
        mine = [r for r in results if r.get("symbol") in held]
        first = results[0]
        items.append(
            {
                "when": f"to {results[-1]['meeting']}",
                "what": f"Results due: {len(results)} companies"
                + (
                    f", including yours: {', '.join(sorted({str(r['symbol']) for r in mine}))}"
                    if mine
                    else ""
                ),
                "why": f"First: {first['company']} on {first['meeting']}. Board meetings to approve results, from NSE's intimations.",
            }
        )
    not_covered = []
    if not results_since:
        not_covered.append(
            "Company results dates (no board-meeting intimations captured yet: `make board-meetings`)"
        )
    elif (today - date.fromisoformat(results_since)).days < 14:
        not_covered.append(
            f"Results announced before {results_since}, when capture of NSE's board-meeting intimations began"
        )
    if not events:
        not_covered.append(
            "Economic releases (the calendar held has nothing in the next two days, or is stale)"
        )
    return {"items": items, "not_covered": not_covered}


# --- the books ----------------------------------------------------------------------------------


def attention(books: Sequence[Mapping[str, Any]], ban: set[str]) -> list[dict[str, str]]:
    """What in the paper books needs the operator, most urgent first."""
    out: list[tuple[int, dict[str, str]]] = []
    for b in books:
        if b.get("status") != "active":
            continue
        name = str(b.get("label") or b.get("strategy"))
        dd, reduce_at = _num(b.get("drawdown")), _num(b.get("reduce_at"))
        if dd is not None and reduce_at and dd >= 0.75 * reduce_at:
            out.append(
                (
                    0,
                    {
                        "book": name,
                        "why": f"{dd * 100:.1f}% below its peak; buys stop at {reduce_at * 100:.0f}% (reduce-only).",
                    },
                )
            )
        hit = sorted(set(b.get("symbols") or []) & ban)
        if hit:
            out.append((1, {"book": name, "why": f"holds {', '.join(hit)}, now in the F&O ban."}))
        due = str(b.get("next_rebalance") or "")
        if due.startswith(("in 0 ", "in 1 ")) or due == "today":
            out.append((2, {"book": name, "why": f"rebalances {due}."}))
        for warning in b.get("warnings") or []:
            out.append((3, {"book": name, "why": str(warning)[:160]}))
    out.sort(key=lambda x: x[0])
    return [x[1] for x in out]


# --- underneath ---------------------------------------------------------------------------------


def underneath(
    ctx: Mapping[str, Any], reports: Mapping[str, Any], flows: Mapping[str, Any]
) -> dict[str, Any]:
    sectors = (ctx.get("sectors") or {}).get("sectors") or []

    def rel(s: Mapping[str, Any]) -> float:
        return _num((s.get("relative") or {}).get("1m")) or 0.0

    ranked = sorted(sectors, key=rel, reverse=True)
    breadth = ctx.get("breadth") or {}
    deals = reports.get("deals") or {}
    out: dict[str, Any] = {
        "leading": [f"{s['name']} {rel(s) * 100:+.1f}% vs Nifty (1m)" for s in ranked[:3]],
        "lagging": [f"{s['name']} {rel(s) * 100:+.1f}% vs Nifty (1m)" for s in ranked[-3:][::-1]],
        "new_highs": [str(n.get("symbol")) for n in (breadth.get("new_high_names") or [])[:6]],
        "new_lows": [str(n.get("symbol")) for n in (breadth.get("new_low_names") or [])[:6]],
        "delivery": [
            f"{d.get('symbol')} {d.get('delivery_pct')}% delivered (usual {d.get('usual_pct')}%)"
            for d in ((ctx.get("delivery") or {}).get("stocks") or [])[:5]
        ],
        "deals": [
            f"{d.get('client')} net {_crore(float(d.get('net_cr') or 0))}"
            for d in (deals.get("buyers") or [])[:2] + (deals.get("sellers") or [])[:2]
        ],
        "deals_as_of": deals.get("as_of"),
    }
    if flows.get("available"):
        fii, dii = flows.get("fii") or {}, flows.get("dii") or {}

        def run(streak: Any) -> str:
            n = int(streak) if isinstance(streak, int | float) else 0
            side = "buying" if n > 0 else "selling"
            return f"{side} {abs(n)} session{'s' if abs(n) != 1 else ''} running"

        out["flows"] = (
            f"On {flows.get('as_of')}: FII {_crore(float(fii.get('net', 0)))} ({run(fii.get('streak'))}); "
            f"DII {_crore(float(dii.get('net', 0)))} ({run(dii.get('streak'))})."
        )
    return out


# --- after the close ----------------------------------------------------------------------------


def review(
    morning: Mapping[str, Any] | None, now: Read, close: float | None, close_day: str, today: str
) -> list[str]:
    """This morning's read against what happened. Empty when there was no morning brief."""
    if not morning:
        return []
    lines: list[str] = []
    if close_day != today or close is None:
        lines.append(
            f"Today's close is not held yet (latest close {close_day}); the evening run adds it."
        )
    else:
        rng = morning.get("range") or {}
        low, high = _num(rng.get("low")), _num(rng.get("high"))
        if low is not None and high is not None:
            where = "inside" if low <= close <= high else ("above" if close > high else "below")
            lines.append(
                f"Nifty closed at {close:,.1f}, {where} this morning's one-day range ({low:,.0f} to {high:,.0f})."
            )
    before = {r["signal"]: r["word"] for r in (morning.get("rows") or [])}
    for row in now.rows:
        was = before.get(row.signal)
        if was and was != row.word:
            lines.append(f"{row.signal}: {was} → {row.word}.")
    if len(lines) <= 1:
        lines.append("No scorecard word changed since this morning.")
    return lines


# --- telegram -----------------------------------------------------------------------------------


def telegram(brief: Mapping[str, Any]) -> str:
    """At most eight lines."""
    title = "PRE-OPEN" if brief.get("mode") == "pre-open" else "AFTER-CLOSE"
    lines = [f"{title} · {brief.get('day')}", str(brief.get("headline"))]
    for m in (brief.get("matters") or [])[:3]:
        lines.append(f"• {m['title']}: {m['fact']}")
    rng = brief.get("range") or {}
    if rng.get("low") is not None:
        lines.append(f"Range if VIX is right: {rng['low']:,.0f} to {rng['high']:,.0f}")
    needs = brief.get("attention") or []
    if needs:
        lines.append(f"Needs you: {needs[0]['book']} {needs[0]['why']}")
    lines = lines[:7]
    lines.append("Full brief: workbench → AI → Market brief")
    return "\n".join(lines)
