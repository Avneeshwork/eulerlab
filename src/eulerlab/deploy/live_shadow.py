"""Live-price paper: price each intraday book's picks on Kite quotes during the session (ADR-153).

The paper books (`deploy/engine_book.py`) fill at the official open and close
from the evening's bhavcopy: the same assumption as the backtest, so they
cannot say what a real order would have got. This module measures that gap,
without sending anything:

    evening  `make live-shadow-plan`    next session's candidates per book, from
                                        signals known tonight; saved as a watchlist
    09:16    `make live-shadow-open`    Kite quotes for the candidates: the official
                                        open, today's gap, best bid and ask, the spread;
                                        the book's picks, ranked as the rule ranks them
    15:10    `make live-shadow-close`   quotes again, where an MIS position must be
                                        closed (the broker squares off from 15:12)
    evening  `make live-shadow-reconcile` official close from the bhavcopy; per trade
                                        the backtest's return, the achievable return, and
                                        the slippage between them

**Achievable** means crossing the spread at the moment of the sweep: a short
sells at the best bid and covers at the best ask; a long the other way. It is
still optimistic: it assumes the top of the book holds our size (A-123).

**Nothing here places an order.** It reads quotes through `quotes`' Kite session
(read-only) and writes files under `data/live_shadow/`. The summary is what the
readiness checklist (`deploy/readiness.py`) reads.

**What it supports.** Engine cards whose only same-morning condition is `gap`
(H-0175), and rules restated as engine specs in `config/live_shadow.yaml`
(H-0161). A card needing that morning's disclosures (`results_morning`, deals)
is listed as not supported yet: the evening plan cannot see them.

**History.** The plan reads about 200 calendar days of daily data before the
session, so a 20-session ratio is ready on the first day. The paper books read
nothing before the holdout end (ADR-148) and so trade nothing for their first
20 sessions; the shadow's picks can therefore differ from a paper book's until
then, and the plan says so.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from eulerlab.paths import data_path

ROOT = data_path("live_shadow")
CONFIG = Path("config/live_shadow.yaml")
SLOTS = 10
HISTORY_DAYS = 200
OPEN = (9, 15)
IST = timedelta(hours=5, minutes=30)

Quotes = Callable[[list[str]], dict[str, dict[str, Any]]]
"""symbols -> {symbol: Kite `quote()` row}: `ohlc.open`, `ohlc.close`, `last_price`, `depth`."""


# --- which books, as specs ------------------------------------------------------------------


@dataclass(frozen=True)
class Book:
    strategy: str
    spec: Any
    """A `rule_engine.RuleSpec`."""
    source: str
    """`card` (the hypothesis's own engine block) or `restated` (config/live_shadow.yaml)."""


def books(config: Path = CONFIG) -> tuple[list[Book], dict[str, str]]:
    """(books to shadow, {strategy: why it is not shadowed})."""
    from eulerlab.intraday import rule_engine

    if not config.exists():
        return [], {}
    raw = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    out: list[Book] = []
    skipped: dict[str, str] = {}
    for entry in raw.get("books") or []:
        sid = str(entry["strategy"])
        block = entry.get("engine")
        try:
            spec = (
                rule_engine.RuleSpec.model_validate(block)
                if isinstance(block, dict)
                else rule_engine.card_spec(sid)
            )
        except ValueError as exc:
            skipped[sid] = f"spec does not parse: {exc}"
            continue
        if spec is None:
            skipped[sid] = "no engine block on the card and none restated"
            continue
        why = unsupported(spec)
        if why:
            skipped[sid] = why
            continue
        out.append(Book(sid, spec, "restated" if isinstance(block, dict) else "card"))
    return out, skipped


def unsupported(spec: Any) -> str:
    if spec.kind != "intraday":
        return "swing books are not shadowed (their fills are at an open and a close days apart)"
    morning = [c.signal for c in [*spec.when, spec.rank_by] if c.lag == 0 and c.signal != "gap"]
    if morning:
        return f"needs that morning's {', '.join(sorted(set(morning)))}, which the evening plan cannot see"
    return ""


# --- evening: the watchlist -----------------------------------------------------------------


def _shift(signal: Any) -> Any:
    """The same signal read one session earlier relative to tonight (lag k for tomorrow = lag k-1 tonight)."""
    return signal.model_copy(update={"lag": signal.lag - 1})


def _at_open(signal: Any) -> bool:
    return bool(signal.lag == 0 and signal.signal == "gap")


def fund_symbols(panel: Path | None = None) -> frozenset[str]:
    """ETFs and fund units (INF ISINs), never shadowed: their official opening print is
    often stale (research 180), so a gap from it is not a real gap."""
    from eulerlab.intraday import daily_universe_screen as du

    return du.fund_symbols(panel or du.PANEL)


def plan_book(
    engine: Any,
    data: Any,
    book: Book,
    last: date,
    watched: frozenset[str],
    funds: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Tonight's candidates for the session after `last`: every condition known tonight holds."""
    from eulerlab.intraday import cross_section as cs

    spec = book.spec
    known = [c for c in spec.when if not _at_open(c)]
    at_open = [
        {"op": c.op, "value": c.value, "absolute": c.absolute} for c in spec.when if _at_open(c)
    ]
    liquid = data.liquid.get(last, frozenset())
    t2t = data.t2t.get(last, frozenset())
    candidates: dict[str, float | None] = {}
    for symbol in sorted(liquid):
        if symbol in t2t or symbol in funds or (spec.side == "short" and symbol in watched):
            continue
        bar = data.panel.get(symbol, {}).get(last)
        if bar is None or bar.close < cs.MIN_PRICE:
            continue
        if not all(engine._holds(_shift(c), symbol, last) for c in known):
            continue
        rank = None if _at_open(spec.rank_by) else engine.value(_shift(spec.rank_by), symbol, last)
        if rank is None and not _at_open(spec.rank_by):
            continue
        candidates[symbol] = rank
    return {
        "strategy": book.strategy,
        "source": book.source,
        "side": spec.side,
        "rule": spec.describe(),
        "at_open": at_open,
        "rank_at_open": _at_open(spec.rank_by),
        "rank_order": spec.rank_by.order,
        "prev_close": {s: data.panel[s][last].close for s in candidates},
        "candidates": candidates,
    }


def next_session(last: date, closed: frozenset[date]) -> date:
    from eulerlab.ingest import holidays

    d = last + timedelta(days=1)
    while not holidays.is_session(d, closed):
        d += timedelta(days=1)
    return d


def plan(root: Path = ROOT, config: Path = CONFIG) -> Path:
    """Write tomorrow's watchlist. Reads ~200 days of daily data; places nothing."""
    from eulerlab.deploy import delivery_fade_book as fade
    from eulerlab.ingest import holidays
    from eulerlab.intraday import rule_engine

    shadowed, skipped = books(config)
    today = (datetime.now(UTC) + IST).date()
    data = rule_engine.LiveData(since=today - timedelta(days=HISTORY_DAYS), through=today)
    last = data.sessions[-1]
    session = next_session(last, holidays.load_holidays(holidays.REFERENCE))
    lists = fade.surveillance_lists()
    watched = fade.latest_on_or_before(lists, today)
    engine = rule_engine.Engine(data)
    funds = fund_symbols()
    body = {
        "for_session": session.isoformat(),
        "data_through": last.isoformat(),
        "made_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "surveillance_list": "missing" if watched is None else f"{len(watched)} symbols",
        "books": [
            plan_book(engine, data, b, last, watched or frozenset(), funds) for b in shadowed
        ],
        "funds_excluded": len(funds),
        "not_shadowed": skipped,
    }
    path = root / session.isoformat() / "plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2, default=str), encoding="utf-8")
    return path


# --- 09:16: the open ------------------------------------------------------------------------


def _ok(op: str | None, value: float | None, x: float) -> bool:
    if op is None or value is None:
        return True
    return {">=": x >= value, "<=": x <= value, ">": x > value, "<": x < value}[op]


# ASSUMPTION: A-123 — the top of the book holds our size.
def _best(row: Mapping[str, Any], side: str) -> float | None:
    """Best bid (`buy`) or best ask (`sell`) from a Kite depth, or None."""
    levels = ((row.get("depth") or {}).get(side)) or []
    price = levels[0].get("price") if levels and isinstance(levels[0], dict) else None
    return float(price) if isinstance(price, (int, float)) and price > 0 else None


def pick(
    book: Mapping[str, Any], quotes: Mapping[str, Mapping[str, Any]], at: str
) -> dict[str, Any]:
    """Apply the at-open conditions to the quotes; rank; take the best `SLOTS`."""
    from eulerlab.intraday import cross_section as cs

    short = book["side"] == "short"
    ranked: list[tuple[float, str, dict[str, Any]]] = []
    missing = []
    for symbol, rank in book["candidates"].items():
        row = quotes.get(symbol)
        prev = book["prev_close"].get(symbol)
        opened = (row or {}).get("ohlc", {}).get("open") if row else None
        if not row or not isinstance(opened, (int, float)) or not opened or not prev:
            missing.append(symbol)
            continue
        gap = opened / prev - 1.0
        if opened < cs.MIN_PRICE:
            continue
        if not all(
            _ok(c["op"], c["value"], abs(gap) if c["absolute"] else gap) for c in book["at_open"]
        ):
            continue
        key = gap if book["rank_at_open"] else rank
        if key is None:
            continue
        order = -key if book["rank_order"] == "desc" else key
        bid, ask = _best(row, "buy"), _best(row, "sell")
        entry = bid if short else ask
        ranked.append(
            (
                order,
                symbol,
                {
                    "symbol": symbol,
                    "side": -1 if short else 1,
                    "gap": round(gap, 5),
                    "official_open": float(opened),
                    "entry_quote": entry,
                    "bid": bid,
                    "ask": ask,
                    "last": row.get("last_price"),
                    "spread_bps": round((ask - bid) / ((ask + bid) / 2) * 1e4, 2)
                    if bid and ask
                    else None,
                    "entry_at": at,
                },
            )
        )
    ranked.sort(key=lambda x: (x[0], x[1]))
    return {
        "strategy": book["strategy"],
        "picks": [r for _, _, r in ranked[:SLOTS]],
        "passed_at_open": len(ranked),
        "no_quote": missing,
    }


def _kite_quotes(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Full Kite quotes (with depth), read-only. Raises with Kite's message on failure."""
    from kiteconnect import KiteConnect

    from eulerlab import quotes
    from eulerlab.broker import kite_session

    session = kite_session.load()
    if session is None or not kite_session.is_fresh(session):
        msg = "no fresh Kite session: run `make kite-login` before 09:15"
        raise RuntimeError(msg)
    kite = KiteConnect(api_key=quotes._env("ZERODHA_API_KEY"))
    kite.set_access_token(session.access_token)
    out: dict[str, dict[str, Any]] = {}
    for i in range(0, len(symbols), quotes.ZERODHA_BATCH):
        batch = symbols[i : i + quotes.ZERODHA_BATCH]
        for key, row in kite.quote([f"NSE:{s}" for s in batch]).items():
            out[key.split(":", 1)[-1]] = row
    return out


def _any_quotes(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Kite first; Angel One (logs itself in by TOTP, ADR-154) when Kite has no fresh token."""
    try:
        return _kite_quotes(symbols)
    except Exception as kite_exc:
        from eulerlab.broker import angel_check

        try:
            return angel_check.quotes(symbols)
        except Exception as angel_exc:
            msg = f"Kite: {kite_exc}; Angel: {angel_exc}"
            raise RuntimeError(msg) from angel_exc


def _source(quotes: Mapping[str, Mapping[str, Any]]) -> str:
    return next((str(r.get("source", "kite")) for r in quotes.values()), "none")


def _now_ist() -> datetime:
    return datetime.now(UTC) + IST


def _seconds_after_open(at: datetime) -> float:
    opened = at.replace(hour=OPEN[0], minute=OPEN[1], second=0, microsecond=0)
    return round((at - opened).total_seconds(), 1)


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write(path: Path, body: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2, default=str), encoding="utf-8")
    return path


def open_session(
    day: date | None = None, root: Path = ROOT, get: Quotes = _any_quotes
) -> dict[str, Any]:
    clock = _now_ist()
    day = day or clock.date()
    planned = _read(root / day.isoformat() / "plan.json")
    body: dict[str, Any]
    if not planned:
        body = {"status": "no plan", "why": f"no watchlist for {day}: run live-shadow-plan"}
        _write(root / day.isoformat() / "open.json", body)
        return body
    symbols = sorted({s for b in planned["books"] for s in b["candidates"]})
    started = datetime.now(UTC)
    try:
        quotes = get(symbols) if symbols else {}
    except Exception as exc:  # a dead token is the expected morning failure
        body = {"status": "no quotes", "why": f"{type(exc).__name__}: {str(exc)[:200]}"}
        _write(root / day.isoformat() / "open.json", body)
        return body
    took = (datetime.now(UTC) - started).total_seconds()
    at = (started + IST).isoformat(timespec="seconds")
    body = {
        "status": "ok",
        "session": day.isoformat(),
        "swept_at": at,
        "seconds_after_open": _seconds_after_open(started + IST),
        "quote_seconds": round(took, 3),
        "symbols_quoted": len(quotes),
        "quote_source": _source(quotes),
        "books": [pick(b, quotes, at) for b in planned["books"]],
    }
    _write(root / day.isoformat() / "open.json", body)
    return body


# --- 15:10: the exit ------------------------------------------------------------------------


def close_session(
    day: date | None = None, root: Path = ROOT, get: Quotes = _any_quotes
) -> dict[str, Any]:
    day = day or _now_ist().date()
    opened = _read(root / day.isoformat() / "open.json")
    if opened.get("status") != "ok":
        body = {"status": "no open", "why": opened.get("why", "the open sweep did not run")}
        _write(root / day.isoformat() / "close.json", body)
        return body
    symbols = sorted({p["symbol"] for b in opened["books"] for p in b["picks"]})
    started = datetime.now(UTC)
    try:
        quotes = get(symbols) if symbols else {}
    except Exception as exc:
        body = {"status": "no quotes", "why": f"{type(exc).__name__}: {str(exc)[:200]}"}
        _write(root / day.isoformat() / "close.json", body)
        return body
    at = (started + IST).isoformat(timespec="seconds")
    exits = {}
    for s in symbols:
        row = quotes.get(s) or {}
        exits[s] = {
            "bid": _best(row, "buy"),
            "ask": _best(row, "sell"),
            "last": row.get("last_price"),
            "at": at,
        }
    body = {
        "status": "ok",
        "session": day.isoformat(),
        "swept_at": at,
        "quote_source": _source(quotes),
        "exits": exits,
    }
    _write(root / day.isoformat() / "close.json", body)
    return body


# --- evening: reconcile ----------------------------------------------------------------------


@dataclass
class TradeResult:
    strategy: str
    symbol: str
    side: int
    backtest_bps: float
    """Official open to official close, gross: what the backtest books."""
    achievable_bps: float
    """Entry quote to exit quote, crossing the spread both times, gross."""
    slippage_bps: float
    """backtest_bps - achievable_bps: what the backtest's fills hide."""


def trade_result(
    strategy: str, p: Mapping[str, Any], exit_: Mapping[str, Any], close: float
) -> TradeResult | None:
    side = int(p["side"])
    entry = p.get("entry_quote")
    out = exit_.get("ask") if side < 0 else exit_.get("bid")
    if not entry or not out or not close or not p.get("official_open"):
        return None
    backtest = side * (close / p["official_open"] - 1.0) * 1e4
    achievable = side * (out / entry - 1.0) * 1e4
    return TradeResult(
        strategy,
        p["symbol"],
        side,
        round(backtest, 2),
        round(achievable, 2),
        round(backtest - achievable, 2),
    )


def reconcile(
    day: date, root: Path = ROOT, closes: Mapping[str, float] | None = None
) -> dict[str, Any]:
    """Join the two sweeps with the official close. `closes` defaults to the bhavcopy."""
    opened = _read(root / day.isoformat() / "open.json")
    closed = _read(root / day.isoformat() / "close.json")
    if opened.get("status") != "ok" or closed.get("status") != "ok":
        body = {"status": "incomplete", "open": opened.get("status"), "close": closed.get("status")}
        _write(root / day.isoformat() / "result.json", body)
        return body
    if closes is None:
        closes = official_closes(day)
    if not closes:
        return {"status": "waiting", "why": f"no bhavcopy close for {day} yet"}
    results: list[TradeResult] = []
    unpriced = []
    for b in opened["books"]:
        for p in b["picks"]:
            r = trade_result(
                b["strategy"], p, closed["exits"].get(p["symbol"], {}), closes.get(p["symbol"], 0.0)
            )
            if r is None:
                unpriced.append(p["symbol"])
            else:
                results.append(r)
    body = {
        "status": "ok",
        "session": day.isoformat(),
        "trades": [asdict(r) for r in results],
        "unpriced": unpriced,
        "seconds_after_open": opened.get("seconds_after_open"),
    }
    _write(root / day.isoformat() / "result.json", body)
    summarise(root)
    return body


def official_closes(day: date) -> dict[str, float]:
    from eulerlab.intraday import daily_universe_screen as du

    panel = du.load_panel(start=day, end=day)
    return {s: bars[day].close for s, bars in panel.items() if day in bars}


@dataclass
class Summary:
    strategy: str
    sessions: int = 0
    trades: int = 0
    median_slippage_bps: float | None = None
    mean_slippage_bps: float | None = None
    mean_backtest_bps: float | None = None
    mean_achievable_bps: float | None = None
    days: list[str] = field(default_factory=list)


def summarise(root: Path = ROOT) -> dict[str, Summary]:
    by: dict[str, list[dict[str, Any]]] = {}
    days: dict[str, set[str]] = {}
    for path in sorted(root.glob("*/result.json")):
        body = _read(path)
        if body.get("status") != "ok":
            continue
        for t in body["trades"]:
            by.setdefault(t["strategy"], []).append(t)
            days.setdefault(t["strategy"], set()).add(body["session"])
    out: dict[str, Summary] = {}
    for sid, rows in by.items():
        slip = [r["slippage_bps"] for r in rows]
        out[sid] = Summary(
            sid,
            sessions=len(days[sid]),
            trades=len(rows),
            median_slippage_bps=round(statistics.median(slip), 2),
            mean_slippage_bps=round(statistics.fmean(slip), 2),
            mean_backtest_bps=round(statistics.fmean(r["backtest_bps"] for r in rows), 2),
            mean_achievable_bps=round(statistics.fmean(r["achievable_bps"] for r in rows), 2),
            days=sorted(days[sid]),
        )
    _write(root / "summary.json", {k: asdict(v) for k, v in out.items()})
    return out


def read_summary(root: Path = ROOT) -> dict[str, dict[str, Any]]:
    body = _read(root / "summary.json")
    return {str(k): v for k, v in body.items() if isinstance(v, dict)}


def main(argv: Iterable[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Live-price paper for intraday books (ADR-153).")
    parser.add_argument("step", choices=("plan", "open", "close", "reconcile", "summary"))
    parser.add_argument("--day", default="", help="YYYY-MM-DD (default: today, IST)")
    args = parser.parse_args(list(argv) if argv is not None else None)
    day = date.fromisoformat(args.day) if args.day else _now_ist().date()
    if args.step == "plan":
        print(f"live-shadow: watchlist {plan()}")
        return 0
    if args.step == "open":
        body = open_session(day)
    elif args.step == "close":
        body = close_session(day)
    elif args.step == "reconcile":
        body = reconcile(day)
    else:
        for s in summarise().values():
            print(
                f"{s.strategy}: {s.sessions} sessions, {s.trades} trades, slippage median "
                f"{s.median_slippage_bps} bps, backtest {s.mean_backtest_bps} vs achievable "
                f"{s.mean_achievable_bps} bps a trade"
            )
        return 0
    print(f"live-shadow {args.step} {day}: {body.get('status')} {body.get('why', '')}".rstrip())
    return 0 if body.get("status") in ("ok", "waiting") else 1


if __name__ == "__main__":
    raise SystemExit(main())
