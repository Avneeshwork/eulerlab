"""The market brief agent: what happened, what is on today, and what it means for the books.

**Read like a morning note** (ADR-105, research 134). The brief is built as
data (`build_brief`) in the order a trader reads: the headline, the three
things that matter today with what each means (`agents/brief_content.py`),
levels and what would change the read, what is coming up, what in the books
needs the operator, then what is moving underneath, the scorecard and the
detail. After the close (15:30 IST) it is a note that also checks this
morning's read against what happened. The workbench draws it from the data;
Telegram gets eight lines.

**Answer first** (ADR-100). The scorecard is the Trader's read
(`agents/trader_read.py`): a bottom line, a scorecard with what is normal for
each signal, today's levels, what would change the read, and the books. The
detail sections follow. Telegram gets the Trader's read only, and only when
all seven signals are held; otherwise one line says which are missing (ADR-101).

Two briefs a trading day: **pre-open** (before 12:00 IST) and **after the
close**. Every number in a brief comes from data the platform holds or
fetched for it; the model, when it has budget, adds a few sentences of
commentary under a label that says so. The commentary never feeds a strategy:
nothing in `deploy/` or `backtest/` reads this agent's output.

**Refreshes itself.** Each brief records a fingerprint of the numbers it was
built from. A run whose numbers match the last brief's is skipped, so the
scheduled jobs can call it after every data refresh and it only rewrites, and
only messages Telegram, when something changed.

**Memory.** The full market context needs the 1.85 GB price panel. When the
workbench is running, the brief asks it (`/api/market-context`) instead of
loading a second copy. When it is not, the brief uses the index history only
(levels, VIX, valuation, sectors) and says what it left out.
"""

from __future__ import annotations

import hashlib
import json
import math
import urllib.error
import urllib.request
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from eulerlab.agents import brief_content, grounding, history_says, trader_read
from eulerlab.agents.runtime import Context, Item, WorkerResult, latest_output, untrusted

IST = ZoneInfo("Asia/Kolkata")
API = "http://127.0.0.1:8000"


def _local_api(path: str, timeout: float = 20.0) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(f"{API}{path}", timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
            return body if isinstance(body, dict) else None
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


def _context(notes: list[str]) -> dict[str, Any]:
    served = _local_api("/api/market-context")
    if served is not None and served.get("ok"):
        return served
    from eulerlab import market_context

    notes.append("workbench not running: breadth, positioning and options left out")
    series = market_context.indices()
    return {
        "ok": True,
        "strip": market_context.index_strip(series),
        "valuation": market_context.valuation(series),
        "sectors": market_context.sector_strength(series),
        "breadth": {"available": False, "reason": "needs the workbench running"},
        "positioning": {"available": False, "reason": "needs the workbench running"},
        "options": {"available": False, "reason": "needs the workbench running"},
    }


def _world(notes: list[str], fetch: bool) -> list[dict[str, Any]]:
    if not fetch:
        return []
    from eulerlab import macro

    got = macro.fetch(timeout=15)
    if got.error:
        notes.append(f"world prices not fetched: {got.error}")
        return []
    return [
        {
            "name": r.name,
            "last": round(r.last, 3),
            "change_pct": round(r.change_pct, 2),
            "unit": r.unit,
        }
        for r in got.readings
    ]


def _events(now_ist_day: str) -> list[dict[str, Any]]:
    try:
        from eulerlab.ingest import forexfactory

        events = forexfactory.latest_schedule(forexfactory.read_all(stale_ok=True))
    except Exception:
        return []
    out = []
    for e in events:
        if e.event_time[:10] >= now_ist_day and e.impact.lower() in ("high", "medium"):
            out.append(
                {"title": e.title, "country": e.country, "time": e.event_time, "impact": e.impact}
            )
    return sorted(out, key=lambda e: e["time"])[:12]


def _reports() -> dict[str, Any]:
    """NSE's evening reports (ban list, deals, IPOs), as the Deals & filings tab reads them."""
    from eulerlab import market_reports

    try:
        loaded = json.loads(market_reports.OUT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _results(day: str) -> dict[str, Any]:
    """Results meetings in the next week, from the captured board-meeting intimations."""
    from eulerlab.ingest import board_meetings

    rows = board_meetings.held()
    first = min((str(r.get("knowledge_time", ""))[:10] for r in rows), default="")
    return {"upcoming": board_meetings.upcoming(date.fromisoformat(day), rows=rows), "since": first}


def _history(books: list[dict[str, Any]]) -> dict[str, Any]:
    """What history says and each book's backtest in this kind of market (ADR-109)."""
    from eulerlab import market_context, workspace

    try:
        series = market_context.indices()
    except (OSError, ValueError):
        return {"rates": {"available": False, "reason": "index history not readable"}, "books": []}
    s = history_says.setup()

    def closes(name: str) -> dict[date, float]:
        return {r.day: r.close for r in series.get(name, [])}

    days = history_says.align(
        closes("Nifty 50"),
        closes("India VIX"),
        closes("Nifty Smallcap 250"),
        date.fromisoformat(s.start),
    )
    rates = history_says.base_rates(days, s)
    folder = workspace.resolve(None).root / "reports"
    backtests = {
        str(b.get("strategy")): history_says.longest_backtest(folder / str(b.get("strategy")))
        for b in books
        if b.get("status") == "active"
    }
    lines = history_says.books_in_this_market(
        books,
        rates.get("match_days") or [],
        [d.day.isoformat() for d in days],
        backtests,
        s.min_matches,
    )
    return {
        "rates": {k: v for k, v in rates.items() if k != "match_days"},
        "lines": history_says.describe(rates, s.min_matches),
        "books": lines,
    }


def _books() -> list[dict[str, Any]]:
    from eulerlab.deploy import deployments

    out = []
    for d in deployments.all_deployments():
        state = deployments.read_state(d) or {}
        curve = state.get("curve") or []
        flowed = {str(f.get("applied_day")) for f in state.get("flows") or []}
        limit = state.get("loss_limit") or {}
        equity = state.get("equity")
        cash = state.get("cash")
        out.append(
            {
                "id": d.id,
                "strategy": d.strategy_id,
                "label": f"{d.strategy_id} (₹{d.capital:,.0f})",
                "mode": d.mode,
                "status": d.status,
                "traded_through": state.get("traded_through"),
                "equity": state.get("equity"),
                "warnings": list(state.get("warnings") or [])[:2],
                # A day with money added or withdrawn has no clean day change.
                "day_change": float(curve[-1][1]) / float(curve[-2][1]) - 1
                if len(curve) > 1 and float(curve[-2][1]) and str(curve[-1][0]) not in flowed
                else None,
                # The loss limit's time-weighted drawdown, so a withdrawal is not a loss.
                "drawdown": limit.get("drawdown"),
                "reduce_at": limit.get("reduce_at"),
                "invested": 1 - float(cash) / float(equity)
                if isinstance(equity, int | float) and isinstance(cash, int | float) and equity
                else None,
                "symbols": sorted(
                    {str(h.get("symbol")) for h in state.get("book") or [] if isinstance(h, dict)}
                ),
                "next_rebalance": state.get("next_rebalance"),
            }
        )
    return out


def _next(now: datetime, closed: frozenset[date], world: list[dict[str, Any]]) -> dict[str, Any]:
    """The next-session forecast, logged and scored (ADR-133). Never fails the brief."""
    from eulerlab.forecast import next_session

    spx = next((w.get("change_pct") for w in world if w.get("name") == "S&P 500"), None)
    try:
        return next_session.build(
            now=now, closed=closed, us_live=float(spx) if isinstance(spx, int | float) else None
        )
    except (OSError, ValueError, ArithmeticError, IndexError, np.linalg.LinAlgError) as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {str(exc)[:120]}"}


def _flows() -> dict[str, Any]:
    try:
        from eulerlab.ingest import fii_dii_cash

        return fii_dii_cash.summary(fii_dii_cash.rows())
    except (OSError, ValueError, KeyError) as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {str(exc)[:80]}"}


def _closes() -> list[float]:
    """Nifty 50's last 200 closes, for its averages. The index history, not the panel."""
    try:
        from eulerlab import market_context

        return [row.close for row in market_context.indices().get("Nifty 50", [])[-200:]]
    except (OSError, ValueError):
        return []


def _pct(value: Any) -> str:
    return f"{value * 100:+.1f}%" if isinstance(value, int | float) else "n/a"


def _share(value: Any) -> str:
    return f"{value * 100:.0f}%" if isinstance(value, int | float) else "n/a"


def _points(value: Any) -> str:
    return f"{value * 100:+.1f} points" if isinstance(value, int | float) else "n/a"


def compose(mode: str, inputs: dict[str, Any]) -> list[tuple[str, list[str]]]:
    """The brief's sections as plain lines, from the inputs only."""
    ctx = inputs["context"]
    sections: list[tuple[str, list[str]]] = []
    world = inputs.get("world") or []
    if world:
        wanted = ("WTI CRUDE", "BRENT", "GOLD", "DXY", "US 10Y", "USDINR", "INDIA 10Y")
        lines = [
            f"{w['name']}: {w['last']} {w['unit']} ({w['change_pct']:+.2f}%)"
            for w in world
            if any(k in str(w["name"]).upper() for k in wanted)
        ]
        sections.append(("World", lines or ["held, but none of the usual markets resolved"]))
    else:
        sections.append(("World", ["not held this run (TradingView scanner not reached)"]))

    strip = ctx.get("strip") or {}
    india = [
        f"{row['name']}: {row['close']:,} ({_pct(row['change'].get('1d'))} day, {_pct(row['change'].get('1m'))} month) as of {row['as_of']}"
        for row in (strip.get("indices") or [])[:7]
        if row.get("name") != "India VIX"
    ]
    vix = strip.get("vix")
    if vix:
        india.append(
            f"India VIX: {vix['level']} (percentile {vix.get('percentile_1y')} of the past year, "
            f"median {vix.get('median_1y')})"
        )
    for card in (
        (ctx.get("pulse") or {}).get("cards", []) if isinstance(ctx.get("pulse"), dict) else []
    ):
        india.append(f"{card.get('title')}: {card.get('word')}")
    sections.append(("India", india or ["no index history held"]))

    sectors = (ctx.get("sectors") or {}).get("sectors") or []
    if sectors:
        lead = [s["name"] for s in sectors if s.get("phase") == "leading"][:4]
        lag = [s["name"] for s in sectors if s.get("phase") == "lagging"][:4]
        sections.append(
            (
                "Sectors against Nifty",
                [f"Leading: {', '.join(lead) or 'none'}", f"Lagging: {', '.join(lag) or 'none'}"],
            )
        )

    breadth = ctx.get("breadth") or {}
    if breadth.get("available"):
        latest = breadth.get("latest") or {}
        sections.append(
            (
                "Breadth",
                [
                    f"Stocks above their 20/50/200-day average: {latest.get('above_20')}% / "
                    f"{latest.get('above_50')}% / {latest.get('above_200')}%",
                    f"52-week new highs {latest.get('new_highs')}, new lows {latest.get('new_lows')}",
                ]
                if latest
                else ["held"],
            )
        )
    positioning = ctx.get("positioning") or {}
    if positioning.get("available"):
        lines = [
            f"{p['participant']}: {_share(p.get('index_futures_long_share'))} of index futures held long "
            f"(usual {_share(p.get('usual'))}; {_points(p.get('change_1d'))} on the day)"
            for p in positioning.get("participants", [])[:4]
        ]
        sections.append((f"F&O positioning ({positioning.get('as_of')})", lines))

    events = inputs.get("events") or []
    sections.append(
        (
            "On today",
            [f"{e['time'][11:16]} {e['country']} {e['title']} ({e['impact']})" for e in events]
            or ["no medium or high impact release in the calendar held"],
        )
    )
    data = inputs.get("data") or []
    low = [f"{g['name']} grade {g['grade']}" for g in data if g.get("grade") in ("C", "D")]
    behind = [g["name"] for g in data if g.get("freshness") in ("stale", "missing", "behind")]
    sections.append(
        (
            "Data",
            [
                f"{len(low)} of {len(data)} sources at grade C or D (Data Status lists them)"
                if low
                else "every source at grade A or B",
                f"Behind: {', '.join(behind) or 'none'}",
            ],
        )
    )
    return sections


def render(
    mode: str, day: str, sections: list[tuple[str, list[str]]], commentary: str, read: str = ""
) -> str:
    title = "PRE-OPEN BRIEF" if mode == "pre-open" else "AFTER-CLOSE BRIEF"
    lines = [f"{title} · {day}"]
    if read:
        lines += ["", read]
    if commentary:
        lines += ["", "ANALYST NOTE (model, not data)", commentary.strip()]
    if read:
        lines += ["", "— DETAIL —"]
    for heading, body in sections:
        lines += ["", heading.upper(), *[f"- {b}" for b in body]]
    return "\n".join(lines)


QUESTIONS = (
    "You write an analyst note under one trader's market brief for India. Use only the numbers "
    "in the brief. Answer exactly these four, each on its own line starting with its label, "
    "two to four sentences each, explaining the reasons, not just restating numbers:\n"
    "What happened: what drove the last session, from the brief's account of it, flows and "
    "breadth, and what that says about who is in control.\n"
    "What can happen next: what the next-session forecast says and the reasons it gives, "
    "including how much to trust it from its score.\n"
    "What to watch: the level or number in the brief that decides the session, and why.\n"
    "What would prove it wrong: which trigger in the brief, if hit, flips the read.\n"
    "No advice to buy or sell, no new numbers, no markdown."
)


def fingerprint(inputs: dict[str, Any]) -> str:
    def strip(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: strip(v)
                for k, v in sorted(value.items())
                if k not in ("spark", "at", "taken_at", "note", "info")
            }
        if isinstance(value, list):
            return [strip(v) for v in value]
        return value

    material = json.dumps(strip(inputs), sort_keys=True, default=str)
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def run(ctx: Context) -> WorkerResult:
    now_ist = ctx.now.astimezone(IST)
    closed = (now_ist.hour, now_ist.minute) >= (15, 30)
    mode = str(ctx.args.get("mode") or ("after-close" if closed else "pre-open"))
    day = now_ist.date().isoformat()
    notes: list[str] = []
    from eulerlab.ingest import holidays
    from eulerlab.quality import contract

    force = str(ctx.args.get("force", "")).lower() in ("1", "true", "yes")
    closed_days = holidays.load_holidays(holidays.REFERENCE)
    closed_why = ""
    if not holidays.is_session(now_ist.date(), closed_days):
        # No session: a closed-market note instead of a brief that would repeat
        # the last session's numbers under today's date (ADR-105).
        closed_why = "weekend" if now_ist.weekday() >= 5 else "NSE holiday"
        if not ctx.args.get("mode"):
            mode = "weekend"
    if not closed_days:
        notes.append("NSE holiday list not held (`make holidays`): only weekends are skipped")

    ctx.step(f"Gathering market context, world markets, events and books for the {mode} brief")
    inputs: dict[str, Any] = {
        "mode": mode,
        "day": day,
        "context": _context(notes),
        "world": _world(notes, fetch=bool(ctx.options.get("world", True))),
        "events": _events(day),
        "books": _books(),
        "reports": _reports(),
        "results": _results(day),
        "flows": _flows(),
        "closes": _closes(),
        "data": [
            {"name": g.get("name"), "grade": g.get("grade"), "freshness": g.get("freshness")}
            for g in contract.saved()
        ],
    }
    stamp = fingerprint(inputs)
    last = latest_output(ctx.name, ctx.root)
    # One Telegram message per break: Sunday shows the note again but does not resend it.
    repeat = False
    if mode == "weekend" and last is not None:
        before = last.data.get("brief") or {}
        as_of = next(
            (r.get("as_of") for r in (inputs["context"].get("strip") or {}).get("indices") or []),
            None,
        )
        repeat = before.get("mode") == "weekend" and before.get("as_of") == as_of
    if (
        not force
        and mode != "weekend"
        and last is not None
        and last.data.get("fingerprint") == stamp
        and last.data.get("mode") == mode
        and ctx.now - timedelta(hours=20) < _parse(last.started, ctx)
    ):
        return WorkerResult(
            "nothing changed since the last brief",
            status="skipped",
            data={"fingerprint": stamp, "mode": mode},
        )

    ctx.step("Finding past days like today and what followed (history, not a forecast)")
    history = _history(inputs["books"])
    ctx.step("Forecasting the next session and scoring the forecasts made so far")
    upcoming = _next(ctx.now, closed_days, inputs["world"])
    ctx.step("Writing the Trader's read and the brief from the numbers gathered")
    levels = trader_read.levels()
    read = trader_read.build(
        inputs["context"],
        closes=inputs["closes"],
        flows=inputs["flows"],
        books=inputs["books"],
        day=day,
        lv=levels,
    )
    read_text = trader_read.render(read)
    brief = build_brief(
        mode,
        day,
        inputs,
        read,
        levels,
        _morning(ctx, day) if mode == "after-close" else None,
        closed_why,
    )
    brief["history"] = history.get("lines") or []
    brief["history_rates"] = history.get("rates") or {}
    brief["books_history"] = history.get("books") or []
    brief["next"] = upcoming
    if mode == "after-close":
        brief["review"] = brief_content.forecast_review(upcoming, day) + brief["review"]
    elif mode == "pre-open":
        brief["review"] = brief_content.forecast_review(upcoming, "")
        brief["review_title"] = "The last forecast against what happened"
    sections = compose(mode, inputs)
    detail = render(mode, day, sections, "")
    commentary = ""
    if ctx.can_ask():
        plain = brief_text(brief, read_text, "")
        try:
            commentary = ctx.ask(QUESTIONS, untrusted("brief", plain))
        except Exception as exc:
            notes.append(f"no commentary: {type(exc).__name__}: {str(exc)[:120]}")
        if commentary:
            found = grounding.check(commentary, [plain, detail])
            if not found.ok:
                notes.append(
                    "commentary dropped: it used figures not in the brief "
                    f"({', '.join(found.unsupported)}) (ADR-088)"
                )
                commentary = ""
    brief["note"] = commentary.strip()
    brief["detail"] = sections
    text = brief_text(brief, read_text, detail)
    ctx.notes.extend(notes)
    ctx.write("brief.txt", text)
    sent = ""
    if ctx.options.get("telegram"):
        from eulerlab import notify

        if repeat:
            sent = "Telegram not sent again: this break's note was already sent"
        elif notify.configured():
            gone = trader_read.missing(read.rows)
            if gone:
                # An incomplete read is not sent; one line says why (ADR-101).
                message = (
                    f"Brief held back: {', '.join(gone)} missing. Full brief in the workbench."
                )
            else:
                message = brief_content.telegram(brief)
            delivery = notify.send(message[:3900])
            if not delivery.sent:
                sent = f"Telegram: {delivery.reason}"
            else:
                sent = "held back on Telegram (incomplete)" if gone else "sent to Telegram"
        else:
            sent = "Telegram not configured"
    card = "\n".join([brief["headline"], *[f"- {m['title']}" for m in brief["matters"]]])
    return WorkerResult(
        f"{mode} brief for {day}" + (f"; {sent}" if sent else ""),
        [
            Item(
                kind="brief",
                title=f"{mode} brief · {day}",
                body=card,
                ref="market_brief",
                data={"headline": brief["headline"], "tone": brief["tone"]},
            )
        ],
        data={
            "fingerprint": stamp,
            "mode": mode,
            "text": text,
            "brief": brief,
            "read": read.as_dict(),
            "read_text": read_text,
            "sections": sections,
            "notes": notes,
        },
    )


def _morning(ctx: Context, day: str) -> dict[str, Any] | None:
    """Today's pre-open brief, for the after-close review."""
    from eulerlab.agents.runtime import outputs

    for out in outputs(ctx.name, ctx.root, limit=10):
        brief = out.data.get("brief") or {}
        if out.status == "ok" and brief.get("mode") == "pre-open" and brief.get("day") == day:
            return dict(brief)
    return None


def _tone(headline: str) -> str:
    lowered = headline.lower()
    if lowered.startswith("incomplete"):
        return "incomplete"
    if lowered.startswith("risk-off") or "leaning weak" in lowered:
        return "weak"
    if lowered.startswith("risk-on") or "leaning supportive" in lowered:
        return "supportive"
    return "mixed"


def build_brief(
    mode: str,
    day: str,
    inputs: dict[str, Any],
    read: trader_read.Read,
    levels: trader_read.ReadLevels,
    morning: dict[str, Any] | None,
    closed_why: str = "",
) -> dict[str, Any]:
    """The brief as data, in the order it is read (research 134). The page and Telegram draw it."""
    ctx = inputs["context"]
    strip = ctx.get("strip") or {}
    nifty: dict[str, Any] = next(
        (r for r in strip.get("indices") or [] if r.get("name") == "Nifty 50"), {}
    )
    close = nifty.get("close") if isinstance(nifty.get("close"), int | float) else None
    vix = (strip.get("vix") or {}).get("level")
    rng: dict[str, Any] = {}
    if isinstance(close, int | float) and isinstance(vix, int | float):
        move = close * vix / 100 / math.sqrt(252)
        rng = {
            "close": close,
            "low": round(close - move),
            "high": round(close + move),
            "move": round(move),
        }
    reports = inputs.get("reports") or {}
    held = {s for b in inputs.get("books") or [] for s in b.get("symbols") or []}
    ban = set((reports.get("ban") or {}).get("symbols") or [])
    flows = inputs.get("flows") or {}
    fii_nets = [float(x) for x in ((flows.get("series") or {}).get("fii") or [])]
    return {
        "mode": mode,
        "day": day,
        "as_of": nifty.get("as_of"),
        "headline": (
            f"Markets closed today ({closed_why}); last session {nifty.get('as_of')}. "
            if mode == "weekend"
            else ""
        )
        + read.bottom_line,
        "tone": _tone(read.bottom_line),
        "missing": trader_read.missing(read.rows),
        "matters": brief_content.matters(
            ctx, fii_nets=fii_nets, closes=inputs.get("closes") or [], lv=levels
        ),
        "range": rng,
        "levels": read.map,
        "scenarios": read.triggers,
        "coming_up": brief_content.coming_up(
            today=date.fromisoformat(day),
            ctx=ctx,
            events=inputs.get("events") or [],
            reports=reports,
            held=held,
            results=(inputs.get("results") or {}).get("upcoming") or [],
            results_since=(inputs.get("results") or {}).get("since") or "",
            horizon=6 if mode == "weekend" else 1,
        ),
        "attention": brief_content.attention(inputs.get("books") or [], ban),
        "books": read.books,
        "rows": [asdict(r) for r in read.rows],
        "underneath": brief_content.underneath(ctx, reports, flows),
        "review": brief_content.review(morning, read, close, str(nifty.get("as_of") or ""), day)
        if mode == "after-close"
        else brief_content.week(ctx, fii_nets)
        if mode == "weekend"
        else [],
        "review_title": "The week in review" if mode == "weekend" else "This morning vs the close",
        "left_out": read.gaps,
    }


def brief_text(brief: dict[str, Any], read_text: str, detail: str) -> str:
    """Plain text in the same order as the page: the answer first, detail last."""
    title = {"pre-open": "PRE-OPEN BRIEF", "after-close": "AFTER-CLOSE NOTE"}.get(
        brief["mode"], "MARKETS CLOSED"
    )
    lines = [
        f"{title} · {brief['day']} (data to {brief.get('as_of') or '?'})",
        "",
        brief["headline"],
    ]
    nxt = brief.get("next") or {}
    if nxt.get("story"):
        lines += ["", "WHAT HAPPENED IN THE LAST SESSION", *[f"- {x}" for x in nxt["story"]]]
    if brief.get("review"):
        lines += ["", brief["review_title"].upper(), *[f"- {r}" for r in brief["review"]]]
    lines += ["", "WHAT MATTERS TODAY"]
    for i, m in enumerate(brief["matters"], 1):
        lines += [f"{i}. {m['title']}. {m['fact']}", f"   What it means: {m['meaning']}"]
        if m.get("why"):
            lines.append(f"   Why it matters for the next session: {m['why']}")
        if m.get("watch"):
            lines.append(f"   What to watch: {m['watch']}")
    if not brief["matters"]:
        lines.append("- Nothing is far from normal today.")
    lines += brief_content.forecast_lines(nxt)
    if brief.get("history"):
        lines += [
            "",
            "WHAT HISTORY SAYS (history, not a forecast)",
            *[f"- {x}" for x in brief["history"]],
        ]
    lines += ["", "LEVELS AND WHAT WOULD CHANGE THE READ", *[f"- {x}" for x in brief["levels"]]]
    lines += [f"- If: {x}" for x in brief["scenarios"]]
    coming = brief["coming_up"]
    lines += [
        "",
        "COMING UP",
        *[f"- {c['when']}: {c['what']}. {c['why']}" for c in coming["items"]],
    ]
    lines += [f"- Not covered: {n}" for n in coming["not_covered"]]
    lines += ["", "YOUR BOOKS"]
    lines += [f"- Needs you: {a['book']} {a['why']}" for a in brief["attention"]]
    lines += [f"- {b}" for b in brief["books"]]
    if brief.get("books_history"):
        lines += [
            "",
            "YOUR BOOKS IN THIS KIND OF MARKET",
            *[f"- {x}" for x in brief["books_history"]],
        ]
    u = brief["underneath"]
    lines += ["", "UNDERNEATH"]
    for label, key in (
        ("Leading sectors", "leading"),
        ("Lagging sectors", "lagging"),
        ("New 52-week highs", "new_highs"),
        ("New 52-week lows", "new_lows"),
        ("Delivery spikes", "delivery"),
        ("Largest deals", "deals"),
    ):
        if u.get(key):
            lines.append(f"- {label}: {'; '.join(u[key])}")
    if u.get("flows"):
        lines.append(f"- Flows: {u['flows']}")
    if brief.get("note"):
        lines += ["", "ANALYST NOTE (model, not data)", brief["note"]]
    lines += ["", read_text]
    if detail:
        lines += ["", "— DETAIL —", detail.split("\n", 1)[1] if "\n" in detail else detail]
    return "\n".join(lines)


def _parse(stamp: str, ctx: Context) -> datetime:
    try:
        return datetime.fromisoformat(stamp)
    except ValueError:
        return ctx.now - timedelta(days=2)
