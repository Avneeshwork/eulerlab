"""Paper trading for the research studies that share one shape (ADR-078, stage 2).

Thirteen study modules (twenty-two strategies) are built alike: `run_all`
loads minute days with `research_screen.load_days`, `_run` trades only inside
`EVAL_START <= day <= DATA_END`, and each run returns its `id` and every trade
in `trade_log`. So a deployment of one of them runs that module's own
`run_all`, unchanged, over the paper window and takes its run's trades: the
paper trade is the trade the study's backtest would have made.

The window is swapped, not rewritten: for the call, the module's `EVAL_START`
and `DATA_END` become the deployment's start and yesterday, and its loader is
wrapped so it opens no file starting on or before the holdout end
(`mandate.yaml`) and caches nothing. A lock keeps two paper runs from swapping
at once. The research code, and every result already recorded from it, is
untouched.

Each trade becomes two orders through the deployment's OMS: in at the study's
entry price, out at its exit, short trades selling first. Costs are NSE
intraday charges on the paper fill; the broker's slippage replaces the study's
assumed 2 bp.
"""

from __future__ import annotations

import importlib
import threading
import time
import types
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from types import ModuleType
from typing import Any

from eulerlab.backtest.events import Order, client_order_id
from eulerlab.costs.schedule import Side
from eulerlab.deploy import deployments as store
from eulerlab.deploy import intraday_book
from eulerlab.deploy.deployments import Deployment
from eulerlab.oms.killswitch import KillSwitchTripped
from eulerlab.oms.states import OrderState

MODULES = {
    "company_github_stock_strategies": "company_github_screen",
    "github_donchian_stock_strategies": "github_donchian_screen",
    "github_ema_crossover_stock_strategies": "github_ema_crossover_screen",
    "github_engulfing_stock_strategies": "github_engulfing_screen",
    "github_followup_stock_strategies": "github_followup_screen",
    "github_keltner_stock_strategies": "github_keltner_screen",
    "github_momentum_burst_stock_strategies": "github_momentum_burst_screen",
    "github_momentum_pullback_stock_strategies": "github_momentum_pullback_screen",
    "github_pivot_stock_strategies": "github_pivot_breakout_screen",
    "github_rsi2_pullback_stock_strategies": "github_rsi2_pullback_screen",
    "hikkake_stock_strategies": "hikkake_screen",
    "inside_bar_stock_strategies": "inside_bar_screen",
    "supertrend_alignment_stock_strategies": "supertrend_alignment_screen",
}
"""Study output name (`studies.py`'s `study`) to the module that computes it."""

FIVE = {
    "nse_overnight_intraday_reversal_decile": "overnight",
    "nse_stock_expiry_pin_to_max_oi_strike": "pinning",
    "nse_results_in_hours_follow_five_minutes": "earnings",
    "nse_nr7_opening_range_breakout": "nr7",
    "nse_delivery_spike_next_day_long": "delivery",
}
"""Research 112's five cross-sectional screens, run by `five_trades` instead."""

_SWAP = threading.Lock()


def module_of(strategy_id: str) -> str | None:
    """The study module behind one strategy card configuration, if it is one of these."""
    from eulerlab.strategies import studies

    if strategy_id in FIVE:
        return "india_five_screen"
    for entry in studies.ENTRIES:
        if (
            strategy_id in (entry.get("configurations") or {}).values()
            or entry["id"] == strategy_id
        ):
            return MODULES.get(str(entry.get("study")))
    return None


def blocker(strategy_id: str) -> str:
    """Why this study cannot paper-trade now, or ""."""
    if module_of(strategy_id) is None:
        return "its study is not one the paper book can run yet (ADR-078)"
    if intraday_book.holdout_end() is None:
        return (
            "minute data after 2024-11-30 is the holdout. Paper trading needs "
            "`forward_evidence: holdout_end` in mandate.yaml (operator-owned) first"
        )
    return ""


class _Loader:
    """The module's `research_screen`, with `load_days` held to the paper window."""

    def __init__(self, real: ModuleType, since: date, through: date) -> None:
        self._real, self._since, self._through = real, since, through
        self.sessions: set[date] = set()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)

    def load_days(self, symbol: str, **_: Any) -> list[Any]:
        days = self._real.load_days(symbol, cutoff=self._through, cache=False, since=self._since)
        self.sessions.update(day.day for day in days)
        return list(days)


@contextmanager
def _window(module: ModuleType, start: date, through: date, since: date) -> Iterator[_Loader]:
    names = ("EVAL_START", "DATA_END", "rs")
    with _SWAP:
        saved = {name: getattr(module, name) for name in names}
        loader = _Loader(saved["rs"], since, through)
        for name, value in zip(names, (start, through, loader), strict=True):
            setattr(module, name, value)
        try:
            yield loader
        finally:
            for name, value in saved.items():
                setattr(module, name, value)


def study_trades(
    strategy_id: str,
    *,
    start: date,
    through: date,
    since: date,
    capital: float,
    module: ModuleType | None = None,
) -> tuple[list[dict[str, Any]], list[date]]:
    """(this strategy's trades, the sessions loaded), from the study's own `run_all`.

    The study sizes for its own `CAPITAL`; quantities are scaled to the
    deployment's, rounded down to whole shares.
    """
    if module is None:
        name = module_of(strategy_id)
        if name is None:
            msg = f"{strategy_id} is not a study this book runs"
            raise KeyError(msg)
        module = importlib.import_module(f"eulerlab.intraday.{name}")
    with _window(module, start, through, since) as loader:
        result = module.run_all()
    runs = result.get("runs") or []
    run = next((r for r in runs if r.get("id") == strategy_id), runs[0] if len(runs) == 1 else None)
    if run is None:
        msg = f"{module.__name__} produced no run named {strategy_id}"
        raise KeyError(msg)
    notional = float(getattr(module, "NOTIONAL", 0.0))
    scale = capital / float(getattr(module, "CAPITAL", capital) or capital)
    trades = [normalise(t, notional) for t in run.get("trade_log") or []]
    for trade in trades:
        trade["quantity"] = int(trade["quantity"] * scale)
    return trades, sorted(loader.sessions)


def five_trades(
    strategy_id: str, *, start: date, through: date, since: date, capital: float
) -> tuple[list[dict[str, Any]], list[date]]:
    """One research-112 screen over every F&O stock, from its own extract and evaluate.

    Every trade, not the 2,000 the report keeps: the screen's `cs.report` is
    swapped for one that records what it is handed.
    """
    from eulerlab.ingest import nse_earnings_announcements as announcements
    from eulerlab.intraday import cross_section as cs
    from eulerlab.intraday import delivery_spike_screen as delivery
    from eulerlab.intraday import earnings_reaction_screen as earnings
    from eulerlab.intraday import expiry_pinning_screen as pinning
    from eulerlab.intraday import nr7_breakout_screen as nr7
    from eulerlab.intraday import overnight_reversal_screen as overnight

    screen = FIVE[strategy_id]
    symbols = cs.universe()
    modules: dict[str, ModuleType] = {
        "overnight": overnight,
        "pinning": pinning,
        "earnings": earnings,
        "nr7": nr7,
        "delivery": delivery,
    }
    extract: cs.Extractor
    if screen == "pinning":
        extract = pinning.extractor(pinning.context(symbols, start, through))
    elif screen == "earnings":
        extract = earnings.extractor(earnings.events(announcements.load()))
    elif screen == "delivery":
        # Daily delivery figures, not minute bars: a month before the start is
        # the 20-session baseline the rule compares against.
        extract = delivery.extractor(delivery.context(symbols, start - timedelta(days=45), through))
    else:
        extract = modules[screen].extract
    marks, sessions = cs.scan(symbols, {screen: extract}, cutoff=through, since=since)
    window = [day for day in sessions if start <= day <= through]
    kept: list[cs.Trade] = []
    module = modules[screen]

    def recording(run_id: str, trades: Any, days: Any, **kwargs: Any) -> dict[str, Any]:
        kept.extend(trades)
        return {}

    shim = types.SimpleNamespace(**{k: getattr(cs, k) for k in dir(cs) if not k.startswith("__")})
    shim.report = recording
    with _SWAP:
        real = getattr(module, "cs")  # noqa: B009 - swapped and put back below
        setattr(module, "cs", shim)  # noqa: B010
        try:
            module.evaluate(marks[screen], window)
        finally:
            setattr(module, "cs", real)  # noqa: B010
    scale = capital / cs.CAPITAL
    return [
        {
            "symbol": t.symbol,
            "day": t.day,
            "direction": t.direction,
            "quantity": int(t.quantity * scale),
            "entry": t.entry,
            "exit": t.exit,
            "minute": t.entry_minute,
        }
        for t in kept
    ], window


def normalise(trade: dict[str, Any], notional: float = 0.0) -> dict[str, Any]:
    """symbol, day, direction (+1/-1), quantity, entry, exit, entry minute: one shape for all."""
    raw = trade.get("side", trade.get("direction", 1))
    direction = -1 if raw in ("short", "sell", -1) else 1
    entry, exit_ = float(trade["entry"]), float(trade["exit"])
    quantity = trade.get("quantity")
    if quantity is None:
        moved = exit_ - entry
        gross = float(trade.get("gross_pnl") or 0.0)
        # Every study sizes whole shares, so gross = direction * moved * quantity.
        quantity = round(abs(gross / moved)) if moved else (int(notional / entry) if entry else 0)
    return {
        "symbol": str(trade["symbol"]),
        "day": date.fromisoformat(str(trade["day"])),
        "direction": direction,
        "quantity": int(quantity),
        "entry": entry,
        "exit": exit_,
        "minute": int(trade.get("entry_minute") or 0),
    }


def replay(
    deployment: Deployment,
    oms: Any,
    *,
    trades: list[dict[str, Any]],
    sessions: list[date],
    through: date,
    traded_through: date | None,
) -> dict[str, Any]:
    """Each trade's two legs through the OMS, then equity by session. Or a halt."""
    from eulerlab.intraday import india_papers as ip

    equity, costs, sent = float(deployment.capital), 0.0, 0
    fills: list[dict[str, Any]] = []
    by_day: dict[date, float] = defaultdict(float)
    counted: dict[tuple[date, str], int] = defaultdict(int)
    taken = sorted(
        (t for t in trades if deployment.start <= t["day"] <= through and t["quantity"] > 0),
        key=lambda t: (t["day"], t["symbol"], t["minute"]),
    )
    for trade in taken:
        day, symbol, quantity = trade["day"], trade["symbol"], trade["quantity"]
        k = counted[(day, symbol)]
        counted[(day, symbol)] += 1
        opening = Side.BUY if trade["direction"] > 0 else Side.SELL
        closing = Side.SELL if opening is Side.BUY else Side.BUY
        for seq, side, price in (
            (2 * k, opening, trade["entry"]),
            (2 * k + 1, closing, trade["exit"]),
        ):
            coid = client_order_id(deployment.strategy_id, day, symbol, seq)
            if oms.state(coid) is None:
                if traded_through is not None and day <= traded_through:
                    return {
                        "halt": f"{day} now has a {symbol} trade that earlier runs did not make: "
                        f"the minute history changed. Nothing is sent for a past day"
                    }
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
            view = oms.adapter.query(coid)
            if view is None or oms.state(coid) is not OrderState.FILLED:
                return {"halt": f"order {coid} is {oms.state(coid)}, not filled"}
            filled = float(view.average_price)
            # A delivery (CNC) position, e.g. H-0162's 20-day hold, pays delivery
            # charges; everything else here is intraday (ADR-149).
            if trade.get("segment") == "delivery":
                from eulerlab.intraday import other_data_screen as od

                charge = od.delivery_fee(filled, quantity, side, day)
            else:
                charge = ip.stock_cost(filled, quantity, side, day)
            costs += charge
            by_day[day] += (-filled if side is Side.BUY else filled) * quantity - charge
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
    days = [d for d in sessions if deployment.start <= d <= through]
    curve: list[list[Any]] = []
    for day in days:
        equity += by_day.get(day, 0.0)
        curve.append([day.isoformat(), round(equity, 2)])
    return {
        "days": days,
        "equity": equity,
        "costs": costs,
        "curve": curve,
        "fills": fills,
        "sent": sent,
        "held": oms.adapter.positions(),
    }


def run(
    deployment: Deployment,
    *,
    trades_for: Callable[..., Any] | None = None,
    block: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Bring one study deployment up to yesterday's minute bars. Returns the state written."""
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
    end = intraday_book.holdout_end()
    if (why := (block or blocker)(deployment.strategy_id)) or end is None:
        state.update(status="waiting", reason=why)
        store.write_state(deployment, state)
        return state
    if deployment.flows:
        return _halt(
            deployment, oms, state, "study paper books do not take deposits or withdrawals yet"
        )
    if deployment.start <= end:
        return _halt(
            deployment, oms, state, f"starts {deployment.start}, inside the holdout (ends {end})"
        )
    report = oms.recover()
    if not report.clean:
        return _halt(deployment, oms, state, f"orders still unresolved: {report.render()}")

    through = datetime.now(UTC).date() - timedelta(days=1)
    try:
        chosen = trades_for or (five_trades if deployment.strategy_id in FIVE else study_trades)
        trades, sessions = chosen(
            deployment.strategy_id,
            start=deployment.start,
            through=through,
            since=end,
            capital=deployment.capital,
        )
    except Exception as exc:  # a study that cannot run on this window says why, and waits
        state.update(
            status="waiting", reason=f"the study did not run: {type(exc).__name__}: {exc}"[:400]
        )
        store.write_state(deployment, state)
        return state
    try:
        book = replay(
            deployment,
            oms,
            trades=trades,
            sessions=sessions,
            through=through,
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
    if not book["days"]:
        state.update(
            status="waiting", reason=f"no minute bars from {deployment.start} are in the data yet"
        )
        store.write_state(deployment, state)
        return state
    store.write_fills(deployment, book["fills"])
    state.update(
        status="ok",
        reason="",
        traded_through=book["days"][-1].isoformat(),
        as_of=book["days"][-1].isoformat(),
        capital=deployment.capital,
        invested=deployment.capital,
        currency="INR",
        equity=round(book["equity"], 2),
        cash=round(book["equity"], 2),
        total_return=round(book["equity"] / deployment.capital - 1.0, 6),
        costs=round(book["costs"], 2),
        curve=book["curve"],
        book=[],
        fills=book["fills"][-200:],
        fills_total=len(book["fills"]),
        rejections=[],
        sent_this_run=book["sent"],
        rebalance_every=1,
        next_rebalance="runs the study over each session's minute bars once they land; flat at every close",
        seconds=round(time.monotonic() - began),
    )
    store.write_state(deployment, state)
    return state
