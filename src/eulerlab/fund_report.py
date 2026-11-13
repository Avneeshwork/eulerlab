"""The daily fund report after the close: what the paper fund holds and what happened today (ADR-182).

NAV and P&L by strategy and ladder rung, drawdown against each book's limits,
what moved on the ladder, today's incidents and the month's AI spend. The full
report is kept; Telegram gets eight lines. Paper money only: there is no live
book in it, because no agent runs one.

Slippage is not in it yet: the live-price shadow measures it per book, but
does not keep a daily figure to read (T-4594).
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from eulerlab.paths import data_path

REPORTS = "derived/fund_reports"
LINES = 8


def build(now: datetime | None = None) -> dict[str, Any]:
    from eulerlab import constitution
    from eulerlab.agents import oncall
    from eulerlab.deploy import deployments, ladder, loss_limits
    from eulerlab.llm import spend

    at = now or datetime.now(UTC)
    rungs = ladder.stages()
    books: list[dict[str, Any]] = []
    for book in deployments.all_deployments():
        if book.mode != "paper" or book.status != "active":
            continue
        state = deployments.read_state(book) or {}
        curve = state.get("curve") or []
        equity = float(state.get("equity") or book.capital)
        day_pnl = round(float(curve[-1][1]) - float(curve[-2][1]), 2) if len(curve) > 1 else 0.0
        current, _worst = loss_limits.drawdown(state, book.capital) if curve else (0.0, 0.0)
        limits = loss_limits.for_deployment(book)
        books.append(
            {
                "book": book.id,
                "strategy": book.strategy_id,
                "rung": rungs.get(book.strategy_id, "unlisted"),
                "capital": book.capital,
                "nav": round(equity, 2),
                "pnl_day": day_pnl,
                "pnl_total": round(equity - book.capital, 2),
                "drawdown": round(current, 4),
                "halt_at": limits.halt_at,
                "risk_used": round(current / limits.halt_at, 2) if limits.halt_at else None,
                "reducing": loss_limits.is_reducing(book),
                "as_of": state.get("as_of"),
            }
        )
    day = at - timedelta(hours=24)
    cut = day.isoformat(timespec="seconds")
    moved = [
        m for m in ladder.moves() if str(m.get("at", "")) >= cut and m.get("from") != m.get("to")
    ]
    rules = constitution.load().budget
    return {
        "at": at.isoformat(timespec="seconds"),
        "books": books,
        "nav": round(sum(b["nav"] for b in books), 2),
        "capital": round(sum(b["capital"] for b in books), 2),
        "pnl_day": round(sum(b["pnl_day"] for b in books), 2),
        "ladder_moves": [f"{m['strategy']} {m['from']} to {m['to']}" for m in moved],
        "incidents": [
            f"{r['kind']}: {str(r['what'])[:80]} ({'fixed' if r.get('ok') else 'open'})"
            for r in oncall.incidents(since=day)
        ],
        "ai_spend_inr": round(spend.month_spend_inr(at), 2),
        "ai_budget_inr": rules.monthly_ai_inr,
        "slippage": "not measured yet (T-4594)",
    }


def telegram(report: dict[str, Any]) -> str:
    """Eight lines, the order the operator reads them."""
    books = report["books"]
    worst = max(books, key=lambda b: b["risk_used"] or 0.0, default=None)
    best = max(books, key=lambda b: b["pnl_day"], default=None)
    rungs: dict[str, int] = {}
    for b in books:
        rungs[b["rung"]] = rungs.get(b["rung"], 0) + 1
    lines = [
        f"Euler Lab fund, {report['at'][:10]} (paper money only)",
        f"NAV Rs {report['nav']:,.0f} on Rs {report['capital']:,.0f}; today Rs {report['pnl_day']:+,.0f}",
        f"{len(books)} book(s): "
        + (", ".join(f"{n} {k}" for k, n in sorted(rungs.items())) or "none"),
        (
            f"Best today: {best['strategy']} Rs {best['pnl_day']:+,.0f}"
            if best
            else "Best today: no book"
        ),
        (
            f"Risk: {worst['strategy']} at {worst['drawdown']:.1%} drawdown, "
            f"{(worst['risk_used'] or 0):.0%} of its halt"
            + ("; reduce-only" if any(b["reducing"] for b in books) else "")
            if worst
            else "Risk: no book"
        ),
        "Ladder: " + ("; ".join(report["ladder_moves"]) or "no moves"),
        "Incidents: " + ("; ".join(report["incidents"])[:200] or "none"),
        f"AI spend Rs {report['ai_spend_inr']:,.0f} of Rs {report['ai_budget_inr']:,.0f} this month",
    ]
    assert len(lines) == LINES
    return "\n".join(line[:160] for line in lines)


def save(report: dict[str, Any]) -> str:
    folder = data_path(REPORTS)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{report['at'][:10]}.json"
    path.write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    return str(path)


def main(argv: Sequence[str] | None = None) -> int:
    from eulerlab import notify

    parser = argparse.ArgumentParser(prog="fund-report", description=__doc__)
    parser.add_argument("--send", action="store_true", help="send the eight lines to Telegram")
    args = parser.parse_args(argv)
    report = build()
    text = telegram(report)
    print(text)
    print(f"\nkept: {save(report)}")
    if args.send:
        sent = notify.send(text)
        print("sent" if sent.sent else f"not sent: {sent.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
