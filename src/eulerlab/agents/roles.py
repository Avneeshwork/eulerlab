"""Nine roles, each feeding one decision, and which model each role's work goes to (ADR-181).

Fifteen agent definitions grew one at a time. Each now names the role it
plays, so the operator sees nine jobs instead of fifteen names, and spend is
counted by the decision it serves:

    scout              finds papers and notices worth a card        small model
    generator          writes and mutates rules (inside the engine) mid
    engineer           changes code, each on its own branch         frontier
    evaluator          screens, gates, firewall: code only          none
    red_team           attacks a result before the gate             frontier
    allocator          sizes passed strategies, in code; explains   small
    execution_analyst  fills and timing against the backtest        small
    on_call            dead letters, failed runs, data gaps         mid
    chief_of_staff     the operator's briefs, answers, memo, plans  frontier

The tier names a provider through the constitution's `routing` table. An
agent whose definition names its own provider keeps it: that is a choice made
for cost (most are on free Groq inside the Rs 1,000 budget), and `exceptions`
lists every such agent so the choice stays visible. Nothing here makes an
agent's model dearer by itself.

The three department heads are folded into chief_of_staff; they are not
retired, since the plans and checklists they write are still read (T-4593).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from eulerlab import constitution

Tier = Literal["frontier", "mid", "small", "scoring"]


@dataclass(frozen=True)
class Role:
    name: str
    tier: Tier
    decision: str
    """The decision the role's output feeds."""


ROLES: dict[str, Role] = {
    r.name: r
    for r in (
        Role("scout", "small", "which papers and notices become cards"),
        Role("generator", "mid", "which rules are tried tonight"),
        Role("engineer", "frontier", "which code change is merged"),
        Role("evaluator", "scoring", "which rule passes the screen and the gate"),
        Role("red_team", "frontier", "whether a result is fake before the gate sees it"),
        Role("allocator", "small", "how much paper capital a passed strategy gets"),
        Role("execution_analyst", "small", "whether fills still match the backtest"),
        Role("on_call", "mid", "which failure is fixed, and how"),
        Role("chief_of_staff", "frontier", "what the operator reads and decides this week"),
    )
}


def provider_for(role: str) -> str:
    """The provider the constitution routes this role's work to, or 'none' for code only."""
    routing = constitution.load().routing
    tier = ROLES[role].tier
    return str(getattr(routing, tier))


def role_of(spec: Any) -> str:
    return str(getattr(spec, "role", "") or "")


def exceptions(specs: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Agents whose own provider differs from their role's route, with both."""
    out = {}
    for name, spec in sorted(specs.items()):
        role = role_of(spec)
        if not role or not getattr(spec, "uses_model", False):
            continue
        routed = provider_for(role)
        own = str(getattr(spec, "provider", "") or "")
        if own and own != routed:
            out[name] = {"role": role, "own": own, "routed": routed}
    return out


def spend(
    specs: dict[str, Any], now: datetime | None = None, *, days: int = 30
) -> dict[str, dict[str, Any]]:
    """Each role's paid-model rupees and model requests over the last `days`, and its agents."""
    from eulerlab.llm import spend as money
    from eulerlab.llm import usage

    at = now or datetime.now(UTC)
    rules, free = constitution.load().budget, money.free_providers()
    agents = {name: role_of(spec) for name, spec in specs.items()}
    out: dict[str, dict[str, Any]] = {
        r: {"inr": 0.0, "requests": 0, "agents": sorted(a for a, x in agents.items() if x == r)}
        for r in ROLES
    }
    out["unassigned"] = {"inr": 0.0, "requests": 0, "agents": []}
    for row in usage.rows(since=at - timedelta(days=days)):
        role = agents.get(str(row.get("agent") or ""), "") or "unassigned"
        out[role]["inr"] += money.cost_inr(row, rules, free)
        out[role]["requests"] += 1
    for row in out.values():
        row["inr"] = round(row["inr"], 2)
    return out
