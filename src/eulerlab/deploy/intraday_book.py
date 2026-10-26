"""Paper trading for the minute-bar strategies: replay each session, trade forward.

The daily runner replays its engine from the deployment's start; the overnight
book replays its rule. This does the same for the intraday signals: each run
scans the strategy's adopted instrument through `paper_scan.scan_symbol`, the
scanner its backtests use, from the deployment's start to the newest minute
bar, and sends every leg of every bracket through the deployment's OMS. One
scanner, so a paper trade and a backtest trade are the same trade.

### The holdout (operator, 2026-10-17)

Research treats every minute bar after 2024-11-30 as the holdout, read once
(`mandate.yaml`). Paper trading reads new minute bars every day, so the
operator chose to end the holdout on a fixed date, `forward_evidence:
holdout_end` in `mandate.yaml`. Until that line exists nothing here runs, and
nothing on or before it is read, not even as indicator warmup: a signal that
needs more history simply rejects ("warmup") for its first sessions, counted
in the state, never hidden.

### Forward only

A deployment trades from the day after it was made. One created at 14:00
would otherwise "trade" that morning in hindsight.

### What is not here yet

Money moved in or out (flows are refused for these deployments); a strategy
with no adopted instrument (Tweezer Bottom); sizing on current equity rather
than the starting capital. Each is said where it would apply.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from eulerlab.backtest.events import Order, client_order_id
from eulerlab.costs.schedule import Side
from eulerlab.deploy import deployments as store
from eulerlab.deploy.deployments import Deployment
from eulerlab.filecache import FileMemo
from eulerlab.oms.killswitch import KillSwitchTripped
from eulerlab.oms.states import OrderState

WARMUP_DAYS = 30
"""Calendar days of history read before the start, never before the holdout end."""

MARKETS = {"equity": "INR", "us": "USD", "crypto": "USD"}
"""The adopted market of each intraday strategy, and the money it is counted in."""


def _mandate() -> dict[str, Any]:
    """`gates.load_mandate()`, parsed once per version of the file. The strategy
    table asked 52 times per request, 0.3 s of YAML (2026-10-27)."""
    global _MANDATE
    from eulerlab.gates import MANDATE_PATH, load_mandate

    if _MANDATE is None:
        _MANDATE = FileMemo(load_mandate, size=2)
    return _MANDATE(MANDATE_PATH)


_MANDATE: FileMemo[dict[str, Any]] | None = None


def holdout_end() -> date | None:
    """The operator's holdout end (`mandate.yaml: forward_evidence.holdout_end`), or None."""
    value = (_mandate().get("forward_evidence") or {}).get("holdout_end")
    if value is None:
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def instrument(strategy_id: str) -> tuple[str, str] | None:
    """(symbol, market) the strategy's library result was measured on, or None."""
    from eulerlab.intraday import adopted

    row = adopted.read().get(strategy_id) or {}
    symbol, market = row.get("symbol"), row.get("market")
    if not symbol or market not in MARKETS:
        return None
    return str(symbol), str(market)


def blocker(strategy_id: str) -> str:
    """Why this intraday strategy cannot paper-trade now, or ""."""
    if instrument(strategy_id) is None:
        return "it has no adopted instrument to trade (its library result names none)"
    if holdout_end() is None:
        return (
            "minute data after 2024-11-30 is the holdout. Paper trading needs "
            "`forward_evidence: holdout_end` in mandate.yaml (operator-owned) first"
        )
    return ""


def first_session(created: date, end: date) -> date:
    """The first day a new deployment trades: after both its creation and the holdout."""
    return max(created, end) + timedelta(days=1)


Scan = Callable[..., Any]


def replay(
    deployment: Deployment,
    oms: Any,
    *,
    symbol: str,
    market: str,
    through: date,
    end_of_holdout: date,
    traded_through: date | None,
    scan: Scan | None = None,
) -> dict[str, Any]:
    """Every trade from the start to `through`, through the OMS. Returns the book, or a halt."""
    from eulerlab.intraday import bracket, paper_scan

    if deployment.start <= end_of_holdout:
        return {"halt": f"starts {deployment.start}, inside the holdout (ends {end_of_holdout})"}
    read_from = max(
        deployment.start - timedelta(days=WARMUP_DAYS), end_of_holdout + timedelta(days=1)
    )
    scanned = (scan or paper_scan.scan_symbol)(
        deployment.strategy_id,
        symbol,
        start=read_from,
        end=through,
        equity=deployment.capital,
        asset_class=market,
    )

    equity = float(deployment.capital)
    costs = 0.0
    fills: list[dict[str, Any]] = []
    sent = 0
    by_day: dict[date, float] = {}

    def place(day: date, side: Side, quantity: int, price: float, seq: int) -> Any:
        nonlocal sent
        coid = client_order_id(deployment.strategy_id, day, symbol, seq)
        if oms.state(coid) is None:
            if traded_through is not None and day <= traded_through:
                return coid, "history"
            oms.submit(
                Order(
                    client_order_id=coid,
                    strategy_id=deployment.strategy_id,
                    signal_day=day,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                ),
                price=price,
            )
            sent += 1
        return coid, oms.adapter.query(coid)

    entered = [(t.entry_ts, t) for t in scanned.trades if t.entry_ts is not None]
    for entry_ts, trade in sorted(entered, key=lambda pair: pair[0]):
        day = entry_ts.date()
        if day < deployment.start or day > through:
            continue
        legs = [(Side.BUY, trade.plan.shares, trade.entry_price)]
        legs += [(Side.SELL, leg.shares, leg.price) for leg in trade.exits]
        cash = 0.0
        for seq, (side, quantity, price) in enumerate(legs):
            if quantity <= 0:
                continue
            coid, view = place(day, side, quantity, price, seq)
            if view == "history":
                return {
                    "halt": f"{day} now has a {symbol} trade that earlier runs did not make: "
                    f"the minute history changed. Nothing is sent for a past day"
                }
            if view is None or oms.state(coid) is not OrderState.FILLED:
                return {"halt": f"order {coid} is {oms.state(coid)}, not filled"}
            filled = float(view.average_price)
            charge = bracket._cost(filled, quantity, side, day, market)
            costs += charge
            cash += (-filled if side is Side.BUY else filled) * quantity - charge
            fills.append(
                {
                    "day": day.isoformat(),
                    "symbol": symbol,
                    "side": side.value,
                    "quantity": quantity,
                    "price": round(filled, 4),
                    "cost": round(charge, 2),
                }
            )
        by_day[day] = by_day.get(day, 0.0) + cash

    sessions = sorted(
        d for d in getattr(scanned, "_session_dates", []) if deployment.start <= d <= through
    )
    curve: list[list[Any]] = []
    for day in sessions:
        equity += by_day.get(day, 0.0)
        curve.append([day.isoformat(), round(equity, 2)])
    return {
        "days": sessions,
        "equity": equity,
        "costs": costs,
        "curve": curve,
        "fills": fills,
        "sent": sent,
        "rejections": dict(scanned.rejections),
        "held": oms.adapter.positions(),
    }


def run(deployment: Deployment) -> dict[str, Any]:
    """Bring one intraday deployment up to the newest minute bar. Returns the state written."""
    from eulerlab.deploy.runner import _halt, make_oms

    began = time.monotonic()
    previous = store.read_state(deployment) or {}
    traded_through = (
        date.fromisoformat(previous["traded_through"]) if previous.get("traded_through") else None
    )
    state: dict[str, Any] = {
        "deployment": deployment.id,
        "ran_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "traded_through": previous.get("traded_through"),
        "warnings": [],
    }
    oms = make_oms(deployment)
    if oms.kill_switch.is_tripped():
        reason = oms.kill_switch.reason()
        store.set_status(deployment, "halted", reason)
        state.update(status="halted", reason=reason)
        store.write_state(deployment, state)
        return state

    found, end = instrument(deployment.strategy_id), holdout_end()
    if found is None or end is None:
        state.update(status="waiting", reason=blocker(deployment.strategy_id))
        store.write_state(deployment, state)
        return state
    if deployment.flows:
        return _halt(
            deployment, oms, state, "intraday paper books do not take deposits or withdrawals yet"
        )
    symbol, market = found
    report = oms.recover()
    if not report.clean:
        return _halt(deployment, oms, state, f"orders still unresolved: {report.render()}")

    if market == "us":
        # The daily update lands US daily bars, not minute ones; fetch this
        # symbol's here, from the day after the holdout and never before it.
        from eulerlab.ingest import alpaca

        _, _, error = alpaca.land_minute(
            [symbol],
            start=max(
                deployment.start - timedelta(days=WARMUP_DAYS), end + timedelta(days=1)
            ).isoformat(),
        )
        if error:
            state["warnings"].append(f"{symbol} minute bars could not be fetched: {error}")
    # Up to yesterday: today's session is not over, and its bars are not all in.
    through = datetime.now(UTC).date() - timedelta(days=1)
    try:
        book = replay(
            deployment,
            oms,
            symbol=symbol,
            market=market,
            through=through,
            end_of_holdout=end,
            traded_through=traded_through,
        )
    except KillSwitchTripped as exc:
        return _halt(deployment, oms, state, f"kill switch: {exc}")
    if "halt" in book:
        return _halt(deployment, oms, state, str(book["halt"]))
    if book["held"]:
        return _halt(
            deployment, oms, state, f"flat at every close, yet the broker holds {book['held']}"
        )

    days: Sequence[date] = book["days"]
    if not days:
        state.update(
            status="waiting",
            reason=f"no {symbol} minute bars from {deployment.start} are in the data yet",
        )
        store.write_state(deployment, state)
        return state
    store.write_fills(deployment, book["fills"])
    state.update(
        status="ok",
        reason="",
        traded_through=days[-1].isoformat(),
        as_of=days[-1].isoformat(),
        capital=deployment.capital,
        invested=deployment.capital,
        currency=MARKETS[market],
        instrument={"symbol": symbol, "market": market},
        equity=round(book["equity"], 2),
        cash=round(book["equity"], 2),
        total_return=round(book["equity"] / deployment.capital - 1.0, 6),
        costs=round(book["costs"], 2),
        curve=book["curve"],
        book=[],
        fills=book["fills"][-200:],
        fills_total=len(book["fills"]),
        rejections=[
            {"day": "", "symbol": symbol, "reason": f"{k}: {v} bars"}
            for k, v in book["rejections"].items()
        ],
        sent_this_run=book["sent"],
        rebalance_every=1,
        next_rebalance=f"scans each {symbol} session's minute bars once they land; flat at every close",
        seconds=round(time.monotonic() - began),
    )
    store.write_state(deployment, state)
    return state
