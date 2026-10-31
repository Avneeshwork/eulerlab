"""The market brief agent: what happened, what is on today, and what it means for the books.

**Answer first** (ADR-100). The brief opens with the Trader's read
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
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from eulerlab.agents import grounding, trader_read
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

        events = forexfactory.read_all(stale_ok=True)
    except Exception:
        return []
    out = []
    for e in events:
        if e.event_time[:10] == now_ist_day and e.impact.lower() in ("high", "medium"):
            out.append(
                {"title": e.title, "country": e.country, "time": e.event_time, "impact": e.impact}
            )
    return out[:12]


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
            }
        )
    return out


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
    "You write an analyst note under one trader's market read for India. Use only the numbers "
    "in the read. Answer exactly these three, each on its own line starting with its label, one "
    "or two sentences each:\n"
    "What matters today: the one or two signals that explain the bottom line, and why.\n"
    "What to watch: the level or number in the read that decides the session.\n"
    "What would prove it wrong: which trigger in the read, if hit, flips the bottom line.\n"
    "No price predictions, no advice to buy or sell, no markdown."
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
    mode = str(ctx.args.get("mode") or ("pre-open" if now_ist.hour < 12 else "after-close"))
    day = now_ist.date().isoformat()
    notes: list[str] = []
    from eulerlab.quality import contract

    ctx.step(f"Gathering market context, world markets, events and books for the {mode} brief")
    inputs: dict[str, Any] = {
        "mode": mode,
        "day": day,
        "context": _context(notes),
        "world": _world(notes, fetch=bool(ctx.options.get("world", True))),
        "events": _events(day),
        "books": _books(),
        "flows": _flows(),
        "closes": _closes(),
        "data": [
            {"name": g.get("name"), "grade": g.get("grade"), "freshness": g.get("freshness")}
            for g in contract.saved()
        ],
    }
    stamp = fingerprint(inputs)
    last = latest_output(ctx.name, ctx.root)
    force = str(ctx.args.get("force", "")).lower() in ("1", "true", "yes")
    if (
        not force
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

    ctx.step("Writing the Trader's read and the brief from the numbers gathered")
    read = trader_read.build(
        inputs["context"],
        closes=inputs["closes"],
        flows=inputs["flows"],
        books=inputs["books"],
        day=day,
        lv=trader_read.levels(),
    )
    read_text = trader_read.render(read)
    sections = compose(mode, inputs)
    commentary = ""
    if ctx.can_ask():
        plain = render(mode, day, sections, "", read_text)
        try:
            commentary = ctx.ask(QUESTIONS, untrusted("read", read_text))
        except Exception as exc:
            notes.append(f"no commentary: {type(exc).__name__}: {str(exc)[:120]}")
        if commentary:
            found = grounding.check(commentary, [plain])
            if not found.ok:
                notes.append(
                    "commentary dropped: it used figures not in the brief "
                    f"({', '.join(found.unsupported)}) (ADR-088)"
                )
                commentary = ""
    text = render(mode, day, sections, commentary, read_text)
    ctx.notes.extend(notes)
    ctx.write("brief.txt", text)
    sent = ""
    if ctx.options.get("telegram"):
        from eulerlab import notify

        if notify.configured():
            gone = trader_read.missing(read.rows)
            if gone:
                # An incomplete read is not sent; one line says why (ADR-101).
                message = (
                    f"Brief held back: {', '.join(gone)} missing. Full brief in the workbench."
                )
            else:
                title = "PRE-OPEN" if mode == "pre-open" else "AFTER-CLOSE"
                message = (
                    f"{title} · {day}\n\n{read_text}\n\nFull brief: workbench → AI → market_brief"
                )
            delivery = notify.send(message[:3900])
            if not delivery.sent:
                sent = f"Telegram: {delivery.reason}"
            else:
                sent = "held back on Telegram (incomplete)" if gone else "sent to Telegram"
        else:
            sent = "Telegram not configured"
    return WorkerResult(
        f"{mode} brief for {day}" + (f"; {sent}" if sent else ""),
        [Item(kind="brief", title=f"{mode} brief · {day}", body=text)],
        data={
            "fingerprint": stamp,
            "mode": mode,
            "text": text,
            "read": read.as_dict(),
            "read_text": read_text,
            "sections": sections,
            "notes": notes,
        },
    )


def _parse(stamp: str, ctx: Context) -> datetime:
    try:
        return datetime.fromisoformat(stamp)
    except ValueError:
        return ctx.now - timedelta(days=2)
