"""A paper book for the Nifty overnight strategy (ADR-066, T-4048).

`nifty_calm_rise_overnight` buys the near-month Nifty future at the close of a
day that was GREEN with VIX down, and sells at the next open. Deployments
replay a `Strategy` through the equity engine, which fills once a day at the
close; a position that opens at one close and shuts at the next open has no
place in it, so this strategy could be studied and not deployed.

This is its own runner, and only that. Everything that makes a deployment a
deployment is the same code the equity books use:

- orders go through the same `OMS`, journal and paper broker (`runner.make_oms`),
  with the same deterministic ids, so a replay can never send twice;
- the same kill switch stops it, and the same halt is written when the book
  and the broker disagree;
- the state file has the same fields, so the same screen and the same Telegram
  messages read it.

### The rule, and where it comes from

The signal is `gap_forecast.predict(Model.JOINT, day) == UP`, the function the
study and the pre-close message use. The contract is the nearest expiry after
the signal day. The exit is that contract's open on the next stored day.

### Sizing

Whole lots, one times the book's equity in notional: `floor(equity / (lot x
price))`. That is the study's own assumption (its returns are on notional, not
on margin), so no margin rate is assumed here. It also means a book smaller
than one lot's notional, about 15 lakh rupees in October 2026, never trades,
and says so on every signal night.

The lot size is read from the signal day's F&O bhavcopy. It is a time-versioned
contract field (`CLAUDE.md`) and is never written here: a night whose lot size
cannot be read is skipped with the reason, not sized with a guess.

### What a fill is

The close and the next open as the exchange published them, moved against the
book by the deployment's slippage. The replay runs after the data lands, so
the fill is not an order that was really working at 15:29 (A-046 covers the
study; the same caveat holds here).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from eulerlab.backtest.events import Order, client_order_id
from eulerlab.costs.schedule import Side
from eulerlab.deploy import deployments as store
from eulerlab.deploy.deployments import Deployment
from eulerlab.oms.killswitch import KillSwitchTripped
from eulerlab.oms.states import OrderState
from eulerlab.research import gap_forecast as gf

STRATEGIES = frozenset({gf.CALM_RISE_ID})
"""Strategy ids this runner trades."""

UNDERLYING = "NIFTY"

LotLookup = Callable[[date, str], int | None]


def symbol_of(expiry: str) -> str:
    """The book's name for one futures contract."""
    return f"{UNDERLYING}-FUT-{expiry}"


def lot_size(day: date, expiry: str) -> int | None:
    """The Nifty future's lot size on `day`, from that day's F&O bhavcopy."""
    from eulerlab.ingest import landing_reader
    from eulerlab.master.derivatives import ContractType
    from eulerlab.options.chain import quotes_from_fo_bhavcopy

    pattern = f"{day:%Y}/{day:%m}/{day.isoformat()}_udiff.zip"
    found = landing_reader.available("fo", pattern)
    if not found:
        return None
    for quote in quotes_from_fo_bhavcopy(landing_reader.read(found[0]), UNDERLYING):
        if (
            quote.contract_type is ContractType.FUTURE
            and quote.expiry.isoformat() == expiry
            and quote.lot_size
        ):
            return int(quote.lot_size)
    return None


def cost(day: date, side: Side, price: float, quantity: int) -> float:
    """Charges on one futures leg, in rupees, at the rates in force that day."""
    from eulerlab.costs.model import cost_of_trade
    from eulerlab.costs.schedule import Segment

    return float(
        cost_of_trade(
            trade_date=day,
            segment=Segment.FUTURES,
            side=side,
            price=Decimal(str(round(price, 4))),
            quantity=quantity,
        ).total
    )


def contract_for(contracts: dict[str, dict[str, Any]], day: str) -> tuple[str, float] | None:
    """The nearest contract expiring after `day` that traded, and its close."""
    for expiry in sorted(contracts):
        if expiry > day and contracts[expiry].get("c"):
            return expiry, float(contracts[expiry]["c"])
    return None


def replay(
    deployment: Deployment,
    oms: Any,
    *,
    sessions: list[gf.Day],
    futures: list[dict[str, Any]],
    lots: LotLookup,
    traded_through: date | None,
    cash_flows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Walk the days since the deployment started. Returns the book, or a halt.

    Pure of the filesystem apart from `oms`, which is where the orders go.
    """
    signal = {s.day for s in sessions if gf.predict(gf.Model.JOINT, s) == gf.UP}
    known_days = {s.day for s in sessions}
    stored = {date.fromisoformat(str(f["d"])): f["contracts"] for f in futures}
    # Only days both sources hold. A future day without its index row cannot
    # be judged yet, and judging it later would mean trading in the past.
    days = sorted(d for d in stored if d in known_days and d >= deployment.start)

    equity = float(deployment.capital)
    costs = 0.0
    curve: list[list[Any]] = []
    fills: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    held: dict[str, int] = {}
    position: dict[str, Any] | None = None
    sent = 0
    applied_flows: list[dict[str, Any]] = []
    applied_flow_keys: set[tuple[str, str]] = set()

    def record(day: date, side: Side, symbol: str, quantity: int, price: float) -> float:
        nonlocal costs
        charge = cost(day, side, price, quantity)
        costs += charge
        fills.append(
            {
                "day": day.isoformat(),
                "symbol": symbol,
                "side": side.value,
                "quantity": quantity,
                "price": round(price, 2),
                "cost": round(charge, 2),
            }
        )
        return charge

    def place(
        order_day: date, side: Side, symbol: str, quantity: int, price: float, seq: int
    ) -> Any:
        """Submit once; return the broker's own record of the order."""
        nonlocal sent
        coid = client_order_id(deployment.strategy_id, order_day, symbol, seq)
        if oms.state(coid) is None:
            oms.submit(
                Order(
                    client_order_id=coid,
                    strategy_id=deployment.strategy_id,
                    signal_day=order_day,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                ),
                price=price,
            )
            sent += 1
        return coid, oms.adapter.query(coid)

    for day in days:
        # --- the morning: close what last night opened --------------------------
        if position is not None:
            contract = stored[day].get(position["expiry"]) or {}
            opened = contract.get("o")
            if not opened:
                return {
                    "halt": f"{position['symbol']} has no opening price on {day}; "
                    f"the position bought on {position['day']} cannot be closed"
                }
            coid, view = place(
                position["day"],
                Side.SELL,
                position["symbol"],
                position["quantity"],
                float(opened),
                1,
            )
            if view is None or oms.state(coid) is not OrderState.FILLED:
                return {"halt": f"the exit order {coid} is {oms.state(coid)}, not filled"}
            charge = record(
                day, Side.SELL, position["symbol"], position["quantity"], view.average_price
            )
            equity += position["quantity"] * (view.average_price - position["price"]) - charge
            held.pop(position["symbol"], None)
            position = None

        # A flow takes effect on the first close after the last decision it
        # records. The prior overnight position has already settled at open.
        pre_flow_equity = equity
        due_flows = [
            flow
            for flow in (cash_flows or [])
            if str(flow.get("last_decided", "")) < day.isoformat()
            and (str(flow.get("entered_at", "")), str(flow.get("last_decided", "")))
            not in applied_flow_keys
        ]
        flow_amount = sum(float(flow.get("amount", 0.0)) for flow in due_flows)
        if equity + flow_amount < 1_000.0:
            return {"halt": "cash flow would leave less than ₹1,000 in the overnight book"}
        equity += flow_amount

        # --- the close: open tonight's, if the day signals ----------------------
        if day in signal:
            chosen = contract_for(stored[day], day.isoformat())
            if chosen is None:
                rejections.append(
                    {"day": day.isoformat(), "symbol": UNDERLYING, "reason": "no future traded"}
                )
            else:
                expiry, close = chosen
                symbol = symbol_of(expiry)
                coid = client_order_id(deployment.strategy_id, day, symbol, 0)
                quantity = 0
                if oms.state(coid) is None:
                    if traded_through is not None and day <= traded_through:
                        return {
                            "halt": f"{day} now signals a trade but was already traded through "
                            f"without one: the history changed. Nothing is sent for a past day"
                        }
                    lot = lots(day, expiry)
                    if not lot:
                        rejections.append(
                            {
                                "day": day.isoformat(),
                                "symbol": symbol,
                                "reason": "lot size not found in that day's F&O file",
                            }
                        )
                    else:
                        quantity = int(equity // (lot * close)) * lot
                        if quantity <= 0:
                            rejections.append(
                                {
                                    "day": day.isoformat(),
                                    "symbol": symbol,
                                    "reason": f"capital too small: one lot of {lot} is "
                                    f"₹{lot * close:,.0f} and the book has ₹{equity:,.0f}",
                                }
                            )
                if quantity > 0 or oms.state(coid) is not None:
                    coid, view = place(day, Side.BUY, symbol, quantity, close, 0)
                    if view is not None and oms.state(coid) is OrderState.FILLED:
                        bought = int(view.filled_quantity)
                        charge = record(day, Side.BUY, symbol, bought, view.average_price)
                        equity -= charge
                        held[symbol] = bought
                        position = {
                            "day": day,
                            "symbol": symbol,
                            "expiry": expiry,
                            "quantity": bought,
                            "price": view.average_price,
                            "close": close,
                        }
                    else:
                        rejections.append(
                            {
                                "day": day.isoformat(),
                                "symbol": symbol,
                                "reason": f"order {oms.state(coid)}",
                            }
                        )
        curve.append([day.isoformat(), round(equity, 2)])
        for flow in due_flows:
            key = (str(flow.get("entered_at", "")), str(flow.get("last_decided", "")))
            applied_flow_keys.add(key)
            applied_flows.append(
                {
                    "amount": float(flow.get("amount", 0.0)),
                    "last_decided": str(flow.get("last_decided", "")),
                    "entered_at": str(flow.get("entered_at", "")),
                    "decision_day": day,
                    "applied_day": day,
                    "pre_flow_equity": pre_flow_equity,
                }
            )

    return {
        "days": days,
        "equity": equity,
        "costs": costs,
        "curve": curve,
        "fills": fills,
        "rejections": rejections,
        "held": held,
        "position": position,
        "sent": sent,
        "signal_today": bool(days) and days[-1] in signal,
        "flows": applied_flows,
    }


def run(deployment: Deployment) -> dict[str, Any]:
    """Bring one overnight deployment up to the latest data. Returns the state written."""
    from eulerlab.deploy.runner import _halt, freshness, make_oms
    from eulerlab.market_history import NIFTY_FUTURES, _stored_days
    from eulerlab.research.gap_forecast_run import load_days

    began = time.monotonic()
    previous = store.read_state(deployment) or {}
    traded_through = (
        date.fromisoformat(previous["traded_through"]) if previous.get("traded_through") else None
    )
    oms = make_oms(deployment)
    warnings: list[str] = []
    state: dict[str, Any] = {
        "deployment": deployment.id,
        "ran_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "traded_through": previous.get("traded_through"),
        "warnings": warnings,
    }

    if oms.kill_switch.is_tripped():
        reason = oms.kill_switch.reason()
        store.set_status(deployment, "halted", reason)
        state.update(status="halted", reason=reason, book=previous.get("book"))
        store.write_state(deployment, state)
        return state

    report = oms.recover()
    if not report.clean:
        return _halt(deployment, oms, state, f"orders still unresolved: {report.render()}")

    try:
        book = replay(
            deployment,
            oms,
            sessions=load_days(),
            futures=sorted(_stored_days(NIFTY_FUTURES), key=lambda d: str(d["d"])),
            lots=lot_size,
            traded_through=traded_through,
            cash_flows=deployment.flows,
        )
    except KillSwitchTripped as exc:
        return _halt(deployment, oms, state, f"kill switch: {exc}")
    if "halt" in book:
        return _halt(deployment, oms, state, str(book["halt"]))

    oms.resolve_unknown()
    if oms.unresolved():
        return _halt(deployment, oms, state, f"orders in UNKNOWN: {', '.join(oms.unresolved())}")
    at_broker = oms.adapter.positions()
    if book["held"] != at_broker:
        diff = sorted(set(book["held"].items()) ^ set(at_broker.items()))
        return _halt(deployment, oms, state, f"book and broker disagree: {diff[:6]}")

    days: list[date] = book["days"]
    if not days:
        state.update(
            status="waiting",
            panel_through="",
            reason=f"no session on or after {deployment.start} is in the data yet",
        )
        if stale := freshness(deployment.start):
            warnings.append(stale)
        store.write_state(deployment, state)
        return state

    equity, position = float(book["equity"]), book["position"]
    curve = [list(point) for point in book["curve"]]
    rows = []
    if position is not None:
        # An open position is marked at the close it was bought on. The fill
        # is that close moved by slippage, so the book starts the night down
        # by the slippage, which is what it would cost to get out.
        equity += position["quantity"] * (position["close"] - position["price"])
        curve[-1][1] = round(equity, 2)
        value = position["quantity"] * position["close"]
        rows.append(
            {
                "symbol": position["symbol"],
                "quantity": position["quantity"],
                "average_price": round(position["price"], 2),
                "last_price": round(position["close"], 2),
                # A future's notional, not money paid: the book's cash is untouched.
                "value": round(value, 2),
                "weight": round(value / equity, 4) if equity else 0.0,
                "last_traded": position["day"].isoformat(),
            }
        )
    if stale := freshness(days[-1]):
        warnings.append(stale)
    applied_flows = [
        {**flow, "decision_day": flow["decision_day"].isoformat()} for flow in book["flows"]
    ]
    applied_keys = {
        (str(flow.get("entered_at", "")), str(flow.get("last_decided", "")))
        for flow in applied_flows
    }
    pending_flows = [
        flow
        for flow in deployment.flows
        if (str(flow.get("entered_at", "")), str(flow.get("last_decided", ""))) not in applied_keys
    ]
    invested = deployment.capital + sum(float(flow["amount"]) for flow in applied_flows)
    flow_by_day: dict[str, tuple[float, float]] = {}
    for flow in applied_flows:
        flow_day = str(flow["decision_day"])
        amount, before = flow_by_day.get(flow_day, (0.0, float(flow["pre_flow_equity"])))
        flow_by_day[flow_day] = (amount + float(flow["amount"]), before)
    twr = 1.0
    previous_equity = deployment.capital
    for day, value in book["curve"]:
        flow_period = flow_by_day.get(str(day))
        if flow_period:
            amount, before_flow = flow_period
            if previous_equity > 0 and before_flow > 0:
                twr *= before_flow / previous_equity
            if before_flow + amount > 0:
                twr *= float(value) / (before_flow + amount)
        elif previous_equity > 0:
            twr *= float(value) / previous_equity
        previous_equity = float(value)
    state.update(
        status="ok",
        reason="",
        traded_through=days[-1].isoformat(),
        as_of=days[-1].isoformat(),
        last_decided=days[-1].isoformat(),
        capital=deployment.capital,
        invested=round(invested, 2),
        flows=applied_flows,
        pending=pending_flows,
        equity=round(equity, 2),
        cash=round(equity, 2),
        total_return=round(twr - 1.0, 6),
        costs=round(float(book["costs"]), 2),
        curve=curve,
        book=rows,
        fills=book["fills"][-200:],
        fills_total=len(book["fills"]),
        rejections=book["rejections"][-50:],
        sent_this_run=book["sent"],
        rebalance_every=1,
        next_rebalance=(
            f"holding {position['symbol']} overnight; sold at the next open"
            if position is not None
            else "decided at each close: buys only after a GREEN day with VIX down"
        ),
        intended={
            "wanted": 1 if book["signal_today"] else 0,
            "affordable": 1 if position is not None else 0,
            "names": [position["symbol"]] if position is not None else [],
            "cut": [] if position is not None or not book["signal_today"] else [UNDERLYING],
        },
        seconds=round(time.monotonic() - began),
    )
    store.write_state(deployment, state)
    return state
