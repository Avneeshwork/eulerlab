"""The autonomy scorecard: is the agent fund working, and what does it cost (ADR-173).

`make scorecard` prints one page from stored records only. It runs no test and
asks no model. The numbers that judge the agents are outcomes the agents
cannot produce by trying more rules:

- what the paid models cost this month against the constitution's budget;
- how many rules have been tried, how many distinct ideas they are, and where
  the search has piled up;
- how many gate runs the week used against its cap, and their verdicts;
- how many paper books are running forward.

Two lines are stated as not measured rather than left out: strategies
confirmed by the forward test, and the operator's minutes a week (T-4575).
Until those exist, nothing on this page says the agents have found an edge.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from eulerlab import constitution
from eulerlab.agents.spec import home
from eulerlab.llm import spend
from eulerlab.research import experiments
from eulerlab.validation import firewall, search_bar

NOT_MEASURED = "not measured yet (T-4575)"


def _gates(root: Path, since: datetime) -> tuple[int, dict[str, int]]:
    """(ledger entries used since `since`, verdict counts) from the autopilot's gate log."""
    path = root / "autopilot" / "gates.jsonl"
    if not path.exists():
        return 0, {}
    used, verdicts = 0, Counter[str]()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if datetime.fromisoformat(row["at"]) >= since:
            used += int(row.get("entries", 2))
            verdicts[str(row.get("verdict"))] += 1
    return used, dict(verdicts)


def _paper_books() -> dict[str, int]:
    from eulerlab.deploy import deployments

    found = [d for d in deployments.all_deployments() if d.mode == "paper"]
    return dict(Counter(d.status for d in found))


def _roles(at: datetime) -> dict[str, dict[str, Any]]:
    """Paid rupees and requests per role over 30 days (ADR-181); roles with neither left out."""
    from eulerlab.agents import roles
    from eulerlab.agents.spec import load_specs

    spent = roles.spend(dict(load_specs()), at)
    return {
        k: {"inr": v["inr"], "requests": v["requests"]} for k, v in spent.items() if v["requests"]
    }


def build(now: datetime | None = None, root: Path | None = None) -> dict[str, Any]:
    at = now or datetime.now(UTC)
    rules = constitution.load()
    week = at - timedelta(days=7)
    spent = spend.month_spend_inr(at)
    universe = experiments.universe()
    bar = search_bar.family_bar(universe, join_at=firewall.JOIN_AT)
    used, verdicts = _gates(home(root), week)
    return {
        "at": at.isoformat(timespec="seconds"),
        "rules": {
            "test_capital_inr": rules.capital.test_capital_inr,
            "backtest_end": rules.periods.backtest_end.isoformat(),
            "forward_start": rules.periods.forward_start.isoformat(),
            "live_account": rules.actions["live_account"],
        },
        "ai_spend": {
            "month_inr": round(spent, 2),
            "budget_inr": rules.budget.monthly_ai_inr,
            "left_inr": round(max(rules.budget.monthly_ai_inr - spent, 0.0), 2),
            "by_agent_inr": {k: round(v, 2) for k, v in spend.by_agent(at).items() if v > 0},
            "by_role_30d": _roles(at),
        },
        "search": {
            "all_time": experiments.counts(),
            "last_7_days": experiments.counts(since=week),
            "rules_with_returns": len(universe),
            "families": bar.families if bar else None,
            "noise_bar_sharpe": bar.bar if bar else None,
            "most_searched": dict(list(experiments.coverage().items())[:5]),
        },
        "gate": {
            "entries_last_7_days": used,
            "cap_per_week": rules.caps.gate_entries_per_week,
            "verdicts_last_7_days": verdicts,
        },
        "paper_books": _paper_books(),
        "forward_confirmed_strategies": NOT_MEASURED,
        "operator_minutes_per_week": NOT_MEASURED,
    }


def render(card: dict[str, Any]) -> str:
    ai, search, gate = card["ai_spend"], card["search"], card["gate"]
    lines = [
        f"Autonomy scorecard, {card['at']}",
        "",
        "-- the operator's rules (config/constitution.yaml) --",
        f"  test capital            Rs {card['rules']['test_capital_inr']:,.0f}",
        f"  history used up to      {card['rules']['backtest_end']}",
        f"  forward test from       {card['rules']['forward_start']}",
        f"  agents on live account  {card['rules']['live_account']}",
        "",
        "-- paid models this month --",
        f"  spent   Rs {ai['month_inr']:,.0f} of Rs {ai['budget_inr']:,.0f}"
        f"   (Rs {ai['left_inr']:,.0f} left)"
        + ("   SPENT: agents use free models only" if ai["left_inr"] <= 0 else ""),
        *[f"    {agent:<18} Rs {inr:,.0f}" for agent, inr in ai["by_agent_inr"].items()],
        "  by role, last 30 days:",
        *[
            f"    {role:<18} Rs {v['inr']:,.0f} over {v['requests']} requests"
            for role, v in ai["by_role_30d"].items()
        ],
        "",
        "-- the search --",
        f"  tests recorded, all time    {search['all_time'] or 'none'}",
        f"  tests recorded, last 7 days {search['last_7_days'] or 'none'}",
        f"  distinct ideas (families)   {search['families']} from "
        f"{search['rules_with_returns']} rules with daily returns",
        f"  Sharpe that noise would show after this much search: {search['noise_bar_sharpe']}",
        "  most searched: "
        + (", ".join(f"{k} ({v})" for k, v in search["most_searched"].items()) or "nothing yet"),
        "",
        "-- the gate, last 7 days --",
        f"  ledger entries  {gate['entries_last_7_days']} of {gate['cap_per_week']}",
        f"  verdicts        {gate['verdicts_last_7_days'] or 'none'}",
        "",
        "-- forward evidence --",
        f"  paper books                    {card['paper_books'] or 'none'}",
        f"  strategies confirmed forward   {card['forward_confirmed_strategies']}",
        f"  operator minutes a week        {card['operator_minutes_per_week']}",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The autonomy scorecard (ADR-173).")
    parser.add_argument("--json", action="store_true", help="print the numbers as JSON")
    args = parser.parse_args(argv)
    card = build()
    print(json.dumps(card, indent=2) if args.json else render(card))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
