"""Angel One: a read-only check, live quotes, and a supervised one-share proof (ADR-154).

    make angel-readonly                 log in (TOTP, no browser), read profile, funds,
                                        order book, positions, a quote and the intraday
                                        list; send nothing; write data/oms/angel_readonly.json
    make angel-proof SYMBOL=SBIN CONFIRM=SEND
                                        the operator, at the screen: buy 1 share MIS at
                                        market, wait for the fill, sell it back; write
                                        data/oms/angel_proof.json (what readiness reads)

**Why Angel as well as Kite.** Kite's token dies at 06:00 and its login needs a
person at Zerodha's page every morning (`broker/kite_session.py`). Angel One's
SmartAPI logs in with a PIN and a TOTP seed already in `.env`, so a 09:16 job
can log itself in. `deploy/live_shadow.py` uses Angel's quotes when no fresh
Kite session exists.

**What is checked against what.** The SDK methods and routes here
(`generateSession`, `getProfile`, `rmsLimit`, `orderBook`, `position`,
`getMarketData`, `searchScrip`, `nseIntraday`) were read from the installed
`smartapi-python` 1.5.5 source on 2026-11-08 (`SmartApi/smartConnect.py`). The
shape of `getMarketData`'s FULL reply and its 50-token limit are from memory of
Angel's docs, not fetched (A-127): `angel-readonly` records the real reply, and
the parser refuses a reply it does not recognise rather than guessing.

**The proof sends real orders**, so it refuses unless `CONFIRM=SEND` is given,
the kill switch is not tripped, it is a weekday between 09:20 and 15:00 IST,
and the symbol resolves to one NSE equity token. The order ids are deterministic
(`hash(strategy, time, instrument, seq)`), as CLAUDE.md requires.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

READONLY_FILE = Path("data/oms/angel_readonly.json")
PROOF_FILE = Path("data/oms/angel_proof.json")
TOKENS_FILE = Path("data/master/angel_nse_tokens.json")
QUOTE_BATCH = 50
# ASSUMPTION: A-127 — getMarketData takes at most 50 tokens a request and its FULL
# reply is {"data": {"fetched": [{tradingSymbol, symbolToken, ltp, open, close,
# depth: {buy: [{price, quantity}], sell: [...]}}]}}; checked by angel-readonly.
IST = timedelta(hours=5, minutes=30)


class AngelError(RuntimeError):
    pass


def _env(name: str) -> str:
    from eulerlab import quotes

    value = quotes._env(name)
    if not value:
        msg = f"{name} is not set in .env"
        raise AngelError(msg)
    return value


def login() -> tuple[Any, str]:
    """(SmartConnect client, refresh token). Nothing is written to disk."""
    try:
        import logzero
        import pyotp
        from SmartApi import SmartConnect
    except ImportError as exc:
        msg = f"Angel One SDK not installed: {exc}"
        raise AngelError(msg) from exc
    logzero.logger.disabled = True
    client = SmartConnect(_env("ANGEL_API_KEY"))
    session = client.generateSession(
        _env("ANGEL_CLIENT_CODE"),
        _env("ANGEL_PIN"),
        pyotp.TOTP(_env("ANGEL_TOTP_SECRET")).now(),
    )
    if not isinstance(session, dict) or session.get("status") is not True:
        detail = session.get("message", "login failed") if isinstance(session, dict) else "?"
        msg = f"Angel One login failed: {detail}"
        raise AngelError(msg)
    data = session.get("data") or {}
    return client, str(data.get("refreshToken") or "")


# --- symbols to tokens --------------------------------------------------------------------


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _load_tokens(path: Path = TOKENS_FILE) -> dict[str, str]:
    return {str(k): str(v) for k, v in (_read(path).get("tokens") or {}).items()}


def _save_tokens(
    tokens: Mapping[str, str], path: Path = TOKENS_FILE, *, master_at: str | None = None
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body: dict[str, Any] = {
        "tokens": dict(sorted(tokens.items())),
        "at": datetime.now(UTC).isoformat(),
    }
    kept = master_at if master_at is not None else _read(path).get("master_at")
    if kept:
        body["master_at"] = kept
    path.write_text(json.dumps(body, indent=1), encoding="utf-8")


SCRIP_MASTER = (
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
)
"""Angel One's public instrument list (no login), about 38 MB and 162,000 rows,
fetched 2026-11-09. NSE cash lines are `exch_seg == "NSE"` with a `-EQ` (or `-BE`)
suffix on `symbol`; 2,776 `-EQ` lines on that day."""

MASTER_MAX_AGE = timedelta(hours=20)
"""Re-read the scrip master once a day: listings and renames change daily."""

SEARCH_LIMIT = 5
"""Symbols still searched one by one after the master. `searchScrip` answered
"exceeding access rate" after a handful of calls on 2026-11-09, so a universe of
two thousand names cannot be resolved that way."""


def download_master(timeout: float = 90.0) -> list[dict[str, Any]]:
    """The scrip master rows. Read-only, public, not stored raw (it is a lookup)."""
    import urllib.request

    request = urllib.request.Request(SCRIP_MASTER, headers={"User-Agent": "eulerlab"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        rows = json.loads(response.read().decode("utf-8"))
    if not isinstance(rows, list):
        msg = "Angel scrip master is not a list"
        raise AngelError(msg)
    return [r for r in rows if isinstance(r, dict)]


def master_tokens(rows: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """NSE cash symbol -> token. The `-EQ` line wins over `-BE` for the same name."""
    eq: dict[str, str] = {}
    be: dict[str, str] = {}
    for row in rows:
        if row.get("exch_seg") != "NSE":
            continue
        name = str(row.get("symbol") or "")
        token = str(row.get("token") or "")
        if not token:
            continue
        if name.endswith("-EQ"):
            eq[name[:-3]] = token
        elif name.endswith("-BE"):
            be[name[:-3]] = token
    return {**be, **eq}


def _master_stale(path: Path, now: datetime) -> bool:
    stamp = _read(path).get("master_at")
    if not stamp:
        return True
    try:
        return now - datetime.fromisoformat(str(stamp)) > MASTER_MAX_AGE
    except ValueError:
        return True


def token_for(client: Any, symbol: str) -> str | None:
    """The NSE cash token for `symbol` (its `-EQ` line), by SmartAPI's scrip search."""
    reply = client.searchScrip("NSE", symbol)
    rows = (reply or {}).get("data") or [] if isinstance(reply, dict) else []
    wanted = f"{symbol}-EQ"
    for row in rows:
        if isinstance(row, dict) and row.get("tradingsymbol") == wanted:
            return str(row.get("symboltoken"))
    return None


def tokens_for(
    client: Any,
    symbols: Sequence[str],
    *,
    pause: float = 1.1,
    path: Path | None = None,
    master: Callable[[], Sequence[Mapping[str, Any]]] | None = download_master,
) -> dict[str, str]:
    """Cached tokens. Unknown symbols come from the scrip master (re-read at most
    once a day), then at most SEARCH_LIMIT of what is left from `searchScrip`."""
    path = path or TOKENS_FILE
    known = _load_tokens(path)
    missing = [s for s in symbols if s not in known]
    changed = False
    now = datetime.now(UTC)
    if missing and master is not None and _master_stale(path, now):
        known.update(master_tokens(master()))
        _save_tokens(known, path, master_at=now.isoformat())
        missing = [s for s in symbols if s not in known]
    for s in missing[:SEARCH_LIMIT]:
        found = token_for(client, s)
        if found:
            known[s] = found
            changed = True
        if pause:
            time.sleep(pause)
    if changed:
        _save_tokens(known, path)
    return {s: known[s] for s in symbols if s in known}


# --- quotes ------------------------------------------------------------------------------


def to_kite_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """An Angel FULL quote in the shape `live_shadow` reads from Kite."""

    def levels(side: str) -> list[dict[str, float]]:
        out = []
        for level in ((row.get("depth") or {}).get(side)) or []:
            if isinstance(level, dict) and isinstance(level.get("price"), (int, float)):
                out.append({"price": float(level["price"]), "quantity": level.get("quantity", 0)})
        return out

    return {
        "last_price": row.get("ltp"),
        "ohlc": {"open": row.get("open"), "close": row.get("close")},
        "depth": {"buy": levels("buy"), "sell": levels("sell")},
        "source": "angel",
        "exchange_time": row.get("exchFeedTime"),
    }


def parse_quotes(reply: Any, by_token: Mapping[str, str]) -> dict[str, dict[str, Any]]:
    if not isinstance(reply, dict) or reply.get("status") is not True:
        message = reply.get("message") if isinstance(reply, dict) else type(reply).__name__
        msg = f"Angel quote refused: {message}"
        raise AngelError(msg)
    fetched = (reply.get("data") or {}).get("fetched")
    if not isinstance(fetched, list):
        msg = "Angel quote reply has no data.fetched list (A-127): shape not recognised"
        raise AngelError(msg)
    out: dict[str, dict[str, Any]] = {}
    for row in fetched:
        if not isinstance(row, dict):
            continue
        symbol = by_token.get(str(row.get("symbolToken")))
        if symbol:
            out[symbol] = to_kite_row(row)
    return out


# ASSUMPTION: A-130 — SmartAPI quote calls are limited to roughly 10 a second;
# from memory of Angel's rate-limit table, not fetched.
QUOTE_PAUSE = 0.12
"""Seconds between `getMarketData` batches, to stay under about ten a second."""


def quotes(
    symbols: list[str],
    client: Any | None = None,
    *,
    mode: str = "FULL",
    pause: float = QUOTE_PAUSE,
    master: Callable[[], Sequence[Mapping[str, Any]]] | None = download_master,
) -> dict[str, dict[str, Any]]:
    """Quotes for NSE cash symbols, keyed by symbol. Read-only.

    `mode="FULL"` carries depth (what live_shadow needs); `"OHLC"` is the same
    row without depth, enough for a last price and the previous close."""
    if client is None:
        client, _ = login()
    tokens = tokens_for(client, symbols, master=master)
    by_token = {t: s for s, t in tokens.items()}
    out: dict[str, dict[str, Any]] = {}
    ids = list(by_token)
    sent = 0.0
    for i in range(0, len(ids), QUOTE_BATCH):
        wait = pause - (time.monotonic() - sent)
        if i and wait > 0:  # only the part of the pause the request did not use
            time.sleep(wait)
        sent = time.monotonic()
        reply = client.getMarketData(mode, {"NSE": ids[i : i + QUOTE_BATCH]})
        out.update(parse_quotes(reply, by_token))
    return out


# --- the read-only check -------------------------------------------------------------------


def _count(reply: Any) -> int | str:
    if not isinstance(reply, dict):
        return f"unexpected {type(reply).__name__}"
    if reply.get("status") is not True:
        return f"refused: {reply.get('message')}"
    data = reply.get("data")
    return len(data) if isinstance(data, list) else 0


def readonly(
    client: Any, refresh: str, symbol: str = "SBIN", path: Path = READONLY_FILE
) -> dict[str, Any]:
    """Every read the order path needs, no send. Secrets never reach the file."""
    profile = client.getProfile(refresh)
    funds = client.rmsLimit()
    report: dict[str, Any] = {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "login": "ok",
        "profile": "ok"
        if isinstance(profile, dict) and profile.get("status") is True
        else f"refused: {profile}",
        "funds_available": ((funds or {}).get("data") or {}).get("availablecash")
        if isinstance(funds, dict)
        else None,
        "open_orders": _count(client.orderBook()),
        "positions": _count(client.position()),
    }
    try:
        quote = quotes([symbol], client)
        report["quote"] = quote.get(symbol) or "no quote returned"
    except AngelError as exc:
        report["quote"] = str(exc)
    try:
        intraday = client.nseIntraday()
        data = intraday.get("data") if isinstance(intraday, dict) else None
        report["nse_intraday_list"] = {
            "count": len(data) if isinstance(data, list) else None,
            "sample": data[:3] if isinstance(data, list) else intraday,
        }
    except Exception as exc:  # an endpoint the account may not have
        report["nse_intraday_list"] = f"{type(exc).__name__}: {str(exc)[:120]}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report


# --- the supervised proof -----------------------------------------------------------------


def client_order_id(strategy: str, at: datetime, instrument: str, seq: int) -> str:
    """CLAUDE.md: hash(strategy_id, signal_time, instrument_id, seq)."""
    raw = f"{strategy}|{at.isoformat()}|{instrument}|{seq}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def refuse(confirm: str, now_ist: datetime, tripped: bool) -> str:
    """Why the proof must not send, or '' when it may."""
    if confirm != "SEND":
        return "give CONFIRM=SEND: this places a real buy and a real sell of 1 share"
    if tripped:
        return "the kill switch is tripped"
    if now_ist.weekday() >= 5:
        return "not a weekday"
    minutes = now_ist.hour * 60 + now_ist.minute
    if not 9 * 60 + 20 <= minutes <= 15 * 60:
        return "only between 09:20 and 15:00 IST, away from the open and the square-off"
    return ""


DONE = ("complete", "rejected", "cancelled")
"""`broker/smartapi._view` statuses that end an order's life."""


def _wait_fill(broker: Any, coid: str, timeout: float = 30.0, step: float = 1.0) -> Any:
    deadline = time.monotonic() + timeout
    view = None
    while time.monotonic() < deadline:
        view = broker.query(coid)
        if view is not None and str(getattr(view, "status", "")).lower() in DONE:
            return view
        time.sleep(step)
    return view


def proof(
    symbol: str,
    confirm: str,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    path: Path = PROOF_FILE,
    tripped: Callable[[], bool] | None = None,
    connect: Callable[[], tuple[Any, str]] = login,
    make_broker: Callable[[Any, Mapping[str, str]], Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Buy 1 share MIS at market, wait for the fill, sell it back. Real money."""
    from eulerlab.backtest.events import Order
    from eulerlab.costs.schedule import Side

    if tripped is None:
        from eulerlab.oms.killswitch import KillSwitch

        tripped = KillSwitch().is_tripped
    if make_broker is None:
        from eulerlab.broker.smartapi import SmartAPIBroker

        def make_broker(client: Any, tokens: Mapping[str, str]) -> Any:
            return SmartAPIBroker(client, symbol_tokens=tokens, product_type="INTRADAY")

    at = now()
    why = refuse(confirm, at + IST, tripped())
    if why:
        return {"status": "refused", "why": why}
    client, _ = connect()
    token = token_for(client, symbol)
    if not token:
        return {"status": "refused", "why": f"no NSE equity token for {symbol}"}
    broker = make_broker(client, {symbol: token})
    day = (at + IST).date()
    legs: list[dict[str, Any]] = []
    for seq, side in enumerate((Side.BUY, Side.SELL)):
        if tripped():  # the operator may trip it between the legs
            break
        coid = client_order_id("angel-proof", at, symbol, seq)
        order = Order(
            client_order_id=coid,
            strategy_id="angel-proof",
            signal_day=day,
            symbol=symbol,
            side=side,
            quantity=1,
        )
        broker_id = broker.place(order)
        view = _wait_fill(broker, coid, timeout)
        status = str(getattr(view, "status", "unknown")).lower()
        legs.append(
            {
                "side": side.value,
                "client_order_id": coid,
                "broker_order_id": broker_id,
                "status": status,
                "filled": getattr(view, "filled_quantity", None),
                "average_price": getattr(view, "average_price", None),
                "reason": getattr(view, "reason", ""),
            }
        )
        if status != "complete":
            break
    ok = len(legs) == 2 and all(x["status"] == "complete" for x in legs)
    if ok:
        status = "ok"
    elif legs and legs[0]["status"] == "complete":
        status = "incomplete: 1 share is still held MIS; sell it in the Angel app now"
    else:
        status = "incomplete: check the Angel order book now"
    body = {
        "status": status,
        "broker": "angel",
        "symbol": symbol,
        "at": at.isoformat(timespec="seconds"),
        "what": f"1 {symbol} bought and sold back MIS through Angel One SmartAPI",
        "legs": legs,
    }
    if ok:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    return body


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Angel One checks (ADR-154).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    ro = sub.add_parser("readonly")
    ro.add_argument("--symbol", default="SBIN")
    pr = sub.add_parser("proof")
    pr.add_argument("--symbol", required=True)
    pr.add_argument("--confirm", default="")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "readonly":
            client, refresh = login()
            report = readonly(client, refresh, args.symbol)
            print(json.dumps(report, indent=2, default=str))
            return 0
        body = proof(args.symbol, args.confirm)
    except AngelError as exc:
        print(f"angel: {exc}")
        return 1
    print(json.dumps(body, indent=2, default=str))
    return 0 if body["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
