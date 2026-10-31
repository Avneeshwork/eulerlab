"""Tell the operator what a deployed strategy just did, on Telegram.

The operator's request (2026-10-11): "setup telegram signals for paper / live
trading strategies like name of strategy and strategy actions". A deployment
used to act and say so only in its state file and on the Live & Risk page.

A message is sent when a run **does something or stops**:

- it placed orders — the strategy's name, each order (side, quantity, symbol,
  price), then equity, cash and the next rebalance;
- it halted or errored — the reason, once, when the status changes.

A run that only marks the book to a new close sends nothing. `notify.py`
states the rule this follows: a message every evening that nothing happened
trains the reader to ignore the channel that carries the one that matters.

Nothing here can stop a run. Delivery is best-effort through `notify.send`,
which never raises, and `announce` swallows everything else: a deployment that
traded must not be reported as failed because Telegram was unreachable.

`EULERLAB_TELEGRAM_SIGNALS=0` turns it off. The token and chat are the ones
already in `.env` (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`).

The same code serves a live deployment the day one is allowed (T-4022): the
header carries the mode, and nothing else differs.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any

from eulerlab import notify
from eulerlab.deploy.deployments import Deployment

MAX_LINES = 25
"""Orders listed in one message. A catch-up over many days can place more;
the rest are counted, and Telegram would reject a longer message anyway."""

STOPPED = frozenset({"halted", "error"})


def enabled() -> bool:
    return os.environ.get("EULERLAB_TELEGRAM_SIGNALS", "1") != "0" and notify.configured()


def title_of(strategy_id: str) -> str:
    """The strategy's library title, or its id when it has none."""
    from eulerlab.strategies import REGISTRY

    found = REGISTRY.get(strategy_id)
    return found.title if found else strategy_id


def new_fills(previous: Mapping[str, Any], state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Fills dated after the day the previous run had traded through.

    A run replays the deployment from its start, so `state["fills"]` holds
    every fill so far; only those on days the last run had not reached are
    this run's actions. Compared as ISO dates.
    """
    seen_through = str(previous.get("traded_through") or "")
    fills = state.get("fills") or []
    return [f for f in fills if isinstance(f, dict) and str(f.get("day", "")) > seen_through]


def _rupees(value: object) -> str:
    return f"₹{float(value):,.0f}" if isinstance(value, int | float) else "—"


def _order_line(fill: Mapping[str, Any]) -> str:
    side = str(fill.get("side", "")).upper()
    price = fill.get("price")
    at = f" @ {float(price):,.2f}" if isinstance(price, int | float) else ""
    return f"{side:<4} {fill.get('quantity')} {fill.get('symbol')}{at}"


def message(
    deployment: Deployment, previous: Mapping[str, Any], state: Mapping[str, Any]
) -> str | None:
    """The text to send for this run, or None when it did nothing worth a message."""
    header = (
        f"{deployment.mode.upper()} · {title_of(deployment.strategy_id)}\n"
        f"{deployment.id} · invested {_rupees(state.get('invested', deployment.capital))}"
    )
    status = str(state.get("status", ""))
    if status in STOPPED:
        if str(previous.get("status", "")) == status:
            return None  # already told
        reason = str(state.get("reason") or "no reason recorded").strip()
        return f"⚠️ {header}\n\n{status.upper()}: {reason[:600]}\nNothing more is sent until it is cleared."

    limit = state.get("loss_limit")
    went_reducing = isinstance(limit, Mapping) and limit.get("action") == "reducing"
    reducing_line = (
        f"⚠️ REDUCE-ONLY from the next session: down {float(limit.get('drawdown', 0)):.1%} "
        f"from its high. Sells go through; buys are refused until you resume it (ADR-092)."
        if went_reducing and isinstance(limit, Mapping)
        else ""
    )
    fills = new_fills(previous, state)
    if not fills:
        return f"{header}\n\n{reducing_line}" if reducing_line else None
    days = sorted({str(f.get("day")) for f in fills})
    when = days[0] if len(days) == 1 else f"{days[0]} to {days[-1]}"
    lines = [_order_line(f) for f in fills[:MAX_LINES]]
    if len(fills) > MAX_LINES:
        lines.append(f"… and {len(fills) - MAX_LINES} more")
    total = state.get("total_return")
    change = f" ({float(total):+.1%})" if isinstance(total, int | float) else ""
    book = state.get("book")
    holdings = f" · {len(book)} holdings" if isinstance(book, Sequence) else ""
    equity = state.get("equity")
    invested = state.get("invested", deployment.capital)
    gain = float(equity) - float(invested) if isinstance(equity, int | float) else None
    gain_text = f" · gain {_rupees(gain)}" if gain is not None else ""
    footer = (
        f"Equity {_rupees(equity)}{change}{gain_text} · cash {_rupees(state.get('cash'))}{holdings}"
    )
    upcoming = state.get("next_rebalance")
    if upcoming:
        footer += f"\nNext rebalance: {upcoming}"
    if reducing_line:
        footer += f"\n\n{reducing_line}"
    return f"{header}\n\nActions on {when} ({len(fills)}):\n" + "\n".join(lines) + f"\n\n{footer}"


def announce(
    deployment: Deployment, previous: Mapping[str, Any], state: Mapping[str, Any]
) -> notify.Delivery | None:
    """Send this run's message if there is one. Never raises."""
    try:
        if not enabled():
            return None
        text = message(deployment, previous, state)
        return notify.send(text) if text else None
    except Exception as exc:  # a notifier must not take the run down with it
        return notify.Delivery(False, f"{type(exc).__name__}: {exc}"[:200])
