"""`make paper-daily` — bring every active deployment up to the latest close.

### How a day is traded

There is no second trading loop. Each run replays the deployment from its
start date to the latest panel day through `event_driven.run` — the engine the
backtest uses — with an `OMSExecutor` routing every order through the OMS to
the deployment's broker. Client order ids are deterministic, and `OMS.submit`
returns an order it has already journalled without sending it again, so the
replayed days re-read their recorded fills and only the newest day sends
anything. That gives three properties for free:

- **Catch-up.** A Mac that was off for three days runs once and trades the
  three missed days in order. Nothing is skipped and nothing is sent twice.
- **Same as the backtest.** Decide on day *t*'s close, fill at day *t+1*'s
  price — the timing the backtest uses and the timing a live order placed near
  the next close would get.
- **The capital is yours.** `fit_capital` keeps the top-ranked names the money
  can buy (`deploy.sizing`), and nothing else differs from the backtest except
  the paper broker's slippage and a 1% cash buffer for costs.

### Fallbacks — every one stops the deployment rather than guessing

- **Kill switch tripped** → nothing runs.
- **Orders in UNKNOWN** → resolved by asking the broker before anything else
  (`OMS.recover`); still unresolved afterwards → halt.
- **History changed** → a replayed day wants an order the journal never saw
  (the panel was revised after the order was placed) → halt, send nothing.
- **Book ≠ broker** → the engine's holdings and the broker's positions differ
  → halt. The broker is the source of truth.
- **Stale data** → the panel is behind the calendar. Not a halt: no new day
  exists to trade, so nothing is sent. Reported on the page.

A halt trips the deployment's own kill switch. Clearing it is the operator's
action (`make kill-reset` against that folder), never automatic.
"""

from __future__ import annotations

import argparse
import time
import traceback
from collections.abc import Collection, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from eulerlab.backtest import event_driven
from eulerlab.backtest.events import Fill, Order, Rejection
from eulerlab.deploy import deployments as store
from eulerlab.deploy.deployments import Deployment
from eulerlab.deploy.sizing import fit_to_capital
from eulerlab.features.panel import PanelRow, by_symbol, trading_days
from eulerlab.oms import ems
from eulerlab.oms.journal import Journal
from eulerlab.oms.killswitch import KillSwitch, KillSwitchTripped
from eulerlab.oms.oms import OMS
from eulerlab.oms.paper_broker import PaperBroker
from eulerlab.paper.runner import OMSExecutor

GROSS = 0.99
"""Invested share of equity. Costs are paid in cash on top of each buy; at
1.0 the last buy of a rebalance can find the account short, which a broker
rejects and a backtest does not."""

HISTORY_BUFFER = 400
"""Trading days loaded before the start, for lookbacks and the liquidity rank."""


class HistoryChanged(RuntimeError):
    """A replayed, already-traded day produced an order the journal never saw."""


class ForwardExecutor(OMSExecutor):
    """`OMSExecutor`, refusing to send for a day that has already been traded."""

    def __init__(self, oms: OMS, *, traded_through: date | None, **kwargs: Any) -> None:
        super().__init__(oms, **kwargs)
        self.traded_through = traded_through
        self.sent_today: list[str] = []

    def execute(self, order: Order, *, day: date, price: float | None) -> Fill | Rejection:
        known = self.oms.state(order.client_order_id) is not None
        if (
            not known
            and price is not None
            and price > 0
            and self.traded_through is not None
            and day <= self.traded_through
        ):
            msg = (
                f"{order.symbol} {order.side.value} {order.quantity} for {day} was never "
                f"placed, but {day} has already been traded. The data changed after the "
                f"fact; sending it now would be a trade nobody decided."
            )
            raise HistoryChanged(msg)
        if not known and price is not None and price > 0:
            self.sent_today.append(order.client_order_id)
        return super().execute(order, day=day, price=price)


def make_oms(deployment: Deployment) -> OMS:
    if deployment.mode != "paper":
        msg = "live deployments are not enabled (T-3336, and no live limits are set)"
        raise RuntimeError(msg)
    folder = deployment.folder
    folder.mkdir(parents=True, exist_ok=True)
    return OMS(
        PaperBroker(folder / "paper_broker.json", slippage_bps=deployment.slippage_bps),
        journal=Journal(folder / "orders.jsonl"),
        governor=ems.Governor(),
        kill_switch=KillSwitch(folder / "KILL_SWITCH", folder / "killswitch_log.jsonl"),
    )


def _rows_for(rows: Sequence[PanelRow], start: date) -> tuple[list[PanelRow], int]:
    days = trading_days(rows)
    first = next((i for i, d in enumerate(days) if d >= start), len(days))
    since = days[max(0, first - HISTORY_BUFFER)]
    kept = [r for r in rows if r.day >= since]
    kept_days = trading_days(kept)
    warmup = next((i for i, d in enumerate(kept_days) if d >= start), len(kept_days))
    return kept, warmup


def raw_closes(rows: Sequence[PanelRow]) -> dict[str, dict[date, float]]:
    out: dict[str, dict[date, float]] = {}
    for row in rows:
        out.setdefault(row.symbol, {})[row.day] = row.close
    return out


def _business_days_between(a: date, b: date) -> int:
    count, day = 0, a
    while day < b:
        day += timedelta(days=1)
        if day.weekday() < 5:
            count += 1
    return count


def freshness(last_day: date, now: datetime | None = None) -> str:
    """Empty when the panel is current; otherwise what is behind and by how much.

    The day's bhavcopy lands after the close, so before 19:00 IST the latest
    expected day is the previous weekday. Holidays are not known in advance
    here (T-3998), so a holiday reads as one day behind.
    """
    now = now or datetime.now(UTC)
    ist = now + timedelta(hours=5, minutes=30)
    expected = ist.date() if ist.hour >= 19 else ist.date() - timedelta(days=1)
    while expected.weekday() >= 5:
        expected -= timedelta(days=1)
    behind = _business_days_between(last_day, expected)
    if behind <= 0:
        return ""
    return (
        f"the price panel ends {last_day}, {behind} trading day(s) behind {expected}. "
        f"Run `make daily` to land and build the missing days; until then there is "
        f"no new close to trade on."
    )


def paper_blocker(strategy_id: str) -> str:
    """Why paper trading cannot run this strategy, or "" when it can.

    The one rule the strategy list's Deploy button, the preflight and the
    deploy route all read, so none can offer what another refuses: until
    2026-10-17 the preflight passed `buy_and_hold`, which the route rejected.
    """
    from eulerlab.backtest.published import BUILDERS
    from eulerlab.deploy import overnight
    from eulerlab.strategies import REGISTRY

    declaration = REGISTRY.get(strategy_id)
    if declaration is None:
        return f"no strategy named {strategy_id!r}"
    if strategy_id in overnight.STRATEGIES:
        return ""
    from eulerlab.deploy import intraday_book
    from eulerlab.intraday.paper_scan import ALL_SIGNALS

    if strategy_id in ALL_SIGNALS:
        # Minute-bar signals trade through their own book (`intraday_book`).
        return intraday_book.blocker(strategy_id)
    from eulerlab.deploy import study_book

    if study_book.module_of(strategy_id) is not None:
        return study_book.blocker(strategy_id)
    if not declaration.is_strategy_subclass:
        # The intraday book covers the coded minute-bar signals. Research
        # studies, Tweezer Bottom and the option structures each run through
        # their own code, which is not yet wired to a paper book (ADR-078).
        return (
            "its engine is not wired to paper trading yet: research studies, Tweezer "
            "Bottom and option structures are the next stages (ADR-078)"
        )
    if strategy_id == "buy_and_hold":
        return "it is the engine's control, kept to be compared against, not traded"
    if strategy_id not in BUILDERS:
        return "it has no builder the paper runner can construct"
    return ""


def _strategy(strategy_id: str) -> Any:
    from eulerlab.backtest.published import BUILDERS

    builder = BUILDERS.get(strategy_id)
    if builder is None:
        msg = f"no builder for {strategy_id!r}"
        raise KeyError(msg)
    return builder()


def run(deployment: Deployment, rows: Sequence[PanelRow]) -> dict[str, Any]:
    """Bring one deployment up to the latest close. Returns the state written.

    Then tell the operator what it did (`deploy/signals.py`): the strategy's
    name and its orders when it traded, or the reason when it halted. Every
    route to a run comes through here — `make paper-daily`, the auto-updater
    and the Run now button — so none of them can act silently.
    """
    from eulerlab.deploy import overnight, signals

    previous = store.read_state(deployment) or {}
    # The overnight future has its own book (ADR-066): the equity engine fills
    # once a day at the close and cannot hold from one close to the next open.
    # Same OMS, journal, kill switch and state file either way.
    from eulerlab.deploy import intraday_book, study_book
    from eulerlab.intraday.paper_scan import ALL_SIGNALS

    if deployment.strategy_id in overnight.STRATEGIES:
        state = overnight.run(deployment)
    elif deployment.strategy_id in ALL_SIGNALS:
        state = intraday_book.run(deployment)
    elif study_book.module_of(deployment.strategy_id) is not None:
        state = study_book.run(deployment)
    else:
        state = _run(deployment, rows)
    signals.announce(deployment, previous, state)
    return state


def _run(deployment: Deployment, rows: Sequence[PanelRow]) -> dict[str, Any]:
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

    kept, warmup = _rows_for(rows, deployment.start)
    days = trading_days(kept)
    # The engine needs two sessions after the start before it runs at all
    # (`event_driven.run` returns nothing for `len(days) <= warmup + 2`).
    if not days or len(days) <= warmup + 2:
        state.update(
            status="waiting",
            # The panel day this run saw, so the auto-updater replays a waiting
            # book only once the panel has moved (deploy/autoupdate.py).
            panel_through=days[-1].isoformat() if days else "",
            reason=(
                f"the first decision is {deployment.start}'s close; it trades once the "
                f"panel holds two sessions after it"
            ),
        )
        if stale := freshness(days[-1] if days else deployment.start):
            warnings.append(stale)
        store.write_state(deployment, state)
        return state

    strategy = _strategy(deployment.strategy_id)
    executor = ForwardExecutor(
        oms,
        traded_through=traded_through,
        asset_class="equity",
        fund_symbols=frozenset(r.symbol for r in kept if r.isin.startswith("INF")),
    )
    try:
        result = event_driven.run(
            kept,
            strategy,
            asset_class="equity",
            starting_cash=deployment.capital,
            cash_flows=deployment.flows,
            rebalance_every=int(getattr(strategy, "rebalance_every", 21)),
            gross_cap=GROSS,
            warmup=warmup,
            # Raw closes for money, not back-adjusted ones. A back-adjusted
            # series is rebuilt whenever a new corporate action lands, which
            # would re-size days already traded and halt the replay. Signals
            # still see point-in-time adjusted history. STUB S-038: a split on
            # a held name reads as a loss until the paper broker applies it.
            adjusted_index=raw_closes(kept),
            executor=executor,
            fit_capital=True,
        )
    except HistoryChanged as exc:
        return _halt(deployment, oms, state, str(exc))
    except KillSwitchTripped as exc:
        return _halt(deployment, oms, state, f"kill switch: {exc}")

    oms.resolve_unknown()
    if oms.unresolved():
        return _halt(deployment, oms, state, f"orders in UNKNOWN: {', '.join(oms.unresolved())}")

    portfolio = result.portfolio
    held = portfolio.holdings() if portfolio else {}
    at_broker = oms.adapter.positions()
    if held != at_broker:
        diff = sorted(set(held.items()) ^ set(at_broker.items()))
        return _halt(deployment, oms, state, f"book and broker disagree: {diff[:6]}")

    marks = result.final_marks
    equity = result.equity[-1] if result.equity else deployment.capital
    histories = by_symbol([r for r in kept if r.symbol in held])
    book = []
    for symbol, quantity in sorted(held.items()):
        price = marks.get(symbol, 0.0)
        position = portfolio.positions.get(symbol) if portfolio else None
        book.append(
            {
                "symbol": symbol,
                "quantity": quantity,
                "average_price": round(position.average_price(), 2) if position else None,
                "last_price": round(price, 2),
                "value": round(quantity * price, 2),
                "weight": round(quantity * price / equity, 4) if equity else 0.0,
                "last_traded": histories[symbol][-1].day.isoformat()
                if histories.get(symbol)
                else None,
            }
        )

    rebalance = int(getattr(strategy, "rebalance_every", 21))
    last_index = len(days) - 1
    since = last_index - warmup
    next_decision = days[last_index] if since % rebalance == 0 else None
    sessions_to_next = 0 if next_decision else rebalance - since % rebalance

    # What the next rebalance would hold, sized to today's equity: the cut is
    # the part of the sizing an operator most needs to see before it happens.
    intended = _intended(strategy, kept, days[-1], equity)

    fills = [
        {
            "day": f.day.isoformat(),
            "symbol": f.symbol,
            "side": f.side.value,
            "quantity": f.quantity,
            "price": round(f.price, 2),
            "cost": round(f.cost, 2),
        }
        for f in result.fills
    ]
    if stale := freshness(days[-1]):
        warnings.append(stale)
    applied_flows: list[dict[str, Any]] = []
    for flow in result.applied_flows:
        decision_day, fill_day = flow.get("decision_day"), flow.get("fill_day")
        if not isinstance(decision_day, date) or not isinstance(fill_day, date):
            continue
        applied_flows.append(
            {
                **flow,
                "decision_day": decision_day.isoformat(),
                "applied_day": fill_day.isoformat(),
            }
        )
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
    state.update(
        status="ok",
        reason="",
        traded_through=result.days[-1].isoformat() if result.days else None,
        as_of=days[-1].isoformat(),
        last_decided=days[-2].isoformat() if len(days) > 1 else deployment.start.isoformat(),
        capital=deployment.capital,
        invested=round(invested, 2),
        flows=applied_flows,
        pending=pending_flows,
        equity=round(equity, 2),
        cash=round(portfolio.cash, 2) if portfolio else deployment.capital,
        total_return=round(result.total_return, 6),
        costs=round(result.total_cost, 2),
        curve=[
            [d.isoformat(), round(v, 2)] for d, v in zip(result.days, result.equity, strict=True)
        ],
        book=book,
        fills=fills[-200:],
        fills_total=len(fills),
        rejections=[
            {"day": r.day.isoformat(), "symbol": r.symbol, "reason": r.reason}
            for r in result.rejections[-50:]
        ],
        sent_this_run=len(executor.sent_today),
        rebalance_every=rebalance,
        next_rebalance=(
            f"decided on {days[-1]}'s close, filled at the next session's close"
            if next_decision
            else f"in {sessions_to_next} session(s)"
        ),
        intended=intended,
        seconds=round(time.monotonic() - began),
    )
    store.write_fills(deployment, fills)
    store.write_state(deployment, state)
    return state


def _intended(strategy: Any, rows: Sequence[PanelRow], day: date, equity: float) -> dict[str, Any]:
    """The names the strategy wants on `day`, and how many the money can buy."""
    from eulerlab.backtest.strategy import MarketView, normalise

    lookback = int(getattr(strategy, "lookback", 0) or 0)
    histories = by_symbol(rows)
    view_history = {s: (h[-lookback:] if lookback else h) for s, h in histories.items()}
    try:
        targets = normalise(
            strategy.target_weights(MarketView(as_of=day, history=view_history)), gross_cap=GROSS
        )
    except Exception as exc:  # a preview must never fail the run
        return {"error": str(exc)}
    closes = {s: h[-1].close for s, h in histories.items() if h and h[-1].day == day}
    fitted = fit_to_capital(targets, equity * GROSS, closes.get)
    return {
        "wanted": len(targets),
        "affordable": len(fitted),
        "names": list(fitted),
        "cut": [s for s in targets if s not in fitted],
        "note": "point-in-time prices are not split-adjusted here; a preview, not an order",
    }


def _halt(deployment: Deployment, oms: OMS, state: dict[str, Any], reason: str) -> dict[str, Any]:
    oms.kill_switch.trip(reason, by="deploy.runner")
    store.set_status(deployment, "halted", reason)
    state.update(status="halted", reason=reason)
    store.write_state(deployment, state)
    return state


def run_all(only: str | Collection[str] = "") -> int:
    from eulerlab.ingest.filelock import exclusive

    # Two runners replaying the same deployment would race on its journal and
    # state file; the second waits, then finds nothing new to send.
    with exclusive("paper_daily"):
        return _run_all(only)


def _run_all(only: str | Collection[str]) -> int:
    from eulerlab.features.panel import read_panel

    # One id, several (the auto-updater passes the books that are behind, so
    # the panel is read once for all of them), or every active book.
    wanted = {only} if isinstance(only, str) and only else set(only) if only else set()
    active = [
        d
        for d in store.all_deployments()
        if d.status == "active" and d.mode == "paper" and (not wanted or d.id in wanted)
    ]
    if not active:
        print("no active paper deployments")
        return 0
    rows = read_panel()
    worst = 0
    for deployment in active:
        print(f"{deployment.id} ...", flush=True)
        try:
            state = run(deployment, rows)
        except Exception:  # one deployment's failure must not stop the others
            detail = traceback.format_exc(limit=3)
            store.write_state(
                deployment,
                {
                    "deployment": deployment.id,
                    "ran_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "status": "error",
                    "reason": detail,
                    **{
                        k: v
                        for k, v in (store.read_state(deployment) or {}).items()
                        if k in {"book", "curve", "equity", "traded_through", "capital"}
                    },
                },
            )
            print(detail)
            worst = 1
            continue
        print(
            f"   {state['status']}: equity {state.get('equity')} through "
            f"{state.get('traded_through')}, sent {state.get('sent_this_run', 0)} "
            f"{state.get('reason') or ''}"
        )
        for warning in state.get("warnings", []):
            print(f"   warning: {warning}")
        if state["status"] == "halted":
            worst = 1
    return worst


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="paper-daily")
    parser.add_argument("--only", default="", help="one deployment id")
    args = parser.parse_args(argv)
    return run_all(args.only)


if __name__ == "__main__":
    raise SystemExit(main())
