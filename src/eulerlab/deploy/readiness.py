"""Is a strategy ready for real money? One checklist per strategy, every line with evidence (ADR-153).

    make readiness                     every strategy with an active paper book
    make readiness STRATEGY=H-0161     one

Two stages, read from `mandate.yaml` (operator-owned; this module never writes it):

- **pilot**: `forward_test.pilot`, if the operator adds one: a capped first
  live book (capital, sessions of live-price paper, a daily loss halt). Without
  that block the pilot line says so and is not met.
- **full**: `forward_test` as written (60 paper sessions, forward Sharpe at
  least half the backtest's, drawdown floor), through `forward.ready_for_live`.

Lines that hold for both stages:

- an active paper book exists for the strategy;
- live-price paper (`deploy/live_shadow.py`) has measured fills, and the edge
  left after real fills and costs is still positive;
- the Kite order path has been proved by one supervised order (S-015), shown by
  `data/oms/kite_proof.json`;
- the kill switch has been tripped and cleared in a drill within 30 days;
- no guardian hold is open on the strategy (a result too good to believe);
- the operator's explicit go, `data/desk/live_go.json`, names the strategy.

This module only reads. A "ready" here is necessary, never sufficient: the
first live order still waits for the operator.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from eulerlab.deploy import live_shadow

MANDATE = Path("mandate.yaml")
KITE_PROOF = Path("data/oms/kite_proof.json")
KILL_LOG = Path("data/oms/killswitch_log.jsonl")
LIVE_GO = Path("data/desk/live_go.json")
GUARDIAN_LOG = Path("data/agents/guardian/log.jsonl")
COST_BPS = 12.24
"""A ₹1 lakh NSE cash intraday round trip (research 171). Recheck with T-906."""
DRILL_DAYS = 30


@dataclass(frozen=True)
class Line:
    check: str
    met: bool
    evidence: str
    stage: str = "both"
    """`pilot`, `full` or `both`."""


def _mandate(path: Path = MANDATE) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    return raw if isinstance(raw, dict) else {}


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def paper_line(strategy: str, deployments: list[Any]) -> Line:
    active = [d for d in deployments if d.strategy_id == strategy and d.status == "active"]
    if not active:
        return Line("active paper book", False, "none: start one from Live → Deploy")
    return Line("active paper book", True, ", ".join(d.id for d in active))


def shadow_line(strategy: str, summary: dict[str, dict[str, Any]], min_sessions: int) -> Line:
    s = summary.get(strategy)
    if not s:
        return Line("edge survives live-price fills", False, "no live-price sessions measured yet")
    left = (s.get("mean_achievable_bps") or 0.0) - COST_BPS
    text = (
        f"{s['sessions']} sessions, {s['trades']} trades; backtest {s['mean_backtest_bps']} bps, "
        f"achievable {s['mean_achievable_bps']} bps a trade (median slippage "
        f"{s['median_slippage_bps']} bps); after {COST_BPS} bps costs {left:+.2f} bps"
    )
    met = s["sessions"] >= min_sessions and left > 0
    if s["sessions"] < min_sessions:
        text += f"; {min_sessions} sessions needed"
    return Line("edge survives live-price fills", met, text)


def kite_line(path: Path = KITE_PROOF) -> Line:
    if not path.exists():
        return Line(
            "Kite order path proved (S-015)",
            False,
            "never sent a real order: one supervised one-share order with the operator present",
        )
    body = json.loads(path.read_text(encoding="utf-8"))
    return Line(
        "Kite order path proved (S-015)", True, f"{body.get('at', '?')}: {body.get('what', '')}"
    )


def drill_line(now: datetime, path: Path = KILL_LOG) -> Line:
    since = now - timedelta(days=DRILL_DAYS)
    rows = []
    for r in _rows(path):
        try:
            when = datetime.fromisoformat(str(r.get("at") or r.get("time") or ""))
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        if when >= since:
            rows.append(r)
    events = {str(r.get("event") or r.get("action") or "") for r in rows}
    tripped = any("trip" in e for e in events)
    cleared = any(("clear" in e) or ("reset" in e) for e in events)
    met = tripped and cleared
    text = (
        f"tripped and cleared within {DRILL_DAYS} days"
        if met
        else f"no trip-and-clear drill in the last {DRILL_DAYS} days (make kill-stop REASON=drill, then reset it by hand)"
    )
    return Line("kill switch drilled", met, text)


def guardian_line(strategy: str, path: Path = GUARDIAN_LOG) -> Line:
    holds = [
        r for r in _rows(path) if r.get("rule") == "too_good" and strategy in str(r.get("why"))
    ]
    if holds:
        return Line(
            "no open guardian hold",
            False,
            f"held {holds[-1].get('at', '')}: {str(holds[-1].get('why'))[:160]}",
        )
    return Line("no open guardian hold", True, "none")


def go_line(strategy: str, path: Path = LIVE_GO) -> Line:
    if path.exists():
        body = json.loads(path.read_text(encoding="utf-8"))
        named = body.get("strategies") or []
        if strategy in named:
            return Line("operator's go", True, f"{body.get('at', '')}: {body.get('note', '')}")
    return Line("operator's go", False, "not given: live money waits for Avneesh")


def pilot_line(rule: dict[str, Any]) -> tuple[Line, int]:
    pilot = rule.get("pilot")
    if not isinstance(pilot, dict):
        return (
            Line(
                "pilot rule in the mandate",
                False,
                "no forward_test.pilot block: the operator decides whether a capped pilot is allowed",
                "pilot",
            ),
            10,
        )
    sessions = int(pilot.get("min_live_price_sessions", 10))
    text = (
        f"capital up to ₹{pilot.get('max_capital', '?')}, {pilot.get('max_strategies', 1)} "
        f"strategy, halt at ₹{pilot.get('daily_loss_halt', '?')} a day"
    )
    return Line("pilot rule in the mandate", True, text, "pilot"), sessions


def full_line(strategy: str, deployments: list[Any], rule: dict[str, Any]) -> Line:
    from eulerlab import forward
    from eulerlab.deploy import deployments as store

    active = [d for d in deployments if d.strategy_id == strategy and d.status == "active"]
    if not active:
        return Line("mandate forward test", False, "no paper book", "full")
    d = active[0]
    try:
        report = forward.report(
            d,
            store.read_state(d),
            tested_sharpe=forward.backtest_sharpe(strategy),
            rule=rule,
        )
        ok, reasons = forward.ready_for_live(report, rule)
    except Exception as exc:  # a book that has not run yet has no report
        return Line("mandate forward test", False, f"not measured: {type(exc).__name__}", "full")
    return Line("mandate forward test", bool(ok), "met" if ok else "; ".join(reasons), "full")


def checklist(
    strategy: str,
    *,
    deployments: list[Any] | None = None,
    summary: dict[str, dict[str, Any]] | None = None,
    now: datetime | None = None,
    mandate: dict[str, Any] | None = None,
) -> list[Line]:
    from eulerlab.deploy import deployments as store

    deployments = deployments if deployments is not None else store.all_deployments()
    summary = summary if summary is not None else live_shadow.read_summary()
    now = now or datetime.now(UTC)
    rule = (mandate if mandate is not None else _mandate()).get("forward_test") or {}
    pilot, sessions = pilot_line(rule)
    return [
        paper_line(strategy, deployments),
        shadow_line(strategy, summary, sessions),
        kite_line(),
        drill_line(now),
        guardian_line(strategy),
        go_line(strategy),
        pilot,
        full_line(strategy, deployments, rule),
    ]


def verdict(lines: list[Line]) -> dict[str, bool]:
    both = all(x.met for x in lines if x.stage == "both")
    return {
        "pilot": both and all(x.met for x in lines if x.stage == "pilot"),
        "full": both and all(x.met for x in lines if x.stage == "full"),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    from eulerlab.deploy import deployments as store

    parser = argparse.ArgumentParser(description="Readiness for real money (ADR-153).")
    parser.add_argument("--strategy", default="")
    args = parser.parse_args(argv)
    known = store.all_deployments()
    wanted = (
        [args.strategy]
        if args.strategy
        else sorted({d.strategy_id for d in known if d.status == "active"})
    )
    for sid in wanted:
        lines = checklist(sid, deployments=known)
        v = verdict(lines)
        print(
            f"\n{sid}: pilot {'READY' if v['pilot'] else 'not ready'}, full {'READY' if v['full'] else 'not ready'}"
        )
        for x in lines:
            print(f"  [{'x' if x.met else ' '}] {x.check}: {x.evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
