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

from eulerlab.agents.trader_read import Read, ReadLevels, averages, expired

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
# The longer reasons (operator, 2026-11-04: "detailed reasons in brief instead of 1 liner only").
# Each says how the signal has tended to bear on the next session and what would confirm or undo it.
WHY = {
    (
        "volatility",
        "high",
    ): "High VIX means option sellers demand more to carry risk, and realised moves tend to follow: wide-range days cluster. Expect a larger high-to-low range than usual; stop distances set for a calm market will be hit by noise.",
    (
        "volatility",
        "low",
    ): "Low VIX means sessions have been narrow and option premium is thin. Ranges stay small until something breaks the calm, and when that happens the first move is often sharp because few hold protection.",
    (
        "breadth",
        "low",
    ): "When few stocks are above their averages, rallies in the index depend on a handful of heavyweights. Such rallies are fragile: if those names stall, there is little underneath to hold the index.",
    (
        "breadth",
        "high",
    ): "Broad participation means the move does not rest on a few names, so a single stock's bad news does less damage. Broad markets tend to keep their direction longer than narrow ones.",
    (
        "fii_futures",
        "low",
    ): "FIIs short index futures are the ones who must buy back if the market rises, which can make up-moves sharp (short covering). If the market falls, they add pressure by pressing the position.",
    (
        "fii_futures",
        "high",
    ): "FIIs heavily long can sell quickly if news turns, which makes down-moves sharper. While the market holds up, their positioning supports it.",
    (
        "flows",
        "low",
    ): "Heavy FII selling in cash is supply the market has to absorb, usually by DIIs. When domestic buying keeps pace the index holds; when it slips, the selling shows in the price.",
    (
        "flows",
        "high",
    ): "Steady FII buying is fresh demand. Large caps, where FIIs own most, benefit first; the effect tends to last while the buying continues, and fades fast when it stops.",
    (
        "valuation",
        "low",
    ): "A low P/E gives a margin of safety over months. It does not stop a fall tomorrow, but it makes deep, lasting falls less likely without bad earnings news.",
    (
        "valuation",
        "high",
    ): "A high P/E leaves less room for disappointment. Results that only meet expectations can see selling; the effect shows over weeks, not in one session.",
    (
        "options",
        "up",
    ): "More puts open usually means writers sold puts at levels they expect to hold, or holders bought protection. Either way the strikes with the largest put open interest act as levels traders watch.",
    (
        "options",
        "down",
    ): "Puts being closed means less defence below, or less hedging. It shows positioning changing, not a direction.",
    (
        "divergence",
        "large",
    ): "When large caps rise while small caps fall, money is hiding in the safest names. That usually means caution, not confidence: the index level overstates how healthy the market is.",
    (
        "divergence",
        "small",
    ): "Small caps leading is what risk appetite looks like. It also means the market is more exposed if sentiment turns, because small caps fall faster.",
    (
        "trend",
        "down",
    ): "In a downtrend rallies tend to meet selling near the falling averages. Trend rules are slow, so one up day does not change this; a few closes above the averages would.",
    (
        "trend",
        "up",
    ): "In an uptrend dips tend to be bought near the rising averages. One bad day does not change this; closes below the averages would.",
}
WATCH = {
    (
        "volatility",
        "high",
    ): "India VIX at the open: a fall below its 70th percentile would say the stress is easing.",
    (
        "volatility",
        "low",
    ): "A jump in VIX of more than 10% in a session: that is the calm breaking.",
    (
        "breadth",
        "low",
    ): "The advance-decline count: if most stocks rise with the index, the narrow market is widening.",
    ("breadth", "high"): "Whether breadth holds on a down day: a broad market falls less broadly.",
    (
        "fii_futures",
        "low",
    ): "FII index futures long share in tonight's participant data: a rise means covering.",
    ("fii_futures", "high"): "A drop in FII long share tonight: that is the long being unwound.",
    ("flows", "low"): "Tonight's FII/DII cash figures: whether DIIs keep absorbing the selling.",
    (
        "flows",
        "high",
    ): "Whether FIIs buy again tonight: one day of selling after a run of buying is common; three is a turn.",
    (
        "valuation",
        "low",
    ): "Results this week: they decide whether cheap stays cheap or becomes good value.",
    (
        "valuation",
        "high",
    ): "Results this week: misses get punished more when the market is expensive.",
    (
        "options",
        "up",
    ): "The put strike with the largest open interest: a close below it would force writers to hedge.",
    ("options", "down"): "Whether calls are being added instead: that would cap upside.",
    (
        "divergence",
        "large",
    ): "Smallcap 250 against Nifty: if small caps stop falling, the split is closing.",
    ("divergence", "small"): "Whether large caps join: a broad rally needs both.",
    (
        "trend",
        "down",
    ): "The 50-day and 200-day averages in the levels below: closes above them turn the trend.",
    (
        "trend",
        "up",
    ): "The 50-day average in the levels below: a close under it is the first warning.",
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
        "why": WHY.get((key, side), ""),
        "watch": WATCH.get((key, side), ""),
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
    nifty_day = next(
        (str(r.get("as_of")) for r in strip.get("indices") or [] if r.get("name") == "Nifty 50"), ""
    )
    if pcr is not None and before and not expired(options, nifty_day):
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
    horizon: int = 1,
) -> dict[str, Any]:
    """What is scheduled, from what is held, and what is not covered."""
    items: list[dict[str, str]] = []
    options = ctx.get("options") or {}
    if options.get("expiry"):
        try:
            days = (date.fromisoformat(str(options["expiry"])) - today).days
            when = "today" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
            if days >= 0:
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
        if at is None or not 0 <= (at.date() - today).days <= horizon:
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
    if not any(i["why"].endswith("economic calendar.") for i in items):
        not_covered.append(
            f"Economic releases (the calendar held lists nothing in the next {horizon + 1} days, or is stale)"
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


# --- the next-session forecast (ADR-133) ------------------------------------------------------


def _p(value: Any) -> str:
    return f"{float(value) * 100:.0f}%"


def forecast_review(nxt: Mapping[str, Any], day: str) -> list[str]:
    """The last scored forecast against what happened. With `day`, only that session's."""
    last = nxt.get("last_scored")
    if not nxt.get("available") or not last:
        return (
            ["Forecasts are logged from today; each is scored once its session closes."]
            if nxt.get("available")
            else []
        )
    if day and last["target"] != day:
        return [
            f"Today's forecast is scored once today's close is held (latest scored: {last['target']})."
        ]
    f = last["forecast"]
    where = (
        "inside"
        if last["in_band"]
        else "above"
        if last["close"] > float(f["band_high"])
        else "below"
    )
    called = "higher" if float(f["p_up"]) > 0.5 else "lower"
    right = (float(f["p_up"]) > 0.5) == bool(last["up"])
    lines = [
        f"Forecast for {f['target']} (made {str(f['made_at'])[:16]} UTC): close band "
        f"{float(f['band_low']):,.0f} to {float(f['band_high']):,.0f}, range {float(f['range_pct']):.2f}%, "
        f"higher close {_p(f['p_up'])} (base rate {_p(f['base_up'])}), higher open {_p(f['p_gap_up'])}.",
        f"What happened: opened {last['gap_pct']:+.2f}%, closed at {last['close']:,.1f} ({last['change_pct']:+.2f}%), "
        f"range {last['range_pct']:.2f}%. The close was {where} the band; the odds leaned {called}, "
        f"which was {'right' if right else 'wrong'}.",
    ]
    if last.get("range_error") is not None:
        lines.append(
            "The range forecast was "
            + ("too narrow" if last["range_pct"] > float(f["range_pct"]) else "too wide")
            + f" by {abs(last['range_pct'] / float(f['range_pct']) - 1) * 100:.0f}%"
            + (
                f"; VIX's range was off by {abs(last['range_pct'] / float(f['vix_range_pct']) - 1) * 100:.0f}%."
                if f.get("vix_range_pct")
                else "."
            )
        )
    lines.append(
        f"Score: Brier {last['brier_up']:.3f} for the close odds against the base rate's "
        f"{last['brier_up_base']:.3f}; lower is better, and one day proves little. The model refits on this session tonight."
    )
    return lines


def _card(c: Mapping[str, Any], name: str) -> str:
    out = f"{name}, {c['n']} sessions ({c['since']} to {c['to']}): close inside the 80% band {_p(c['in_band'])} of days"
    if c.get("range_error") is not None and c.get("range_error_vix") is not None:
        out += (
            f"; range error {c['range_error']:.2f} against VIX's {c['range_error_vix']:.2f}"
            f" ({'better' if c['range_error'] < c['range_error_vix'] else 'worse'} than VIX)"
        )
    out += (
        f"; higher-close odds Brier {c['brier_up']:.4f} against the base rate's {c['brier_up_base']:.4f}"
        f", direction right {_p(c['hit_up'])} of days"
        f"; higher-open odds Brier {c['brier_gap']:.4f} against {c['brier_gap_base']:.4f}."
    )
    return out


def forecast_sections(nxt: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The forecast as titled sections of lines, with its reasons and its record."""
    if not nxt:
        return []
    if not nxt.get("available"):
        return [
            {
                "title": "What can happen next session",
                "lines": [f"Not available: {nxt.get('reason')}"],
            }
        ]
    f = nxt["forecast"]
    last = float(f["last_close"])
    points = last * float(f["range_pct"]) / 100
    lines: list[str] = []
    if nxt.get("late"):
        lines.append(
            f"Made after {f['target']} opened, because the last close held is {f['last_day']}: "
            "shown, but not logged or scored."
        )
    pct = f.get("range_percentile")
    vix = f.get("vix_range_pct")
    lines += [
        f"How big: the range model expects a {float(f['range_pct']):.2f}% high-to-low range, about "
        f"{points:,.0f} points"
        + (
            f", the {_ordinal(float(pct))} percentile of the past year's sessions"
            if pct is not None
            else ""
        )
        + (
            f". VIX alone implies {float(vix):.2f}%, but VIX has overstated ranges: option buyers "
            "pay for protection, so implied moves run above realised ones."
            if vix and float(vix) > float(f["range_pct"])
            else f". VIX alone implies {float(vix):.2f}%."
            if vix
            else "."
        ),
        f"Where it closes: four days in five the close should land between {float(f['band_low']):,.0f} "
        f"and {float(f['band_high']):,.0f} (last close {last:,.1f}).",
        f"The open: {_p(nxt['show_gap_up'])} chance of opening above {last:,.0f} "
        f"(base rate {_p(f['base_gap_up'])}); expected open about {float(f['expected_open']):,.0f} "
        f"({float(f['gap_pct']):+.2f}%). US session input: {f['us_source']}. {nxt['gap_why']}",
        *[f"Reason: {r}." for r in nxt.get("gap_reasons") or []],
        f"The close: {_p(nxt['show_up'])} chance of closing above {last:,.0f} "
        f"(base rate {_p(f['base_up'])}). {nxt['up_why']}",
        *[f"Reason: {r}." for r in nxt.get("up_reasons") or []],
    ]
    live, walked = nxt.get("live") or {}, nxt.get("check") or {}
    record = [
        _card(live, "Live")
        if live.get("n")
        else "Live: no session scored yet; the first is scored after its close.",
    ]
    if walked.get("n"):
        record.append(
            _card(walked, "Walk-forward check, each day forecast from a model fitted before it")
        )
    record.append(
        "Brier score: the squared error of a probability; 0.25 is a coin flip, lower is better. "
        "The odds shown fall back to the base rate whenever the model trails it."
    )
    return [
        {"title": f"What can happen next session ({f['target']}): {nxt['label']}", "lines": lines},
        {"title": "Scenarios for the next session", "lines": list(nxt.get("scenarios") or [])},
        {"title": "How the forecast has done", "lines": record},
    ]


def forecast_lines(nxt: Mapping[str, Any]) -> list[str]:
    """The forecast sections as brief text."""
    out: list[str] = []
    for s in forecast_sections(nxt):
        out += ["", s["title"].upper(), *[f"- {x}" for x in s["lines"]]]
    return out


# --- weekends and holidays ---------------------------------------------------------------------


def week(ctx: Mapping[str, Any], fii_nets: Sequence[float]) -> list[str]:
    """The last five sessions in a few lines, for a note written when the market is closed."""
    lines: list[str] = []
    for row in (ctx.get("strip") or {}).get("indices") or []:
        name = str(row.get("name"))
        if name in ("Nifty 50", "Nifty Bank", "Nifty Smallcap 250", "India VIX"):
            w = _num((row.get("change") or {}).get("1w"))
            if w is not None:
                lines.append(
                    f"{name}: {w * 100:+.1f}% over the week, to {row.get('close'):,} ({row.get('as_of')})."
                )
    series = (ctx.get("breadth") or {}).get("series") or {}
    above = series.get("above_50") or []
    if len(above) >= 6:
        lines.append(
            f"Stocks above their 50-day average: {above[-6]:.0f}% a week ago, {above[-1]:.0f}% now."
        )
    if len(fii_nets) >= 5:
        lines.append(f"FII cash over the last 5 sessions: {_crore(sum(fii_nets[-5:]))}.")
    return lines


# --- telegram -----------------------------------------------------------------------------------


def telegram(brief: Mapping[str, Any]) -> str:
    """At most eight lines."""
    title = {"pre-open": "PRE-OPEN", "after-close": "AFTER-CLOSE"}.get(
        str(brief.get("mode")), "MARKETS CLOSED"
    )
    lines = [f"{title} · {brief.get('day')}", str(brief.get("headline"))]
    for m in (brief.get("matters") or [])[:3]:
        lines.append(f"• {m['title']}: {m['fact']}")
    nxt = brief.get("next") or {}
    rng = brief.get("range") or {}
    if nxt.get("available"):
        f = nxt["forecast"]
        lines.append(
            f"Next session: range ~{float(f['range_pct']):.1f}%, close likely {float(f['band_low']):,.0f}"
            f"-{float(f['band_high']):,.0f}; higher close {_p(nxt['show_up'])} (base {_p(f['base_up'])})"
        )
    elif rng.get("low") is not None:
        lines.append(f"Range if VIX is right: {rng['low']:,.0f} to {rng['high']:,.0f}")
    needs = brief.get("attention") or []
    if needs:
        lines.append(f"Needs you: {needs[0]['book']} {needs[0]['why']}")
    lines = lines[:7]
    lines.append("Full brief: workbench → AI → Market brief")
    return "\n".join(lines)
