"""What the paid models have cost this month, against the operator's budget (ADR-171).

The constitution gives a monthly budget in rupees and a price per model.
`llm/usage.py` already records every request's tokens with its provider and
model. This module multiplies the two, and `refuse_if_spent` is the hard stop:
an agent's request to a paid provider is refused once the calendar
month's recorded spend has reached the budget (`MonthBudgetSpent`).

Free providers (`free: true` in `config/llm.yaml`) cost nothing and are never
refused, so the agents fall back to them for the rest of the month. A paid
model with no listed price is charged at `unknown_paid_model`, the dearest,
so a missing price cannot make the month look cheaper than it was.

The month is the IST calendar month. The operator's own questions in the
assistant panel are counted in the spend, and are not refused: the stop is on
what agents do by themselves.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from eulerlab import constitution
from eulerlab.llm import client, usage

IST = ZoneInfo("Asia/Kolkata")


class BudgetSpent(RuntimeError):
    """An agent has used its model requests for today (`agents/runtime.py` raises it)."""


class MonthBudgetSpent(BudgetSpent):
    """The month's budget for paid models is used up. Free providers still answer."""


def month_start(now: datetime) -> datetime:
    local = now.astimezone(IST)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def free_providers(config: client.LLMConfig | None = None) -> frozenset[str]:
    loaded = config or client.load_config()
    return frozenset(p.name for p in loaded.providers if p.free)


def cost_inr(row: dict[str, Any], rules: constitution.Budget, free: frozenset[str]) -> float:
    """One recorded request's cost in rupees."""
    if row.get("provider") in free:
        return 0.0
    price = rules.prices_usd_per_mtok.get(str(row.get("model")), rules.unknown_paid_model)
    usd = (
        int(row.get("prompt") or 0) * price.input + int(row.get("completion") or 0) * price.output
    ) / 1e6
    return usd * rules.usd_inr


def month_spend_inr(
    now: datetime | None = None,
    *,
    rules: constitution.Budget | None = None,
    free: frozenset[str] | None = None,
    log: Path | None = None,
) -> float:
    """Rupees spent on paid models since the first of this IST month."""
    at = now or datetime.now(UTC)
    budget = rules or constitution.load().budget
    names = free if free is not None else free_providers()
    return sum(cost_inr(row, budget, names) for row in usage.rows(since=month_start(at), path=log))


def by_agent(now: datetime | None = None, *, log: Path | None = None) -> dict[str, float]:
    """This month's spend in rupees, per agent, dearest first."""
    at = now or datetime.now(UTC)
    budget, names = constitution.load().budget, free_providers()
    out: dict[str, float] = {}
    for row in usage.rows(since=month_start(at), path=log):
        agent = str(row.get("agent") or "assistant")
        out[agent] = out.get(agent, 0.0) + cost_inr(row, budget, names)
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def refuse_if_spent(provider: str, now: datetime | None = None, *, log: Path | None = None) -> None:
    """Raise `BudgetSpent` when `provider` is paid and the month's budget is gone."""
    names = free_providers()
    if provider in names:
        return
    constitution.require("spend_ai_budget", who=f"a request to {provider}")
    budget = constitution.load().budget
    spent = month_spend_inr(now, rules=budget, free=names, log=log)
    if spent >= budget.monthly_ai_inr:
        msg = (
            f"the month's budget for paid models is spent: Rs {spent:,.0f} of "
            f"Rs {budget.monthly_ai_inr:,.0f} (config/constitution.yaml). {provider} is paid; "
            "free providers still answer."
        )
        raise MonthBudgetSpent(msg)
