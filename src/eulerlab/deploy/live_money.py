"""Real money: H-0194 (fade a 3% no-news opening gap) on Angel One, run from the workbench (ADR-162).

The operator enters an amount and a leverage on the Live tab and presses Deploy.
That arms **one session**. Nothing else in this file sends an order.

    evening / before 09:15   plan     tomorrow's watchlist from tonight's data: the liquid
                                      500 less ETFs, ASM/GSM, trade-for-trade and stocks a
                                      position cannot buy one share of
    09:20                    enter    Angel quotes for the watchlist; gap = open / previous
                                      close - 1; keep |gap| >= 3% with no NSE filing since
                                      15:30 yesterday and a spread <= 50 bps; largest gap
                                      first; MIS market orders against the gap
    09:21 - 15:09            watch    P&L of the open positions every minute; at the loss
                                      cap, close everything and trip the kill switch
    15:10                    exit     close every position this book opened; the deploy ends

**Why 09:20, not the open.** The backtest fills at the official opening print. On
F&O stocks with minute data the edge from 09:20 is about half of it (research 180):
that is what this book can get.

**Sizing.** Exposure = amount x leverage. A name gets at least `min_per_name`, so
a small amount trades fewer names, never a bigger one (`size`). Brokerage on Angel
is ₹20 or 0.1% per order, minimum ₹5 (A-131), so below ~₹20,000 a name it costs
about 20 bps a round trip, most of the edge.

**Fail closed.** No plan, no quotes, no filings list, a tripped kill switch or a
deploy not armed for today: nothing is sent, and the reason is written down.
Every send goes through `oms.ems.send` and the shared live governor; client
order ids are `hash(strategy, session, symbol, seq)`.
"""

from __future__ import annotations

import contextlib
import json
import math
import threading
import time as clock
import traceback
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from eulerlab import constitution
from eulerlab.paths import data_path

ROOT = data_path("live_money")
DEPLOY_FILE = ROOT / "deploy.json"
STRATEGY = "H-0194"
BOOK_ID = "H-0194-live"
IST = timedelta(hours=5, minutes=30)

GAP = 0.03
"""H-0194: |open / previous close - 1| >= 3%."""
MAX_SPREAD_BPS = 50.0
# ASSUMPTION: A-132 — a bid-ask spread wider than 50 bps at 09:20 would eat the
# ~30 bps edge left after costs; not measured, chosen as a guard.
MIN_PRICE = 100.0
"""As the research universe (`cross_section.MIN_PRICE`)."""
EDGE_BPS = 30.0
# ASSUMPTION: A-132 — H-0194 keeps about 30-50 bps gross from 09:20 (research 184);
# the low end is used to warn when brokerage alone would exceed it.
MAX_LEVERAGE = 5.0
# ASSUMPTION: A-133 — Angel One's intraday (MIS) list shows a 5.0 multiplier for
# 1,871 NSE names (`make angel-readonly`, 2026-11-09); SEBI's peak-margin rule caps
# equity intraday at 5x (20% margin). Angel's per-stock margin can be lower.

ENTER_AT = time(9, 20)
ENTER_UNTIL = time(9, 35)
"""After this the 09:20 premise is gone; a late tick does not enter."""
EXIT_AT = time(15, 10)
MARKET_OPEN = time(9, 15)


class Settings(BaseModel):
    """What the operator enters. Persisted with the deploy, never edited by code."""

    model_config = ConfigDict(extra="forbid")

    capital: float = Field(gt=0, description="Rupees in the Angel account for this book")
    leverage: float = Field(default=1.0, ge=1.0, le=MAX_LEVERAGE)
    loss_cap: float = Field(gt=0, description="Rupees lost in a day that close everything")
    max_names: int = Field(default=10, ge=1, le=10)
    min_per_name: float = Field(default=5_000.0, ge=1_000.0)


@dataclass(frozen=True)
class Sizing:
    exposure: float
    names: int
    per_name: float
    refused: str
    """Why nothing can trade at this size, or ''."""
    notes: tuple[str, ...]


def size(s: Settings) -> Sizing:
    """Names and rupees a name. Cut the names, never oversize one."""
    exposure = s.capital * s.leverage
    notes: list[str] = []
    if exposure < MIN_PRICE:
        return Sizing(
            exposure,
            0,
            0.0,
            f"₹{exposure:,.0f} of exposure cannot buy one share: the rule trades stocks of "
            f"₹{MIN_PRICE:,.0f} or more, so put in at least ₹{MIN_PRICE / s.leverage:,.0f} "
            f"at {s.leverage:g}x",
            (),
        )
    # Operator, 2026-11-09: "it should take whatever money I have". Below one name's
    # minimum the whole amount goes into one name, the largest gap a share of which fits.
    names = max(1, min(s.max_names, int(exposure // s.min_per_name)))
    per = exposure / names
    if names < s.max_names:
        notes.append(
            f"{names} name(s), not {s.max_names}: each needs at least ₹{s.min_per_name:,.0f}"
        )
    order_cost = min(20.0, max(5.0, per * 0.001))
    cost_bps = 2 * order_cost / per * 1e4
    notes.append(
        f"Brokerage about ₹{2 * order_cost:,.0f} a round trip a name "
        f"({cost_bps:.0f} bps of ₹{per:,.0f})"
    )
    if cost_bps > EDGE_BPS:
        notes.append(
            f"Warning: costs ({cost_bps:.0f} bps) are more than the edge left from 09:20 "
            f"(about {EDGE_BPS:.0f} bps): at this size the trades are expected to lose a little"
        )
    if s.leverage > 1:
        notes.append(
            f"{s.leverage:g}x: a 3% move against the book is ₹{0.03 * exposure:,.0f}, "
            f"{0.03 * s.leverage:.0%} of the ₹{s.capital:,.0f} put in"
        )
    return Sizing(exposure, names, per, "", tuple(notes))


# --- time and files ---------------------------------------------------------------------------


def now_ist() -> datetime:
    return datetime.now(timezone(IST))


def _naive(at: datetime) -> datetime:
    return at.replace(tzinfo=None)


def day_dir(session: date, root: Path = ROOT) -> Path:
    return root / session.isoformat()


def read(path: Path) -> dict[str, Any]:
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return body if isinstance(body, dict) else {}


def write(path: Path, body: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".partial")
    tmp.write_text(json.dumps(body, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)
    return path


def log(session: date, event: str, root: Path = ROOT, **fields: Any) -> None:
    path = day_dir(session, root) / "log.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {"at": datetime.now(UTC).isoformat(timespec="seconds"), "event": event, **fields}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, default=str) + "\n")


def is_session(day: date) -> bool:
    from eulerlab.ingest import holidays

    return bool(holidays.is_session(day, holidays.load_holidays(holidays.REFERENCE)))


def next_session(at: datetime) -> date:
    """The session a deploy made at `at` (IST) is for: today if before 09:15 on a
    session day, else the next session."""
    day = at.date()
    if at.time() < MARKET_OPEN and is_session(day):
        return day
    day += timedelta(days=1)
    while not is_session(day):
        day += timedelta(days=1)
    return day


# --- arming -----------------------------------------------------------------------------------


class Tripped(Protocol):
    def __call__(self) -> bool: ...


def _switch() -> Any:
    """The machine's kill switch (`oms/killswitch.py`). A function so tests can swap it."""
    from eulerlab.oms.killswitch import KillSwitch

    return KillSwitch()


def _tripped() -> bool:
    return bool(_switch().is_tripped())


def arm(
    settings: Settings,
    confirm: str,
    *,
    at: datetime | None = None,
    root: Path = ROOT,
    tripped: Tripped = _tripped,
) -> dict[str, Any]:
    """The operator's go for one session. Refused without `confirm == "DEPLOY"`."""
    constitution.refuse_agents("live_account", "arm a live session")
    at = at or now_ist()
    sized = size(settings)
    if confirm != "DEPLOY":
        return {"status": "refused", "why": "type DEPLOY to confirm: this sends real orders"}
    if sized.refused:
        return {"status": "refused", "why": sized.refused}
    if tripped():
        return {"status": "refused", "why": "the kill switch is tripped; clear it first"}
    session = next_session(at)
    body = {
        "status": "armed",
        "strategy": STRATEGY,
        "for_session": session.isoformat(),
        "armed_at": at.isoformat(timespec="seconds"),
        "settings": settings.model_dump(),
        "sizing": {"exposure": sized.exposure, "names": sized.names, "per_name": sized.per_name},
        "notes": list(sized.notes),
    }
    write(root / "deploy.json", body)
    log(session, "armed", root, settings=settings.model_dump())
    return body


def disarm(reason: str, *, root: Path = ROOT) -> dict[str, Any]:
    body = read(root / "deploy.json")
    if body.get("status") != "armed":
        return {"status": "not armed"}
    body["status"] = "stopped"
    body["stopped_why"] = reason
    body["stopped_at"] = now_ist().isoformat(timespec="seconds")
    write(root / "deploy.json", body)
    log(date.fromisoformat(body["for_session"]), "disarmed", root, why=reason)
    return body


def armed_for(session: date, root: Path = ROOT) -> Settings | None:
    body = read(root / "deploy.json")
    if body.get("status") != "armed" or body.get("for_session") != session.isoformat():
        return None
    return Settings.model_validate(body["settings"])


# --- evening: the watchlist -------------------------------------------------------------------


def plan(session: date, per_name: float, *, root: Path = ROOT) -> dict[str, Any]:
    """Candidates for `session` from data through the session before it. Places nothing."""
    from eulerlab.deploy import delivery_fade_book as fade
    from eulerlab.intraday import daily_universe_screen as du
    from eulerlab.intraday import rule_engine

    data = rule_engine.LiveData(
        since=session - timedelta(days=60), through=session - timedelta(days=1)
    )
    before = [d for d in data.sessions if d < session]
    if not before:
        return {"status": "no data", "why": "no daily bars before the session"}
    last = before[-1]
    funds = du.fund_symbols()
    watched = fade.latest_on_or_before(fade.surveillance_lists(), last)
    t2t = data.t2t.get(last, frozenset())
    candidates: dict[str, float] = {}
    dropped = {"fund": 0, "surveillance": 0, "t2t": 0, "price": 0}
    for symbol in sorted(data.liquid.get(last, frozenset())):
        bar = data.panel.get(symbol, {}).get(last)
        if bar is None:
            continue
        if symbol in funds:
            dropped["fund"] += 1
        elif watched is not None and symbol in watched:
            dropped["surveillance"] += 1
        elif symbol in t2t:
            dropped["t2t"] += 1
        elif bar.close < MIN_PRICE:
            dropped["price"] += 1  # under ₹100; a name too dear for one share is cut at 09:20
        else:
            candidates[symbol] = bar.close
    body = {
        "status": "ok",
        "for_session": session.isoformat(),
        "data_through": last.isoformat(),
        "made_at": now_ist().isoformat(timespec="seconds"),
        "per_name": per_name,
        "surveillance_list": "missing" if watched is None else f"{len(watched)} symbols",
        "dropped": dropped,
        "prev_close": candidates,
    }
    if watched is None:
        body["status"] = "no surveillance list"
        body["why"] = "the ASM/GSM list is missing: refusing rather than trading blind"
    write(day_dir(session, root) / "plan.json", body)
    return body


def data_ready_for(session: date) -> bool:
    """True when the daily panel holds the session before `session`."""
    from eulerlab.intraday import daily_universe_screen as du

    prev = session - timedelta(days=1)
    while not is_session(prev):
        prev -= timedelta(days=1)
    try:
        return bool(du.load_panel(start=prev, end=prev))
    except Exception:
        return False


# --- 09:20: filings, picks, orders ------------------------------------------------------------


def filed_symbols(prev: date, session: date, symbols: Iterable[str]) -> frozenset[str]:
    """Symbols with a non-administrative NSE filing from 15:30 on `prev` to 09:15 on
    `session` (research 179's rule). Raises when NSE does not answer: fail closed."""
    from eulerlab.ingest import nse_earnings_announcements as ann
    from eulerlab.intraday import onex_screen as onex

    opener = ann._opener()
    rows = json.loads(ann._download(opener, prev, session))
    if isinstance(rows, dict):
        rows = rows.get("data", [])
    if not isinstance(rows, list):
        msg = "NSE announcements reply is not a list"
        raise RuntimeError(msg)
    found = onex.news_times(rows, set(symbols))
    start, end = onex._at(prev, time(15, 30)), onex._at(session, MARKET_OPEN)
    return frozenset(s for s, times in found.items() if onex.had_news(times, start, end))


def _best(row: Mapping[str, Any], side: str) -> float | None:
    levels = ((row.get("depth") or {}).get(side)) or []
    price = levels[0].get("price") if levels and isinstance(levels[0], dict) else None
    return float(price) if isinstance(price, (int, float)) and price > 0 else None


def pick(
    prev_close: Mapping[str, float],
    quotes: Mapping[str, Mapping[str, Any]],
    filed: frozenset[str],
    sized: Sizing,
) -> dict[str, Any]:
    """Apply the 09:20 conditions; largest gap first; at most `sized.names`."""
    ranked: list[tuple[float, str, dict[str, Any]]] = []
    skipped: dict[str, int] = {"no quote": 0, "small gap": 0, "filing": 0, "spread": 0, "size": 0}
    for symbol, prev in prev_close.items():
        row = quotes.get(symbol)
        opened = ((row or {}).get("ohlc") or {}).get("open")
        if not row or not isinstance(opened, (int, float)) or opened <= 0 or prev <= 0:
            skipped["no quote"] += 1
            continue
        gap = opened / prev - 1.0
        if abs(gap) < GAP:
            skipped["small gap"] += 1
            continue
        if symbol in filed:
            skipped["filing"] += 1
            continue
        bid, ask = _best(row, "buy"), _best(row, "sell")
        last = row.get("last_price")
        if not bid or not ask or not isinstance(last, (int, float)) or last <= 0:
            skipped["no quote"] += 1
            continue
        spread = (ask - bid) / ((ask + bid) / 2) * 1e4
        if spread > MAX_SPREAD_BPS:
            skipped["spread"] += 1
            continue
        side = -1 if gap > 0 else 1  # against the gap
        ranked.append(
            (
                -abs(gap),
                symbol,
                {
                    "symbol": symbol,
                    "side": side,
                    "gap": round(gap, 5),
                    "prev_close": prev,
                    "official_open": float(opened),
                    "last": float(last),
                    "bid": bid,
                    "ask": ask,
                    "spread_bps": round(spread, 1),
                },
            )
        )
    ranked.sort(key=lambda x: (x[0], x[1]))
    rows = [r for _, _, r in ranked]
    picks, too_dear = allocate(rows, sized)
    skipped["size"] = too_dear
    return {"picks": picks, "passed": len(rows), "ranked": rows, "skipped": skipped}


def allocate(
    ranked: Sequence[Mapping[str, Any]], sized: Sizing
) -> tuple[list[dict[str, Any]], int]:
    """Size the ranked names: the first `sized.names` whose one share fits `per_name`,
    each bought or shorted at the touch. Returns (positions, names skipped as too dear)."""
    out: list[dict[str, Any]] = []
    too_dear = 0
    for row in ranked:
        if len(out) >= sized.names:
            break
        price = float(row["bid"] if row["side"] < 0 else row["ask"])
        quantity = math.floor(sized.per_name / price)
        if quantity < 1:
            too_dear += 1
            continue
        notional = quantity * price
        out.append(
            {
                **row,
                "price": price,
                "quantity": quantity,
                "notional": round(notional, 2),
                "est_cost": round(round_trip_cost(price, price, quantity), 2),
            }
        )
    return out, too_dear


class Desk(Protocol):
    """What the book needs from a broker. `AngelDesk` is the real one; tests fake it."""

    def quotes(self, symbols: list[str]) -> dict[str, dict[str, Any]]: ...
    def send(
        self, coid: str, session: date, symbol: str, buy: bool, quantity: int, *, check: bool = True
    ) -> dict[str, Any]: ...
    def order(self, coid: str) -> dict[str, Any] | None: ...
    def positions(self) -> dict[str, int]: ...
    def funds(self) -> float | None: ...


def client_order_id(session: date, symbol: str, seq: int) -> str:
    from eulerlab.backtest.events import client_order_id as coid

    return coid(BOOK_ID, session, symbol, seq)


class AngelDesk:
    """Angel One through `broker/smartapi.SmartAPIBroker` (MIS), the EMS and the live governor."""

    def __init__(self) -> None:
        from eulerlab.broker import angel_check

        constitution.refuse_agents("live_account", "log in to the live broker account")
        self.client, _ = angel_check.login()
        self._tokens: dict[str, str] = {}

    def quotes(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        from eulerlab.broker import angel_check

        return angel_check.quotes(symbols, self.client)

    def _broker(self, symbols: Sequence[str]) -> Any:
        from eulerlab.broker import angel_check
        from eulerlab.broker.smartapi import SmartAPIBroker

        missing = [s for s in symbols if s not in self._tokens]
        if missing:
            self._tokens.update(angel_check.tokens_for(self.client, missing))
        return SmartAPIBroker(self.client, symbol_tokens=self._tokens, product_type="INTRADAY")

    def send(
        self, coid: str, session: date, symbol: str, buy: bool, quantity: int, *, check: bool = True
    ) -> dict[str, Any]:
        """`check=False` only for exits: closing is what a tripped switch wants done."""
        constitution.refuse_agents("live_account", "send a live order")
        from eulerlab.backtest.events import Order
        from eulerlab.costs.schedule import Side
        from eulerlab.oms import ems

        if check:
            _switch().require_clear()  # raises: a tripped switch never opens risk
        ems.live_governor().acquire()
        order = Order(
            client_order_id=coid,
            strategy_id=BOOK_ID,
            signal_day=session,
            symbol=symbol,
            side=Side.BUY if buy else Side.SELL,
            quantity=quantity,
        )
        outcome = ems.send(self._broker([symbol]), order)
        return {
            "event": outcome.event.value,
            "broker_order_id": outcome.broker_order_id,
            "detail": outcome.detail,
        }

    def order(self, coid: str) -> dict[str, Any] | None:
        view = self._broker([]).query(coid)
        if view is None:
            return None
        return {
            "status": str(getattr(view, "status", "unknown")).lower(),
            "filled": getattr(view, "filled_quantity", None),
            "average_price": getattr(view, "average_price", None),
            "reason": getattr(view, "reason", ""),
        }

    def positions(self) -> dict[str, int]:
        return dict(self._broker([]).positions())

    def funds(self) -> float | None:
        reply = self.client.rmsLimit()
        cash: Any = ((reply or {}).get("data") or {}).get("availablecash")
        try:
            return float(cash)
        except (TypeError, ValueError):
            return None


def _sleep(seconds: float) -> None:
    clock.sleep(seconds)


def _wait(desk: Desk, coid: str, timeout: float = 20.0) -> dict[str, Any] | None:
    deadline = clock.monotonic() + timeout
    view = None
    while clock.monotonic() < deadline:
        view = desk.order(coid)
        if view and view.get("status") in ("complete", "rejected", "cancelled"):
            return view
        _sleep(1.0)
    return view


def enter(
    session: date,
    desk: Desk,
    *,
    send: bool,
    root: Path = ROOT,
    filings: Callable[[date, date, Iterable[str]], frozenset[str]] = filed_symbols,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """The 09:20 step. With `send=False` it is a dry run: the same picks, no orders."""
    path = day_dir(session, root) / ("open.json" if send else "dry_run.json")
    settings = settings or armed_for(session, root)
    if settings is None:
        write(path, {"status": "not armed"})
        return {"status": "not armed"}
    sized = size(settings)
    body: dict[str, Any]
    planned = read(day_dir(session, root) / "plan.json")
    if planned.get("status") != "ok":
        body = {"status": "no plan", "why": planned.get("why", "no watchlist for this session")}
        write(path, body)
        return body
    prev = date.fromisoformat(planned["data_through"])
    symbols = sorted(planned["prev_close"])
    try:
        filed = filings(prev, session, symbols)
    except Exception as exc:
        body = {"status": "no filings list", "why": f"{type(exc).__name__}: {str(exc)[:200]}"}
        write(path, body)
        return body
    try:
        quotes = desk.quotes(symbols)
    except Exception as exc:
        body = {"status": "no quotes", "why": f"{type(exc).__name__}: {str(exc)[:200]}"}
        write(path, body)
        return body
    chosen = pick(planned["prev_close"], quotes, filed, sized)
    body = {
        "status": "dry run" if not send else "sent",
        "session": session.isoformat(),
        "at": now_ist().isoformat(timespec="seconds"),
        "sizing": {"names": sized.names, "per_name": sized.per_name},
        "filed_today": len(filed),
        **chosen,
        "orders": [],
    }
    if send:
        for p in chosen["picks"]:
            coid = client_order_id(session, p["symbol"], 0)
            try:
                sent = desk.send(coid, session, p["symbol"], p["side"] > 0, p["quantity"])
            except Exception as exc:  # the kill switch, or the governor gave up
                sent = {"event": "not sent", "detail": f"{type(exc).__name__}: {exc}"}
                body["orders"].append({"symbol": p["symbol"], "coid": coid, **sent})
                break
            view = _wait(desk, coid) if sent["event"] in ("send_ok", "send_ambiguous") else None
            body["orders"].append({"symbol": p["symbol"], "coid": coid, **sent, "view": view})
            log(session, "entry", root, symbol=p["symbol"], side=p["side"], sent=sent, view=view)
    write(path, body)
    return body


# --- the day: watch, exit ---------------------------------------------------------------------


def book_positions(session: date, desk: Desk, root: Path = ROOT) -> dict[str, int]:
    """Broker positions in this book's symbols. The broker is the truth (CLAUDE.md)."""
    opened = read(day_dir(session, root) / "open.json")
    mine = {o["symbol"] for o in opened.get("orders", [])}
    return {s: q for s, q in desk.positions().items() if s in mine and q}


def pnl(session: date, desk: Desk, root: Path = ROOT) -> dict[str, Any]:
    """Mark the book: entry average from the broker's fill, last price from a quote.
    Costs are estimated (brokerage both legs, STT, exchange, GST, stamp), A-131."""
    opened = read(day_dir(session, root) / "open.json")
    exits = read(day_dir(session, root) / "close.json")
    held = book_positions(session, desk, root)
    rows = []
    symbols = [
        o["symbol"] for o in opened.get("orders", []) if (o.get("view") or {}).get("average_price")
    ]
    quotes = desk.quotes(symbols) if symbols else {}
    total = 0.0
    for o in opened.get("orders", []):
        view = o.get("view") or {}
        avg, filled = view.get("average_price"), view.get("filled") or 0
        if not avg or not filled:
            continue
        side = next((p["side"] for p in opened.get("picks", []) if p["symbol"] == o["symbol"]), 0)
        if not side:
            continue
        out = next((e for e in exits.get("orders", []) if e["symbol"] == o["symbol"]), None)
        out_price = ((out or {}).get("view") or {}).get("average_price")
        mark = float(out_price) if out_price else (quotes.get(o["symbol"]) or {}).get("last_price")
        if not isinstance(mark, (int, float)):
            continue
        gross = side * (float(mark) - float(avg)) * int(filled)
        cost = round_trip_cost(float(avg), float(mark), int(filled))
        total += gross - cost
        rows.append(
            {
                "symbol": o["symbol"],
                "side": side,
                "quantity": int(filled),
                "entry": float(avg),
                "mark": float(mark),
                "closed": bool(out_price),
                "held": held.get(o["symbol"], 0),
                "gross": round(gross, 2),
                "costs": round(cost, 2),
                "net": round(gross - cost, 2),
            }
        )
    return {"rows": rows, "net": round(total, 2)}


# ASSUMPTION: A-131 — Angel intraday brokerage ₹20 or 0.1% per executed order, min ₹5
# (angelone.in support page, 2026-11-09); STT 0.025% on the sell; NSE transaction
# 0.00297%; SEBI ₹10 a crore; GST 18% on brokerage and fees; stamp 0.003% on the buy.
def round_trip_cost(entry: float, exit_: float, quantity: int) -> float:
    buy, sell = entry * quantity, exit_ * quantity
    brokerage = sum(min(20.0, max(5.0, v * 0.001)) for v in (buy, sell))
    exchange = (buy + sell) * 0.0000297
    sebi = (buy + sell) * 1e-6
    return (
        brokerage
        + sell * 0.00025
        + exchange
        + sebi
        + 0.18 * (brokerage + exchange + sebi)
        + buy * 0.00003
    )


def exit_all(session: date, desk: Desk, reason: str, *, root: Path = ROOT) -> dict[str, Any]:
    """Close every position this book holds at the broker. Idempotent: run it again and
    it closes only what is still open, with the next sequence number."""
    path = day_dir(session, root) / "close.json"
    body = read(path) or {"session": session.isoformat(), "orders": [], "reasons": []}
    body["reasons"].append({"at": now_ist().isoformat(timespec="seconds"), "why": reason})
    held = book_positions(session, desk, root)
    for symbol, quantity in sorted(held.items()):
        seq = 1 + sum(1 for o in body["orders"] if o["symbol"] == symbol)
        coid = client_order_id(session, symbol, seq)
        try:
            sent = desk.send(coid, session, symbol, quantity < 0, abs(quantity), check=False)
        except Exception as exc:
            sent = {"event": "not sent", "detail": f"{type(exc).__name__}: {exc}"}
        view = _wait(desk, coid) if sent.get("event") in ("send_ok", "send_ambiguous") else None
        body["orders"].append({"symbol": symbol, "coid": coid, **sent, "view": view})
        log(session, "exit", root, symbol=symbol, why=reason, sent=sent, view=view)
    body["still_held"] = book_positions(session, desk, root)
    body["status"] = "flat" if not body["still_held"] else "positions still open"
    write(path, body)
    return body


def watch(session: date, desk: Desk, settings: Settings, *, root: Path = ROOT) -> dict[str, Any]:
    """Mark the book; at the loss cap, close everything and trip the kill switch."""
    marked = pnl(session, desk, root)
    marked["at"] = now_ist().isoformat(timespec="seconds")
    marked["loss_cap"] = settings.loss_cap
    if marked["net"] <= -settings.loss_cap:
        why = (
            f"{BOOK_ID}: day loss ₹{-marked['net']:,.0f} reached the cap ₹{settings.loss_cap:,.0f}"
        )
        _switch().trip(why, by="live_money")
        marked["stopped"] = why
        exit_all(session, desk, why, root=root)
    write(day_dir(session, root) / "watch.json", marked)
    return marked


def kill(
    reason: str, desk_factory: Callable[[], Desk] = AngelDesk, *, root: Path = ROOT
) -> dict[str, Any]:
    """The operator's button: trip the switch, close today's positions, disarm."""
    _switch().trip(reason, by="operator (workbench)")
    session = now_ist().date()
    out: dict[str, Any] = {"tripped": True}
    if (day_dir(session, root) / "open.json").exists():
        out["exit"] = exit_all(session, desk_factory(), reason, root=root)
    out["deploy"] = disarm(reason, root=root)
    return out


# --- the clock --------------------------------------------------------------------------------


def tick(
    at: datetime | None = None,
    *,
    root: Path = ROOT,
    desk_factory: Callable[[], Desk] = AngelDesk,
) -> str:
    """One step of the armed deploy, chosen by the time. Safe to call every 20 s."""
    at = at or now_ist()
    deploy = read(root / "deploy.json")
    if deploy.get("status") != "armed":
        return "idle"
    session = date.fromisoformat(deploy["for_session"])
    settings = Settings.model_validate(deploy["settings"])
    folder = day_dir(session, root)
    if at.date() > session:
        disarm("the session passed", root=root)
        return "expired"
    if not (folder / "plan.json").exists() or read(folder / "plan.json").get("status") != "ok":
        if data_ready_for(session) and (at.date() < session or at.time() < ENTER_AT):
            plan(session, size(settings).per_name, root=root)
            return "planned"
        if at.date() < session:
            return "waiting for tonight's data"
    if at.date() < session:
        return "armed"
    now = at.time()
    if now < ENTER_AT:
        return "waiting for 09:20"
    if ENTER_AT <= now < ENTER_UNTIL and not (folder / "open.json").exists():
        enter(session, desk_factory(), send=True, root=root, settings=settings)
        return "entered"
    if now >= ENTER_UNTIL and not (folder / "open.json").exists():
        write(folder / "open.json", {"status": "missed", "why": f"no entry by {ENTER_UNTIL}"})
        disarm("missed the 09:20 entry", root=root)
        return "missed"
    opened = read(folder / "open.json")
    if not opened.get("orders"):
        if now >= EXIT_AT:
            disarm("session over, nothing traded", root=root)
        return "nothing open"
    if now >= EXIT_AT:
        if read(folder / "close.json").get("status") != "flat":
            exit_all(session, desk_factory(), "15:10 exit", root=root)
            return "exited"
        disarm("session done", root=root)
        return "done"
    last = read(folder / "watch.json").get("at", "")
    if not last or _naive(at) - datetime.fromisoformat(last).replace(tzinfo=None) >= timedelta(
        seconds=55
    ):
        watch(session, desk_factory(), settings, root=root)
        return "watched"
    return "holding"


class Clock:
    """The API server's background thread: `tick` every 20 seconds while armed."""

    def __init__(self, every: float = 20.0) -> None:
        self.every = every
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last: str = "not started"

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="live-money-clock", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.last = tick()
            except Exception as exc:
                self.last = f"error: {type(exc).__name__}: {exc}"
                session = now_ist().date()
                log(session, "tick error", error=traceback.format_exc()[-1500:])
            self.beat()
            self._stop.wait(self.every)

    def beat(self, at: datetime | None = None, root: Path = ROOT) -> None:
        """Every tick leaves its time, so the dead-man switch (`oms/deadman.py`), in
        another process, can tell a live book from a dead one."""
        at = at or now_ist()
        with contextlib.suppress(OSError):
            write(
                root / "heartbeat.json", {"at": at.isoformat(timespec="seconds"), "last": self.last}
            )


CLOCK = Clock()


# --- what the workbench shows -----------------------------------------------------------------


def what_if(settings: Settings, *, root: Path = ROOT) -> dict[str, Any]:
    """The positions `settings` would hold on the latest dry run's or entry's quotes."""
    sized = size(settings)
    for folder in sorted((d for d in root.glob("20*") if d.is_dir()), reverse=True):
        for name in ("open", "dry_run"):
            body = read(folder / f"{name}.json")
            if "ranked" in body:
                positions, too_dear = allocate(body["ranked"], sized) if sized.names else ([], 0)
                return {
                    "from": f"{name.replace('_', ' ')} of {folder.name} at {str(body.get('at', ''))[11:16]}",
                    "passed": len(body["ranked"]),
                    "too_dear": too_dear,
                    "positions": positions,
                    "exposure_used": round(sum(p["notional"] for p in positions), 2),
                    "est_cost": round(sum(p["est_cost"] for p in positions), 2),
                }
    return {"from": "", "positions": [], "why": "no dry run yet: press Dry run to see real stocks"}


def status(*, root: Path = ROOT) -> dict[str, Any]:
    switch = _switch()
    deploy = read(root / "deploy.json")
    session = (
        date.fromisoformat(deploy["for_session"]) if deploy.get("for_session") else now_ist().date()
    )
    today = now_ist().date()
    days = {}
    for day in sorted({session, today}):
        folder = day_dir(day, root)
        days[day.isoformat()] = {
            name: read(folder / f"{name}.json")
            for name in ("plan", "dry_run", "open", "watch", "close")
            if (folder / f"{name}.json").exists()
        }
        for body in days[day.isoformat()].values():
            body.pop("prev_close", None)  # 400 names the panel does not show
    return {
        "strategy": STRATEGY,
        "deploy": deploy,
        "kill_switch": {"tripped": switch.is_tripped(), "reason": switch.reason()},
        "clock": CLOCK.last,
        "now_ist": now_ist().isoformat(timespec="seconds"),
        "days": days,
    }


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="H-0194 real-money book (ADR-162).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    dry = sub.add_parser("dry-run", help="plan + picks on live quotes now; sends nothing")
    dry.add_argument("--capital", type=float, required=True)
    dry.add_argument("--leverage", type=float, default=1.0)
    sub.add_parser("tick")
    sub.add_parser("status")
    args = parser.parse_args(argv)
    if args.cmd == "tick":
        print(tick())
        return 0
    if args.cmd == "status":
        print(json.dumps(status(), indent=2, default=str))
        return 0
    body = dry_run(Settings(capital=args.capital, leverage=args.leverage, loss_cap=1.0))
    print(json.dumps(body, indent=2, default=str))
    return 0


def dry_run(
    settings: Settings, *, root: Path = ROOT, desk_factory: Callable[[], Desk] = AngelDesk
) -> dict[str, Any]:
    """Today's picks as if armed: the watchlist from the last session's data, today's open
    from live quotes, today's filings. Sends nothing. Writes `dry_run.json`."""
    today = now_ist().date()
    session = today if is_session(today) else next_session(now_ist())
    sized = size(settings)
    if sized.refused:
        return {"status": "refused", "why": sized.refused}
    planned = plan(session, sized.per_name, root=root)
    if planned.get("status") != "ok":
        return planned
    if session != today or now_ist().time() < MARKET_OPEN:
        return {
            "status": "planned",
            "why": "the market has not opened; picks come at 09:20",
            **planned,
        }
    return enter(session, desk_factory(), send=False, root=root, settings=settings)


if __name__ == "__main__":
    raise SystemExit(main())
