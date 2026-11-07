"""The research pipeline and its results, as the AI tab's Overview and Results show them (ADR-151).

    find   the research agent reads papers and drafts cards
    write  the autopilot writes rules and commits them before any test (ADR-150)
    test   the idea lab and the autopilot's rule screen backtest them
    gate   unchanged `make validate` and `make gate` decide PROMOTE, PAPER or KILL
    paper  a pass gets a paper book; live money stays the operator's decision

This module only reads what the agents already wrote: their run outputs, the
gate results of approved survivors (`research/promote.py`), the autopilot's
cards and their result lines, and the deployments. It decides nothing and
starts nothing. Each result carries a one-line `meaning` so a new reader can
tell what happened without knowing the agents' vocabulary.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from eulerlab.agents import runtime
from eulerlab.agents.runtime import Output

HYPOTHESES = Path("hypotheses")
DAYS = 7
"""The Overview's numbers cover the last week."""
RESULTS_SHOWN = 60
PIPELINE = ("research", "autopilot", "lab", "skeptic")
"""Agents whose every run is a research result; the rest are support checks."""

STAGES: list[dict[str, Any]] = [
    {
        "key": "find",
        "title": "Find ideas",
        "agents": ["research"],
        "what": "Reads papers on a topic and drafts strategy ideas. Nothing is tested yet.",
    },
    {
        "key": "write",
        "title": "Write rules",
        "agents": ["autopilot"],
        "what": "Turns ideas into exact stock rules and commits them before any test, "
        "so a result cannot be picked after the fact.",
    },
    {
        "key": "test",
        "title": "Backtest",
        "agents": ["lab", "autopilot"],
        "what": "Tests each idea on 2015-2024 prices after costs. Most fail here; that is normal.",
    },
    {
        "key": "gate",
        "title": "Gate",
        "agents": [],
        "what": "Fixed validation and gate code gives PROMOTE, PAPER or KILL. A KILL is final.",
    },
    {
        "key": "paper",
        "title": "Paper trade",
        "agents": ["portfolio"],
        "what": "A pass trades on paper with live prices. Real money is always your decision.",
    },
]

# What each supporting agent's result means, for the result card.
SUPPORT_MEANING = {
    "data": "Data upkeep: how many datasets are clean enough to backtest on.",
    "market_brief": "The market brief: what moved and what to watch.",
    "watchdog": "Checks the other agents: failed runs, open problems, model use.",
    "operations": "Checks scheduled jobs ran on time.",
    "engineering": "Code quality checks and fixes waiting for you.",
    "portfolio": "Sizes passed strategies and watches the paper books.",
    "knowledge_keeper": "Keeps the knowledge base current.",
    "knowledge": "Rebuilds the index the Ask box reads from.",
    "head_research": "Head of Research: tasks and plans for the research team.",
    "head_platform": "Head of Data and Platform: tasks and plans.",
    "head_portfolio": "Head of Portfolio and Risk: tasks and plans.",
}


def _parse(at: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(at)
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _recent(at: str, since: datetime) -> bool:
    moment = _parse(at)
    return moment is not None and moment >= since


def verdict_word(verdict: str) -> str:
    """The gate's first word: PROMOTE, PAPER, KILL, or the reason it never reached the gate."""
    word = (verdict or "").split(" ")[0].strip(" —:")
    return word.upper() if word.upper() in {"PROMOTE", "PAPER", "KILL"} else verdict


def outcome_of(verdict: str) -> str:
    word = verdict_word(verdict)
    if word == "PROMOTE":
        return "pass"
    if word == "PAPER":
        return "partial"
    if word == "KILL":
        return "fail"
    return "info"


VERDICT_MEANING = {
    "PROMOTE": "Passed every gate rule. It gets a paper book; live money is still your call.",
    "PAPER": "Good enough to trade on paper for more evidence, not for real money yet.",
    "KILL": "Failed the gate. It is closed and will not be tuned and retried.",
}


def card_result(hypothesis: str, root: Path = HYPOTHESES) -> str:
    """The `result:` line the autopilot writes into a card after its screen."""
    path = root / f"{hypothesis}.yaml"
    if not path.exists():
        return ""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return ""
    return str(raw.get("result", "")) if isinstance(raw, dict) else ""


def _autopilot_rows(output: Output, hypotheses: Path) -> list[dict[str, str]]:
    data = output.data
    survivors = set(data.get("survivors") or [])
    gates = {str(g.get("hypothesis")): str(g.get("verdict", "")) for g in data.get("gates") or []}
    rows = []
    for card in data.get("cards") or []:
        h = str(card.get("id", ""))
        if h in gates:
            status, tone = verdict_word(gates[h]), outcome_of(gates[h])
        elif h in survivors:
            status, tone = "Passed test, waiting for gate", "partial"
        else:
            status, tone = "Failed test", "fail"
        rows.append(
            {
                "id": h,
                "label": str(card.get("rule", "")),
                "tag": str(card.get("kind", "")),
                "status": status,
                "tone": tone,
                "detail": card_result(h, hypotheses),
                "ref": f"hypotheses/{h}.yaml",
            }
        )
    return rows


def _lab_rows(output: Output) -> list[dict[str, str]]:
    rows = []
    for r in output.data.get("results") or []:
        screens = r.get("screens") or []
        best = max((abs(float(s.get("t_stat") or 0)) for s in screens), default=0.0)
        passed = any(s.get("passed") for s in screens)
        survived = bool(r.get("survivors"))
        status = "Survived" if survived else "Passed screen" if passed else "No edge"
        rows.append(
            {
                "id": str(r.get("card", "")),
                "label": str(r.get("stopped") or r.get("card", "")),
                "tag": str(r.get("family", "")),
                "status": status,
                "tone": "pass" if survived else "partial" if passed else "fail",
                "detail": f"{len(screens)} signal(s) screened, best |t| {best:.2f}"
                + (f"; window {r['window']}" if r.get("window") else ""),
                "ref": str(r.get("path", "")),
            }
        )
    return rows


def _item_rows(output: Output) -> list[dict[str, str]]:
    tone = {"critical": "fail", "warn": "partial", "warning": "partial"}
    return [
        {
            "id": "",
            "label": i.title,
            "tag": i.kind,
            "status": i.severity,
            "tone": tone.get(i.severity, "info"),
            "detail": i.body[:600],
            "ref": i.ref,
        }
        for i in output.items
    ]


def result_of(output: Output, hypotheses: Path = HYPOTHESES) -> dict[str, Any]:
    """One agent run as a result card: what it was, what came out, and what that means."""
    base: dict[str, Any] = {
        "id": f"{output.agent}/{output.run_id}",
        "agent": output.agent,
        "at": output.finished or output.started,
        "status": output.status,
        "summary": output.summary,
        "model": output.model,
        "notes": output.notes,
    }
    if output.status not in ("ok", "skipped"):
        return {
            **base,
            "kind": "problem",
            "title": f"{output.agent} run did not finish",
            "outcome": "fail",
            "meaning": "This run stopped or failed. The agent tries again at its next scheduled time.",
            "rows": [],
        }
    if output.agent == "autopilot":
        rows = _autopilot_rows(output, hypotheses)
        gated = [r for r in rows if r["status"] in VERDICT_MEANING]
        passes = [r for r in gated if r["tone"] in ("pass", "partial")]
        waiting = [r for r in rows if r["status"].startswith("Passed test")]
        return {
            **base,
            "kind": "batch",
            "title": f"Autopilot batch: {len(rows)} rules written and tested",
            "outcome": "pass" if passes else "info",
            "meaning": f"{len(rows) - len(gated) - len(waiting)} failed the backtest, "
            f"{len(waiting)} passed and wait for the gate, {len(gated)} gated "
            f"({len(passes)} passed).",
            "rows": rows,
            "ref": str(output.data.get("note", "")),
        }
    if output.agent == "lab":
        rows = _lab_rows(output)
        survived = sum(r["status"] == "Survived" for r in rows)
        return {
            **base,
            "kind": "test",
            "title": f"Idea lab: {len(rows)} idea(s) backtested",
            "outcome": "pass" if survived else "info",
            "meaning": (
                f"{survived} survived and wait for your approval in Needs you."
                if survived
                else "None showed an edge after costs, so none go further."
            ),
            "rows": rows,
        }
    if output.agent == "research":
        drafts = [r for r in _item_rows(output) if r["tag"] == "draft"]
        topic = str(output.data.get("topic", ""))
        return {
            **base,
            "kind": "ideas",
            "title": f"Research: {len(drafts)} idea(s) drafted"
            + (f" on “{topic}”" if topic else ""),
            "outcome": "info",
            "meaning": "Drafts are ideas from papers, not results. The idea lab tests them next.",
            "rows": drafts,
        }
    if output.agent == "skeptic":
        rows = _item_rows(output)
        bad = sum(r["tone"] == "fail" for r in rows)
        return {
            **base,
            "kind": "attack",
            "title": f"Skeptic: {output.summary.split(':')[0]}",
            "outcome": "fail" if bad else "pass",
            "meaning": (
                f"{bad} attack(s) found a problem that could make this result fake."
                if bad
                else "No attack broke this result."
            ),
            "rows": rows,
        }
    rows = [r for r in _item_rows(output) if r["tone"] in ("fail", "partial")]
    return {
        **base,
        "kind": "brief" if output.agent == "market_brief" else "check",
        "title": output.summary[:120] or output.agent,
        "outcome": "partial" if rows else "info",
        "meaning": SUPPORT_MEANING.get(output.agent, ""),
        "rows": rows,
    }


def gate_result(promotion: dict[str, Any]) -> dict[str, Any]:
    """A gate run of an approved survivor (`research/promote.py`) as a result card."""
    verdict = str(promotion.get("verdict", ""))
    word = verdict_word(verdict)
    finished = bool(promotion.get("finished"))
    h = str(promotion.get("hypothesis", "")) or str(promotion.get("card", "")).split("/")[-2:][0]
    rows = [
        {
            "id": str(f.get("rule", "")),
            "label": str(f.get("rule", "")),
            "tag": "rule",
            "status": "pass" if f.get("passed") else "fail",
            "tone": "pass" if f.get("passed") else "fail",
            "detail": str(f.get("detail", "")),
            "ref": "",
        }
        for f in promotion.get("findings") or []
    ]
    rows.sort(key=lambda r: r["tone"] == "pass")
    return {
        "id": f"gate/{promotion.get('item', h)}",
        "agent": "gate",
        "at": str(promotion.get("finished") or promotion.get("started", "")),
        "status": "ok" if finished else "running",
        "kind": "verdict",
        "title": f"{h}: {word if finished else 'at the gate now'}",
        "outcome": outcome_of(verdict) if finished else "info",
        "summary": verdict,
        "meaning": VERDICT_MEANING.get(word, "Validation and gate are running.")
        if finished
        else "Validation and gate are running.",
        "rows": rows,
        "model": "",
        "notes": [],
        "ref": f"hypotheses/{h}.yaml" if h.startswith("H-") else "",
    }


def paper_result(paper: dict[str, Any]) -> dict[str, Any]:
    """A paper book started for a strategy that passed."""
    strategy = str(paper.get("strategy_id", ""))
    active = paper.get("status") == "active"
    return {
        "id": f"paper/{paper.get('id', strategy)}",
        "agent": "paper",
        "at": str(paper.get("created_at", "")),
        "status": "ok",
        "kind": "paper",
        "title": f"{strategy}: paper book started",
        "outcome": "pass" if active else "info",
        "summary": f"{paper.get('id', '')}, capital {paper.get('capital', '')}, "
        f"status {paper.get('status', '')}",
        "meaning": "Trades on paper with live prices from its first session. No real money moves.",
        "rows": [],
        "model": "",
        "notes": [],
        "ref": "",
    }


def _autopilot_gates(output: Output) -> list[dict[str, Any]]:
    out = []
    for g in output.data.get("gates") or []:
        h, verdict = str(g.get("hypothesis", "")), str(g.get("verdict", ""))
        word = verdict_word(verdict)
        kept = (output.data.get("kept") or {}).get(h) or {}
        out.append(
            {
                "id": f"gate/autopilot/{output.run_id}/{h}",
                "agent": "gate",
                "at": output.finished or output.started,
                "status": "ok",
                "kind": "verdict",
                "title": f"{h}: {word}",
                "outcome": outcome_of(verdict),
                "summary": f"{verdict} (autopilot)"
                + (f"; report {kept.get('report')}; {kept.get('paper')}" if kept else ""),
                "meaning": VERDICT_MEANING.get(word, verdict),
                "rows": [],
                "model": "",
                "notes": [],
                "ref": f"hypotheses/{h}.yaml",
            }
        )
    return out


def _stage_numbers(
    stage: str,
    runs: dict[str, list[Output]],
    gates: Sequence[dict[str, Any]],
    papers: Sequence[dict[str, Any]],
    since: datetime,
) -> tuple[str, str]:
    """The stage's headline number for the last week, and a short line under it."""

    def week(name: str) -> list[Output]:
        return [o for o in runs.get(name, []) if o.status == "ok" and _recent(o.started, since)]

    if stage == "find":
        drafts = sum(sum(i.kind == "draft" for i in o.items) for o in week("research"))
        return str(drafts), "ideas drafted"
    if stage == "write":
        cards = sum(len(o.data.get("cards") or []) for o in week("autopilot"))
        return str(cards), "rules written"
    if stage == "test":
        lab = sum(len(o.data.get("results") or []) for o in week("lab"))
        auto = sum(len(o.data.get("cards") or []) for o in week("autopilot"))
        passed = sum(
            sum(bool(r.get("survivors")) for r in o.data.get("results") or []) for o in week("lab")
        ) + sum(len(o.data.get("survivors") or []) for o in week("autopilot"))
        return str(lab + auto), f"tested, {passed} passed"
    if stage == "gate":
        done = [g for g in gates if g["status"] == "ok" and _recent(g["at"], since)]
        passes = sum(g["outcome"] in ("pass", "partial") for g in done)
        return str(len(done)), f"gated, {passes} passed"
    active = [p for p in papers if p.get("status") == "active"]
    new = sum(_recent(str(p.get("created_at", "")), since) for p in active)
    return str(len(active)), f"paper books, {new} new"


def _last(runs: dict[str, list[Output]], names: Sequence[str]) -> dict[str, str]:
    latest = [o for n in names for o in runs.get(n, [])[:1]]
    if not latest:
        return {"at": "", "status": "never", "summary": "Has not run yet.", "agent": ""}
    newest = max(latest, key=lambda o: o.started)
    return {
        "at": newest.finished or newest.started,
        "status": newest.status,
        "summary": newest.summary,
        "agent": newest.agent,
    }


def build(
    *,
    now: datetime | None = None,
    root: Path | None = None,
    promotions: Sequence[dict[str, Any]] = (),
    papers: Sequence[dict[str, Any]] = (),
    names: Sequence[str] = (),
    hypotheses: Path = HYPOTHESES,
    days: int = DAYS,
) -> dict[str, Any]:
    """The pipeline stages with last week's numbers, and every result newest first."""
    now = now or datetime.now(UTC)
    since = now - timedelta(days=days)
    runs = {name: runtime.outputs(name, root, limit=20) for name in names}

    gates = [gate_result(p) for p in promotions]
    results: list[dict[str, Any]] = []
    for output in runs.get("autopilot", []):
        gates.extend(_autopilot_gates(output))
    for name, outputs in runs.items():
        kept = [o for o in outputs if o.status != "skipped"]
        # Research agents' every run is a result; a support agent's checks repeat
        # through the day, so only its newest run is shown.
        for output in kept if name in PIPELINE else kept[:1]:
            results.append(result_of(output, hypotheses))
    results.extend(gates)
    results.extend(paper_result(p) for p in papers if _recent(str(p.get("created_at", "")), since))
    for r in results:
        r["pipeline"] = r["agent"] in PIPELINE or r["agent"] in ("gate", "paper")
    results.sort(key=lambda r: r["at"], reverse=True)

    stages = []
    for spec in STAGES:
        number, label = _stage_numbers(spec["key"], runs, gates, papers, since)
        if spec["key"] == "gate":
            newest = max(gates, key=lambda g: g["at"], default=None)
            last = (
                {
                    "at": newest["at"],
                    "status": newest["status"],
                    "summary": newest["summary"],
                    "agent": "gate",
                }
                if newest
                else {"at": "", "status": "never", "summary": "Nothing gated yet.", "agent": ""}
            )
        elif spec["key"] == "paper":
            newest_paper = max(papers, key=lambda p: str(p.get("created_at", "")), default=None)
            last = (
                {
                    "at": str(newest_paper.get("created_at", "")),
                    "status": "ok",
                    "summary": f"Newest paper book: {newest_paper.get('strategy_id')}",
                    "agent": "portfolio",
                }
                if newest_paper
                else {"at": "", "status": "never", "summary": "No paper books.", "agent": ""}
            )
        else:
            last = _last(runs, spec["agents"])
        stages.append({**spec, "number": number, "label": label, "last": last})

    return {
        "ok": True,
        "days": days,
        "stages": stages,
        "results": results[:RESULTS_SHOWN],
    }
