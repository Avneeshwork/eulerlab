"""The trade desk: every order a deployment is about to make, as a ticket you can read and approve (ADR-087).

One ticket per active deployment, built from what its runner already wrote:
what it holds now (`state.book`) and what its strategy wants at the next
rebalance (`state.intended`). Each ticket lists the sells and buys, an
estimated cost, the reason (the strategy and its rebalance day), and the
pre-trade checks as pass or block:

| check | blocks when |
|---|---|
| kill switch | the global switch or the deployment's own is tripped |
| data | the price panel is below its quality grade, or behind |
| version lock | the strategy's code changed since it was deployed |
| position size | any one buy would exceed `max_position_notional` |
| order rate | never blocks; says how many one-second batches the governor needs |

**What approving does.** For a paper deployment, it records the decision and
nothing else: paper books keep trading on their own, as before. For a live
deployment — not enabled yet (T-4022) — the runner refuses to send a day's
orders until that day's ticket is approved (`approved_today`), so a live order
can only follow a click on a ticket the operator read.

**Estimates, said so.** Sell quantities come from the book. A buy is shown as
its target value, because the engine sets the quantity at the fill price; the
cost is the platform's cost model applied to that value.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
APPROVALS = Path("data/desk/approvals.jsonl")
GROSS = 0.99
ROUND_TRIP_COST = 0.0025
"""Delivery round trip as a share of value: 0.1% STT each side plus exchange,
stamp and GST, rounded up. ASSUMPTION A-068: an estimate for the ticket only;
fills pay the itemised model in `costs/`."""

Decision = Literal["approved", "rejected"]


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class Ticket:
    id: str
    deployment: str
    strategy: str
    mode: str
    rebalance: str
    equity: float
    sells: list[dict[str, Any]] = field(default_factory=list)
    buys: list[dict[str, Any]] = field(default_factory=list)
    holds: list[str] = field(default_factory=list)
    est_cost: float = 0.0
    checks: list[Check] = field(default_factory=list)
    reason: str = ""
    decision: str = ""

    @property
    def blocked(self) -> bool:
        return any(not c.ok for c in self.checks)

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["blocked"] = self.blocked
        return out


def _ticket_id(deployment: str, rebalance: str, sells: list[str], buys: list[str]) -> str:
    material = f"{deployment}|{rebalance}|{','.join(sorted(sells))}|{','.join(sorted(buys))}"
    return "t-" + hashlib.sha256(material.encode()).hexdigest()[:12]


def build(
    deployment: Any,
    state: dict[str, Any],
    *,
    tripped: str = "",
    data_ok: tuple[bool, str] = (True, "not checked"),
    lock: tuple[bool, str] = (True, "not checked"),
    max_notional: float = float("inf"),
    max_per_second: int = 5,
) -> Ticket:
    held = {
        str(r["symbol"]): r
        for r in state.get("book") or []
        if r.get("symbol") and float(r.get("value") or 0) != 0
    }
    intended = state.get("intended") or {}
    wanted = [str(s) for s in intended.get("names") or []]
    equity = float(state.get("equity") or deployment.capital)
    per_name = equity * GROSS / len(wanted) if wanted else 0.0
    sells: list[dict[str, Any]] = [
        {
            "symbol": s,
            "quantity": float(r.get("quantity") or 0),
            "value": round(float(r.get("value") or 0), 2),
        }
        for s, r in sorted(held.items())
        if s not in wanted
    ]
    buys: list[dict[str, Any]] = [
        {"symbol": s, "target_value": round(per_name, 2)} for s in wanted if s not in held
    ]
    traded = sum(x["value"] for x in sells) + sum(x["target_value"] for x in buys)
    rebalance = str(state.get("next_rebalance") or "")
    checks = [
        Check("kill switch", not tripped, tripped or "not tripped"),
        Check("data", data_ok[0], data_ok[1]),
        Check("version lock", lock[0], lock[1]),
        Check(
            "position size",
            all(x["target_value"] <= max_notional for x in buys),
            f"largest buy {max((x['target_value'] for x in buys), default=0):,.0f} against a limit of {max_notional:,.0f}",
        ),
        Check(
            "order rate",
            True,
            f"{len(sells) + len(buys)} orders, {-(-(len(sells) + len(buys)) // max(max_per_second, 1))} one-second batches at {max_per_second}/s",
        ),
    ]
    return Ticket(
        id=_ticket_id(
            deployment.id, rebalance, [x["symbol"] for x in sells], [x["symbol"] for x in buys]
        ),
        deployment=deployment.id,
        strategy=deployment.strategy_id,
        mode=deployment.mode,
        rebalance=rebalance,
        equity=round(equity, 2),
        sells=sells,
        buys=buys,
        holds=sorted(s for s in held if s in wanted),
        est_cost=round(traded * ROUND_TRIP_COST / 2, 2),
        checks=checks,
        reason=(
            f"{deployment.strategy_id} rebalances on {rebalance or 'its next day'}; "
            f"{intended.get('wanted', len(wanted))} names wanted, {intended.get('affordable', len(wanted))} affordable"
            + (
                f", left out for capital: {', '.join(intended.get('cut') or [])}"
                if intended.get("cut")
                else ""
            )
        ),
    )


def decisions(path: Path | None = None) -> dict[str, dict[str, Any]]:
    path = path or APPROVALS
    out: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            out[str(row["ticket"])] = row
    return out


def decide(
    ticket: Ticket, decision: Decision, note: str = "", path: Path | None = None
) -> dict[str, Any]:
    path = path or APPROVALS
    if decision == "approved" and ticket.blocked:
        failed = ", ".join(c.name for c in ticket.checks if not c.ok)
        msg = f"ticket {ticket.id} is blocked by: {failed}. Fix those first."
        raise ValueError(msg)
    if ticket.id in decisions(path):
        msg = f"ticket {ticket.id} was already decided"
        raise ValueError(msg)
    row = {
        "ticket": ticket.id,
        "deployment": ticket.deployment,
        "mode": ticket.mode,
        "rebalance": ticket.rebalance,
        "decision": decision,
        "note": note.strip()[:300],
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "ist_day": datetime.now(UTC).astimezone(IST).date().isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")
    return row


def approved_today(
    deployment_id: str, *, now: datetime | None = None, path: Path | None = None
) -> bool:
    """Whether today's (IST) ticket for this deployment was approved."""
    day = (now or datetime.now(UTC)).astimezone(IST).date().isoformat()
    return any(
        row.get("deployment") == deployment_id
        and row.get("decision") == "approved"
        and row.get("ist_day") == day
        for row in decisions(path).values()
    )


def data_check(panel: dict[str, Any] | None) -> tuple[bool, str]:
    """The ticket's data row, from the price panel's saved grade.

    A blocked row used to read "price panel grade D, ok", which looks like a
    contradiction: "ok" is the freshness. It now says what the grade needs and
    the first check that failed.
    """
    if panel is None:
        return True, "no grade saved yet; run make data-quality"
    fresh = str(panel.get("freshness"))
    ok = bool(panel.get("usable")) and fresh in ("ok", "behind", "unknown")
    if ok:
        return True, f"price panel grade {panel.get('grade')}, {fresh}"
    failed = [
        str(c.get("detail"))
        for c in panel.get("checks") or []
        if isinstance(c, dict) and c.get("state") == "fail"
    ]
    reason = f": {failed[0]}" if failed else ""
    return False, (
        f"price panel grade {panel.get('grade')}, needs {panel.get('min_grade')}{reason}"
        f" (freshness {fresh})"
    )


def tickets() -> list[Ticket]:
    """A ticket for every active deployment, with every check filled in."""
    from eulerlab.config import load_execution
    from eulerlab.deploy import deployments, version_lock
    from eulerlab.oms.killswitch import KillSwitch, load_limits
    from eulerlab.quality import contract

    limits = load_limits()
    per_second = load_execution().max_orders_per_second
    global_switch = KillSwitch()
    grades = {str(g.get("name")): g for g in contract.saved()}
    data_ok = data_check(grades.get("Price panel"))
    out: list[Ticket] = []
    decided = decisions()
    for d in deployments.all_deployments():
        if d.status != "active":
            continue
        state = deployments.read_state(d) or {}
        own = KillSwitch(d.folder / "KILL_SWITCH", d.folder / "killswitch_log.jsonl")
        tripped = (
            global_switch.reason()
            if global_switch.is_tripped()
            else own.reason()
            if own.is_tripped()
            else ""
        )
        locked = (
            version_lock.check(d.folder, d.strategy_id)
            if (d.folder / version_lock.FILE).exists()
            else None
        )
        lock = (
            (True, "not locked yet: it locks on its next run")
            if locked is None
            else (not locked.changed, locked.detail or locked.status)
        )
        ticket = build(
            d,
            state,
            tripped=tripped,
            data_ok=data_ok,
            lock=lock,
            max_notional=float(limits.max_position_notional),
            max_per_second=per_second,
        )
        ticket.decision = str(decided.get(ticket.id, {}).get("decision", ""))
        out.append(ticket)
    return out
