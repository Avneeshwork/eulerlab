"""The market brief agent: what happened, what is on today, and what it means for the books.

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

from eulerlab.agents import grounding
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
        out.append(
            {
                "id": d.id,
                "strategy": d.strategy_id,
                "mode": d.mode,
                "status": d.status,
                "traded_through": state.get("traded_through"),
                "equity": state.get("equity"),
                "warnings": list(state.get("warnings") or [])[:2],
            }
        )
    return out


def _pct(value: Any) -> str:
    return f"{value * 100:+.1f}%" if isinstance(value, int | float) else "n/a"


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
        for row in (strip.get("indices") or [])[:6]
    ]
    vix = strip.get("vix")
    if vix:
        india.append(
            f"India VIX: {vix['level']} (percentile {vix.get('percentile_1y')} of the past year)"
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
                [f"{k.replace('_', ' ')}: {v}" for k, v in list(latest.items())[:5]] or ["held"],
            )
        )
    positioning = ctx.get("positioning") or {}
    if positioning.get("available"):
        lines = [
            f"{p['participant']}: {_pct(p.get('index_futures_long_share'))} of index futures long ({_pct(p.get('change_1d'))} on the day)"
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
    books = inputs.get("books") or []
    sections.append(
        (
            "Your books",
            [
                f"{b['strategy']} ({b['mode']}, {b['status']}): traded through {b['traded_through'] or 'not yet'}"
                + (
                    f", equity {b['equity']:,.0f}"
                    if isinstance(b.get("equity"), int | float)
                    else ""
                )
                for b in books
            ]
            or ["no deployment"],
        )
    )
    data = inputs.get("data") or []
    low = [f"{g['name']} grade {g['grade']}" for g in data if g.get("grade") in ("C", "D")]
    behind = [g["name"] for g in data if g.get("freshness") in ("stale", "missing", "behind")]
    sections.append(
        (
            "Data",
            [f"Low grade: {', '.join(low) or 'none'}", f"Behind: {', '.join(behind) or 'none'}"],
        )
    )
    return sections


def render(mode: str, day: str, sections: list[tuple[str, list[str]]], commentary: str) -> str:
    title = "PRE-OPEN BRIEF" if mode == "pre-open" else "AFTER-CLOSE BRIEF"
    lines = [f"{title} · {day}"]
    for heading, body in sections:
        lines += ["", heading.upper(), *[f"- {b}" for b in body]]
    if commentary:
        lines += ["", "COMMENTARY (model, not data)", commentary.strip()]
    return "\n".join(lines)


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

    inputs: dict[str, Any] = {
        "mode": mode,
        "day": day,
        "context": _context(notes),
        "world": _world(notes, fetch=bool(ctx.options.get("world", True))),
        "events": _events(day),
        "books": _books(),
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

    sections = compose(mode, inputs)
    commentary = ""
    if ctx.can_ask():
        plain = render(mode, day, sections, "")
        try:
            commentary = ctx.ask(
                "You write three to five plain sentences of commentary under a market brief for one "
                "trader in India. Use only the numbers in the brief. Say what stands out and what to "
                "watch today. No predictions of prices, no advice to buy or sell, no markdown.",
                untrusted("brief", plain),
            )
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
    text = render(mode, day, sections, commentary)
    ctx.notes.extend(notes)
    ctx.write("brief.txt", text)
    sent = ""
    if ctx.options.get("telegram"):
        from eulerlab import notify

        if notify.configured():
            delivery = notify.send(text[:3900])
            sent = "sent to Telegram" if delivery.sent else f"Telegram: {delivery.reason}"
        else:
            sent = "Telegram not configured"
    return WorkerResult(
        f"{mode} brief for {day}" + (f"; {sent}" if sent else ""),
        [Item(kind="brief", title=f"{mode} brief · {day}", body=text)],
        data={
            "fingerprint": stamp,
            "mode": mode,
            "text": text,
            "sections": sections,
            "notes": notes,
        },
    )


def _parse(stamp: str, ctx: Context) -> datetime:
    try:
        return datetime.fromisoformat(stamp)
    except ValueError:
        return ctx.now - timedelta(days=2)
