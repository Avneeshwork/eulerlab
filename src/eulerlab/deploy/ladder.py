"""The incubation ladder: a gated strategy climbs on evidence, with no real money on any rung (ADR-179).

    registered ─▶ paper ─▶ live_price_paper ─▶ ready_for_real_money
                    ▲            │                (a list for the operator;
                    └── demoted ─┘                 the ladder ends there)

Each rung's entry test is written here, before any strategy reaches it:

    paper                 the gate said PROMOTE or PAPER. A paper book is started at the
                          constitution's test capital if none exists.
    live_price_paper      `MIN_PAPER_SESSIONS` sessions on paper, not decayed, no loss
                          limit tripped, no guardian hold. From here the book is also
                          priced on live quotes each morning (`deploy/live_shadow.py`),
                          which measures its slippage against the backtest's fills.
    ready_for_real_money  the 2026 forward test, scored **once**: the mandate's
                          `forward_test` rule (sessions, half the backtest Sharpe, the
                          drawdown floor) on the paper book's own record. The score is
                          written to the experiment store as the one `forward` row
                          for that strategy and never used to change the rule. A fail
                          is final: the strategy goes to `failed_forward`.

    down one rung         the decay monitor says decayed, a loss limit tripped, or the
                          guardian holds the strategy. Off the bottom rung means the
                          paper book is stopped.

**The ladder ends at a list.** `ready_for_real_money` is a name on a page with
its evidence. Nothing here arms, sizes or sends a real order: the operator
does that separately, each time (`deploy/live_money.arm`, which refuses any
call made inside an agent's run). `constitution.yaml` has `live_account: never`
and the loader accepts no other value.

Every move is one appended row in `data/derived/ladder.jsonl` and one line in
the operator's inbox. A strategy's rung is its last row; nothing is edited.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from eulerlab import constitution
from eulerlab.db.stream import add_row, read_rows
from eulerlab.paths import data_path

KIND = "ladder"
Stage = Literal["registered", "paper", "live_price_paper", "ready_for_real_money", "failed_forward"]
ORDER: tuple[Stage, ...] = ("registered", "paper", "live_price_paper", "ready_for_real_money")
MIN_PAPER_SESSIONS = 5
"""ASSUMPTION: A-140 — a week on paper proves the book runs, nothing about its edge."""
WHO = "the ladder"


def path_for() -> Path:
    return data_path("derived/ladder.jsonl")


@dataclass(frozen=True)
class Facts:
    """What is known about one strategy today. Gathered by `facts_for`, judged by `decide`."""

    strategy: str
    stage: Stage
    verdict: str
    """The gate's latest: PROMOTE, PAPER, KILL or ''."""
    paper_book: str = ""
    """The id of its active paper deployment, or ''."""
    paper_sessions: int = 0
    decay: str = "too little history"
    loss_limit: str = ""
    """Why the book is reducing or halted, or ''."""
    guardian_hold: str = ""
    forward_ready: bool | None = None
    """The mandate's forward-test rule on the paper record; None while it cannot be scored."""
    forward_reasons: tuple[str, ...] = ()
    forward_scored: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Move:
    strategy: str
    start: Stage
    to: Stage
    why: str
    action: Literal["", "start_paper", "stop_paper", "score_forward"] = ""


def _down(stage: Stage) -> Stage:
    return ORDER[max(0, ORDER.index(stage) - 1)] if stage in ORDER else "registered"


def decide(f: Facts) -> Move | None:
    """The one move this strategy makes today, or None. Trouble is looked at before progress."""
    if f.stage in ("failed_forward", "ready_for_real_money") and not (
        f.stage == "ready_for_real_money"
        and (f.decay == "decayed" or f.loss_limit or f.guardian_hold)
    ):
        return None
    trouble = (
        "the decay monitor says its edge has gone"
        if f.decay == "decayed"
        else (f.loss_limit and f"a loss limit acted: {f.loss_limit}")
        or (f.guardian_hold and f"the guardian holds it: {f.guardian_hold}")
        or (f.verdict == "KILL" and "the gate's latest verdict is KILL")
        or ""
    )
    if trouble and f.stage != "registered":
        to = _down(f.stage)
        return Move(f.strategy, f.stage, to, trouble, "stop_paper" if to == "registered" else "")
    if trouble:
        return None
    if f.stage == "registered" and f.verdict in ("PROMOTE", "PAPER"):
        why = f"the gate said {f.verdict}"
        return Move(f.strategy, f.stage, "paper", why, "" if f.paper_book else "start_paper")
    if f.stage == "paper" and f.paper_book and f.paper_sessions >= MIN_PAPER_SESSIONS:
        why = f"{f.paper_sessions} sessions on paper with no decay, loss limit or hold"
        return Move(f.strategy, f.stage, "live_price_paper", why)
    if f.stage == "live_price_paper" and f.forward_ready is not None and not f.forward_scored:
        waiting = [r for r in f.forward_reasons if "trading days of" in r]
        if waiting:
            return None  # not enough sessions yet: the one score is not spent early
        if f.forward_ready:
            why = "passed the forward test on its paper record"
            return Move(f.strategy, f.stage, "ready_for_real_money", why, "score_forward")
        why = "failed the forward test: " + "; ".join(f.forward_reasons)
        return Move(f.strategy, f.stage, "failed_forward", why, "score_forward")
    return None


# --- the record --------------------------------------------------------------------------


def moves(path: Path | None = None) -> list[dict[str, Any]]:
    return read_rows(path or path_for(), KIND)


def stages(path: Path | None = None) -> dict[str, Stage]:
    """Each strategy's rung: where its last move left it."""
    return {str(r["strategy"]): r["to"] for r in moves(path)}


def at_stage(stage: Stage, path: Path | None = None) -> list[str]:
    return sorted(s for s, found in stages(path).items() if found == stage)


def record(
    move: Move, evidence: dict[str, Any], *, now: datetime, path: Path | None = None
) -> None:
    add_row(
        path or path_for(),
        KIND,
        {
            "at": now.astimezone(UTC).isoformat(timespec="seconds"),
            "strategy": move.strategy,
            "from": move.start,
            "to": move.to,
            "why": move.why,
            "by": WHO,
            "evidence": evidence,
        },
    )


# --- gathering facts and acting ----------------------------------------------------------


def backtest_returns(strategy: str) -> list[float]:
    """The strategy's daily net returns on its screen, from the experiment store."""
    from eulerlab.research import experiments

    for row in reversed(experiments.rows()):
        if row.get("hypothesis") == strategy and row.get("returns"):
            return [v for _, v in sorted(experiments.returns_of(row).items())]
    return []


def facts_for(strategy: str, stage: Stage, verdict: str) -> Facts:
    from eulerlab import forward
    from eulerlab.deploy import decay, deployments, live_shadow, loss_limits, readiness
    from eulerlab.research import experiments

    book = next(
        (
            d
            for d in deployments.all_deployments()
            if d.strategy_id == strategy and d.mode == "paper" and d.status != "stopped"
        ),
        None,
    )
    state = deployments.read_state(book) if book else None
    live = forward.state_returns(state, book.capital if book else None)
    shadow = live_shadow.read_summary().get(strategy) or {}
    reading = decay.read(backtest_returns(strategy), live)
    limit = ""
    if book is not None:
        limit = "halted" if book.status == "halted" else ""
        if not limit and loss_limits.is_reducing(book):
            limit = "reduce-only"
    hold = readiness.guardian_line(strategy)
    report = (
        forward.report(
            book, state, tested_sharpe=forward.backtest_sharpe(strategy), rule=forward.rules()
        )
        if book
        else None
    )
    scored = any(r.get("hypothesis") == strategy for r in experiments.rows(purpose="forward"))
    return Facts(
        strategy=strategy,
        stage=stage,
        verdict=verdict,
        paper_book=book.id if book else "",
        paper_sessions=len(live),
        decay=reading.state,
        loss_limit=limit,
        guardian_hold="" if hold.met else hold.evidence,
        forward_ready=report.ready if report else None,
        forward_reasons=tuple(report.reasons) if report else (),
        forward_scored=scored,
        evidence={
            "paper_book": book.id if book else "",
            "paper_sessions": len(live),
            "decay": reading.as_dict(),
            "slippage_bps_median": shadow.get("median_slippage_bps"),
            "live_price_sessions": shadow.get("sessions"),
            "forward": {
                "sharpe": report.sharpe if report else None,
                "backtest_sharpe": report.backtest_sharpe if report else None,
                "max_drawdown": report.max_drawdown if report else None,
                "days": report.days if report else 0,
            },
        },
    )


def start_paper(strategy: str, today: date) -> str:
    """Start the strategy's paper book at the constitution's test capital. Returns what happened."""
    from eulerlab.deploy import deployments, intraday_book, runner

    constitution.require("start_paper_book", who=WHO)
    if blocker := runner.paper_blocker(strategy):
        return f"not deployed: {blocker}"
    if any(d.strategy_id == strategy and d.mode == "paper" for d in deployments.all_deployments()):
        return "already has a paper book"
    end = intraday_book.holdout_end()
    assert end is not None  # paper_blocker refuses without it
    made = deployments.create(
        strategy,
        mode="paper",
        capital=constitution.load().capital.test_capital_inr,
        start=intraday_book.first_session(today, end),
    )
    return f"paper book {made.id} (runs with `make paper-daily`)"


def _apply(move: Move, facts: Facts, now: datetime) -> str:
    from eulerlab.deploy import deployments
    from eulerlab.research import experiments

    if move.action == "start_paper":
        return start_paper(move.strategy, now.date())
    if move.action == "stop_paper":
        constitution.require("stop_paper_book", who=WHO)
        for d in deployments.all_deployments():
            if d.strategy_id == move.strategy and d.mode == "paper" and d.status == "active":
                deployments.set_status(d, "stopped", f"demoted by the ladder: {move.why}"[:200])
        return "paper book stopped"
    if move.action == "score_forward":
        constitution.require("score_forward_test", who=WHO)
        rules = constitution.load().periods
        forward = facts.evidence.get("forward") or {}
        experiments.record(
            purpose="forward",
            hypothesis=move.strategy,
            fingerprint=f"forward:{move.strategy}",
            first=rules.forward_start,
            end=now.date(),
            metrics={**forward, "passed": move.to == "ready_for_real_money"},
            asked_by=WHO,
            now=now,
        )
        return "forward test scored, once"
    return ""


def step(now: datetime | None = None, *, path: Path | None = None) -> list[dict[str, Any]]:
    """Look at every gated strategy once and make the moves that are due. Returns them."""
    from eulerlab import forward

    now = now or datetime.now(UTC)
    known = stages(path)
    made: list[dict[str, Any]] = []
    gate = forward.verdicts()
    for strategy in sorted({*gate, *known}):
        verdict = gate.get(strategy, ("", date.min))[0]
        stage: Stage = known.get(strategy, "registered")
        if stage == "registered" and verdict not in ("PROMOTE", "PAPER"):
            continue
        facts = facts_for(strategy, stage, verdict)
        move = decide(facts)
        if move is None:
            continue
        try:
            done = _apply(move, facts, now)
        except constitution.NotAllowed as exc:
            done = f"not deployed: {exc}"
        if move.action and done.startswith("not deployed"):
            made.append({"strategy": strategy, "from": move.start, "to": move.start, "why": done})
            continue
        record(move, {**facts.evidence, "done": done}, now=now, path=path)
        made.append(
            {"strategy": strategy, "from": move.start, "to": move.to, "why": move.why, "done": done}
        )
    return made


def _notable(start: str, to: str) -> bool:
    """A demotion, a failed forward test, or the end of the ladder: worth the operator's eye."""
    if to in ("ready_for_real_money", "failed_forward"):
        return True
    order: list[str] = list(ORDER)
    return order.index(to) < order.index(start)


def worker(ctx: Any) -> Any:
    """The ladder as an agent's run: each move is a line in the operator's inbox."""
    from eulerlab.agents.runtime import Item, WorkerResult

    made = step(ctx.now)
    moved = [m for m in made if m["from"] != m["to"]]
    items = [
        Item(
            kind="finding",
            title=f"{m['strategy']}: {m['from']} to {m['to']}"[:200],
            body=f"{m['why']}. {m.get('done', '')}".strip()
            + (
                " It is on the list for real money. Whether to trade it, and with how much, "
                "is your decision; no agent can."
                if m["to"] == "ready_for_real_money"
                else ""
            ),
            severity="warn" if _notable(m["from"], m["to"]) else "info",
            needs_approval=m["to"] == "ready_for_real_money",
            ref=f"hypotheses/{m['strategy']}.yaml",
        )
        for m in moved
    ]
    blocked = [f"{m['strategy']}: {m['why']}" for m in made if m["from"] == m["to"]]
    summary = f"{len(moved)} move(s) on the ladder" + (
        f"; {len(blocked)} blocked" if blocked else ""
    )
    return WorkerResult(summary, items=items, data={"moves": made, "stages": stages()})


def render(path: Path | None = None) -> str:
    found = stages(path)
    lines = ["The incubation ladder (no real money on any rung)"]
    for stage in (*ORDER, "failed_forward"):
        names = sorted(s for s, at in found.items() if at == stage)
        lines.append(f"  {stage:22s} {', '.join(names) or 'none'}")
    lines.append("  Real money is the operator's separate decision, each time.")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    from eulerlab.agents import runtime

    parser = argparse.ArgumentParser(prog="ladder", description=__doc__)
    parser.add_argument("--show", action="store_true", help="print the rungs; move nothing")
    args = parser.parse_args(argv)
    if not args.show:
        output = runtime.run("portfolio", worker=worker)
        print(f"{output.status}: {output.summary}")
    print(render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
