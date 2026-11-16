"""The guardian: after every agent run, check fixed rules and stop what misbehaves (ADR-152).

    runtime.run -> doctor.after_run -> guardian.after_run(output)
        -> RULES, each a pure function of what is on disk
        -> an action from a fixed list:
             suspend : switch that one agent off (spec.write_setting, which only narrows)
             halt    : stop every agent (data/agents/HALT); the runtime refuses to start any
             hold    : no switch flipped; the operator is told and a lesson is written
        -> data/agents/guardian/log.jsonl   one line per trip, never rewritten
        -> a lesson (source "guardian"), so the next runs read why

**The asymmetry is the kill switch's** (`oms/killswitch.py`). Anything may trip
the guardian; nothing in an agent's reach clears it. Lifting a halt is
`make agents-resume REASON="..."`, which is `main()` behind `clear`, an operator
command. Switching a suspended agent back on is the operator's, on the AI tab.

**The doctor fixes; the guardian stops.** The doctor applies safe remedies
(close a stalled run, queue a code fix). The guardian acts when a remedy is not
enough: the same failure three runs running (told, not stopped), figures a model made up, a
protected file changed, more ledger entries than the week allows, or a result
too good to believe. It never edits code, deletes data or touches orders.

It must never break the run it inspects: `after_run` swallows its own errors
and records them.

**A planned edit is not a halt (ADR-217).** A protected file whose last commit
carries an `Operator-Ack:` trailer, and which is on disk exactly as that commit
left it, is logged as `acked_change` and joins the baseline; the commit-msg
hook (`eulerlab.operator_ack`) refuses a commit to these files without one.
**A halt is loud until lifted:** a Telegram line when it starts, and again at
2 h and 8 h (`escalate`, run hourly by the `halt-watch` job), and `make health`
is red while it lasts.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from eulerlab.agents.spec import home

Action = Literal["suspend", "halt", "hold"]

# ASSUMPTION: A-125 — these thresholds are chosen by hand.
FAILED = frozenset({"failed", "over_budget"})
REPEATS = 3
"""Consecutive failed runs of one agent that are held: told and written as a lesson.

Not suspended: a failing agent must keep running so the doctor's and the
engineering agent's fixes can heal it, and the watchdog already reports it as
stuck (ADR-132). Suspension is for wrong-doing, not for breaking."""

MADE_UP_PER_DAY = 3
"""Answers withheld for unsupported figures, in one IST day, that suspend an agent."""
MADE_UP_MARKS = ("unsupported figure", "figures not in", "made-up figure", "not in the evidence")

TOO_GOOD_SHARPE = 3.0
"""A screened net Sharpe above this is held for the skeptic and the operator."""

PROTECTED = (
    Path("mandate.yaml"),
    Path("src/eulerlab/gates.py"),
    Path("config/constitution.yaml"),
    *(
        Path(f"config/agent_eval/heldout/{r}.yaml")
        for r in ("on_call", "red_team", "generator", "scout", "engineer")
    ),  # ADR-183
)
"""Operator-owned files (CLAUDE.md). A change no operator acknowledged halts every agent."""

HALT_FILE = "HALT"


@dataclass(frozen=True)
class Trip:
    rule: str
    agent: str
    action: Action
    why: str
    at: str = ""


@dataclass(frozen=True)
class Facts:
    """What the rules read, gathered once per check so a test can hand it in."""

    output: Any
    recent: list[Any]
    """The agent's latest outputs, newest first, including this one."""
    root: Path
    now: datetime
    repo: Path


Rule = Callable[[Facts], Trip | None]


# --- the rules ---------------------------------------------------------------------------


def repeated_failure(f: Facts) -> Trip | None:
    last = f.recent[:REPEATS]
    if len(last) < REPEATS or not all(o.status in FAILED for o in last):
        return None
    return Trip(
        "repeated_failure",
        f.output.agent,
        "hold",
        f"{REPEATS} runs in a row failed; the last: {str(f.output.summary)[:200]}",
    )


def _ist_day(at: str) -> str:
    when = datetime.fromisoformat(at)
    return (when + timedelta(hours=5, minutes=30)).date().isoformat()


def made_up_figures(f: Facts) -> Trip | None:
    day = _ist_day(f.output.started)
    count = 0
    for o in f.recent:
        if _ist_day(o.started) != day:
            continue
        count += sum(1 for n in o.notes if any(m in n.lower() for m in MADE_UP_MARKS))
    if count < MADE_UP_PER_DAY:
        return None
    return Trip(
        "made_up_figures",
        f.output.agent,
        "suspend",
        f"{count} answers today carried figures no evidence held (grounding, ADR-088)",
    )


def too_good(f: Facts) -> Trip | None:
    sharpes = (f.output.data or {}).get("net_sharpe") or {}
    high = {h: s for h, s in sharpes.items() if isinstance(s, (int, float)) and s > TOO_GOOD_SHARPE}
    if not high:
        return None
    named = ", ".join(f"{h} {s:.2f}" for h, s in sorted(high.items()))
    return Trip(
        "too_good",
        f.output.agent,
        "hold",
        f"net Sharpe above {TOO_GOOD_SHARPE:g} ({named}): check fills, universe and lookahead "
        "before trusting it; paper only, never a pilot, until the skeptic and the operator agree",
    )


def entries_this_week(root: Path, now: datetime) -> int:
    """Ledger entries the autopilot spent in the last 7 days, from its own gate log.

    Read as a file, not through `research.autopilot`, so nothing the runtime
    loads reaches the gating code (`agents/boundaries.py`).
    """
    path = root / "autopilot" / "gates.jsonl"
    if not path.exists():
        return 0
    since = now - timedelta(days=7)
    used = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if datetime.fromisoformat(row["at"]) >= since:
            used += int(row.get("entries", 2))
    return used


def ledger_over_allowance(f: Facts) -> Trip | None:
    if f.output.agent != "autopilot":
        return None
    allowance = _allowance()
    used = entries_this_week(f.root, f.now)
    if used <= allowance:
        return None
    return Trip(
        "ledger_over_allowance",
        "autopilot",
        "suspend",
        f"{used} ledger entries in 7 days, over the allowance of {allowance}",
    )


def protected_changed(f: Facts) -> Trip | None:
    base = _baseline(f.root)
    now = fingerprints(f.repo)
    if not base:
        _write_baseline(f.root, now, why="first check")
        return None
    added = {p: h for p, h in now.items() if p not in base}
    if added:
        # A file protected since the baseline was written (the constitution,
        # ADR-171) joins it as it stands; only a later change to it is a trip.
        _write_baseline(f.root, {**base, **added}, why=f"now protected: {', '.join(added)}")
    changed = [p for p, h in now.items() if p in base and base[p] != h]
    acks = {p: why for p in changed if (why := _acked(f.repo, p, now[p]))}
    if acks:
        # A commit carrying `Operator-Ack:` (ADR-217): logged and accepted, not a halt.
        _write_baseline(
            f.root, {**_baseline(f.root), **{p: now[p] for p in acks}}, why="operator-acked commit"
        )
        for p, why in acks.items():
            _log(f.root, Trip("acked_change", "all", "hold", f"{p}: {why}"[:300]))
    changed = [p for p in changed if p not in acks]
    if not changed:
        return None
    return Trip(
        "protected_changed",
        "all",
        "halt",
        f"operator-owned file changed without acknowledgement: {', '.join(changed)}. "
        "If you changed it, run `make agents-resume REASON=...`; next time commit it "
        "with an `Operator-Ack:` trailer",
    )


RULES: tuple[Rule, ...] = (
    protected_changed,
    repeated_failure,
    made_up_figures,
    ledger_over_allowance,
    too_good,
)


# --- state on disk ---------------------------------------------------------------------


def _dir(root: Path) -> Path:
    return root / "guardian"


def _allowance() -> int:
    import yaml

    path = Path("config/agents/autopilot.yaml")
    if not path.exists():
        return 10
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return int((raw.get("options") or {}).get("gate_entries_per_week", 10))


def fingerprints(repo: Path) -> dict[str, str]:
    from eulerlab.operator_ack import digest

    out = {}
    for rel in PROTECTED:
        path = repo / rel
        out[str(rel)] = digest(path.read_bytes()) if path.exists() else "absent"
    return out


def _acked(repo: Path, rel: str, current: str) -> str:
    """Why the operator acked this exact change in a commit, or '' (ADR-217)."""
    from eulerlab.operator_ack import acked

    return acked(repo, rel, current)


def _log(root: Path, trip: Trip) -> Trip:
    stamped = Trip(
        **{**asdict(trip), "at": trip.at or datetime.now(UTC).isoformat(timespec="seconds")}
    )
    path = _dir(root) / "log.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(stamped)) + "\n")
    return stamped


def _baseline(root: Path) -> dict[str, str]:
    path = _dir(root) / "baseline.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in (raw.get("files") or {}).items()}


def _write_baseline(root: Path, files: dict[str, str], *, why: str) -> None:
    path = _dir(root) / "baseline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"files": files, "at": datetime.now(UTC).isoformat(timespec="seconds"), "why": why}
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")


def halted(root: Path | None = None) -> str:
    """Why every agent is halted, or '' when they are not."""
    path = home(root) / HALT_FILE
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip() or "halted by the guardian"


def trips(root: Path | None = None, limit: int = 50) -> list[Trip]:
    path = _dir(home(root)) / "log.jsonl"
    if not path.exists():
        return []
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    return [Trip(**{k: r[k] for k in ("rule", "agent", "action", "why", "at")}) for r in rows][
        -limit:
    ]


def _already(root: Path, trip: Trip) -> bool:
    """Acting again would change nothing: already off, already halted, already said."""
    from eulerlab.agents import spec

    if trip.action == "suspend":
        settings = spec.read_settings(root).get(trip.agent)
        return settings is not None and settings.enabled is False
    if trip.action == "halt":
        return bool(halted(root))
    return any(old.rule == trip.rule and old.why == trip.why for old in trips(root, limit=500))


def act(trip: Trip, root: Path, *, tell: Callable[[str], None] | None = None) -> Trip:
    from eulerlab.agents import lessons, spec

    stamped = Trip(**{**asdict(trip), "at": datetime.now(UTC).isoformat(timespec="seconds")})
    if trip.action == "suspend":
        # an agent that is not defined has nothing to switch off
        with contextlib.suppress(KeyError):
            spec.write_setting(trip.agent, enabled=False, root=root)
    elif trip.action == "halt":
        (root / HALT_FILE).write_text(f"{trip.rule}: {trip.why}\n", encoding="utf-8")
    _log(root, stamped)
    lessons.add(
        f"Guardian {trip.action} ({trip.rule}): {trip.why}",
        source="guardian",
        ref=f"guardian {trip.rule} {trip.agent} {stamped.at}",
        agents=(trip.agent,) if trip.agent != "all" else (lessons.ALL,),
        root=root,
    )
    message = f"Guardian {trip.action}: {trip.agent} — {trip.why}"
    (tell or _tell)(message)
    if trip.action == "halt":
        _write_escalation(root, {"since": stamped.at, "sent": [0]})
    return stamped


# --- halt escalation (ADR-217) -----------------------------------------------------------

# ASSUMPTION: A-125 — chosen by hand, like the thresholds above.
ESCALATE_HOURS = (2, 8)
"""A halt is told when it starts (hour 0) and again at these ages; then `make health` shows it."""


def _escalation_path(root: Path) -> Path:
    return _dir(root) / "escalation.json"


def _write_escalation(root: Path, body: dict[str, Any]) -> None:
    path = _escalation_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body), encoding="utf-8")


def halt_state(root: Path | None = None) -> dict[str, Any]:
    """{"why", "since", "sent"} of the current halt, or {} when there is none."""
    root = home(root)
    why = halted(root)
    if not why:
        return {}
    try:
        body = dict(json.loads(_escalation_path(root).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        body = {}
    if not body.get("since"):
        # a halt written by hand, or before escalation existed: dated by the file
        mtime = (root / HALT_FILE).stat().st_mtime
        since = datetime.fromtimestamp(mtime, UTC).isoformat(timespec="seconds")
        body = {"since": since, "sent": []}
    return {"why": why, "since": str(body["since"]), "sent": [int(h) for h in body.get("sent", [])]}


def escalate(
    root: Path | None = None,
    now: datetime | None = None,
    *,
    tell: Callable[[str], None] | None = None,
) -> list[str]:
    """Send the halt's next due line (start, 2 h, 8 h); return what was sent.

    The hourly `halt-watch` job runs it: a halted runtime starts no agent, so
    no run would reach the guardian to say the halt is still on."""
    root = home(root)
    state = halt_state(root)
    if not state:
        _escalation_path(root).unlink(missing_ok=True)
        return []
    now = now or datetime.now(UTC)
    hours = (now - datetime.fromisoformat(state["since"])).total_seconds() / 3600
    sent: list[int] = state["sent"]
    lines: list[str] = []
    if 0 not in sent:
        lines.append(f"Guardian halt: all — {state['why']}")
        sent.append(0)
    due = [h for h in ESCALATE_HOURS if h <= hours and h not in sent]
    if due:
        # one line for the age reached, even when the job missed an earlier one
        lines.append(
            f"Guardian halt still on after {int(hours)} h (since {state['since'][:16]} UTC): "
            f"{state['why'][:300]}. No agent has run since. Lift it with "
            "`make agents-resume REASON=...` once the change is understood."
        )
        sent.extend(due)
    for line in lines:
        (tell or _tell)(line)
    _write_escalation(root, {"since": state["since"], "sent": sorted(sent)})
    return lines


def _tell(text: str) -> None:
    from eulerlab import notify

    if notify.configured():
        with contextlib.suppress(Exception):
            notify.send(text)


def check(facts: Facts, rules: Iterable[Rule] = RULES) -> list[Trip]:
    found = []
    for rule in rules:
        trip = rule(facts)
        if trip is not None:
            found.append(trip)
    return found


def after_run(
    output: Any,
    root: Path | None = None,
    now: datetime | None = None,
    *,
    repo: Path = Path("."),
    tell: Callable[[str], None] | None = None,
) -> list[Trip]:
    """Check every rule against this run; act on new trips. Never raises."""
    root = home(root)
    try:
        from eulerlab.agents import runtime

        recent = runtime.outputs(output.agent, root, limit=10)
        if not recent or recent[0].run_id != output.run_id:
            recent = [output, *recent]
        facts = Facts(output, recent, root, now or datetime.now(UTC), repo)
        acted = []
        for trip in check(facts):
            if not _already(root, trip):
                acted.append(act(trip, root, tell=tell))
        return acted
    except Exception as exc:  # the run it inspects must not fail because of it
        try:
            path = _dir(root) / "errors.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                row = {"at": datetime.now(UTC).isoformat(), "error": f"{type(exc).__name__}: {exc}"}
                handle.write(json.dumps(row) + "\n")
        except OSError:
            pass
        return []


def clear(reason: str, root: Path | None = None, repo: Path = Path(".")) -> str:
    """The operator lifts a halt and accepts the protected files as they are now."""
    if len(reason.strip()) < 5:
        msg = "say why (REASON=...), at least a few words"
        raise ValueError(msg)
    root = home(root)
    was = halted(root)
    (root / HALT_FILE).unlink(missing_ok=True)
    _write_baseline(root, fingerprints(repo), why=reason.strip()[:300])
    _escalation_path(root).unlink(missing_ok=True)
    _log(root, Trip("cleared", "all", "hold", reason.strip()[:300]))
    return was


def main(argv: list[str] | None = None) -> int:
    """Operator commands: `status`, `escalate` (the hourly job), and `clear --reason`."""
    import argparse

    parser = argparse.ArgumentParser(description="The agents' guardian (ADR-152).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("escalate", help="send a halt's start, 2 h and 8 h lines when due")
    c = sub.add_parser("clear")
    c.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    if args.cmd == "escalate":
        for line in escalate():
            print(line)
        return 0
    if args.cmd == "clear":
        was = clear(args.reason)
        print(f"halt lifted ({was or 'none was set'}); protected files re-baselined")
        return 0
    why = halted()
    print(f"halted: {why}" if why else "running: no halt")
    for t in trips(limit=15):
        print(f"{t.at}  {t.action:8} {t.agent:14} {t.rule}: {t.why[:120]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
