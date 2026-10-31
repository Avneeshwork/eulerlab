"""The operator's inbox: every agent item that waits for a decision.

An item marked `needs_approval` stays here until the operator approves or
dismisses it. The decision is appended to `data/agents/decisions.jsonl` and
to the agent log; the item itself is never edited.

**Approving records a decision; it does not act.** Approving a research draft
does not register it, approving a data request does not download anything,
and approving a trade ticket does not send an order. Each of those stays the
operator's own command (`make paper-agent-approve`, the Instruments page, the
trade desk), so the inbox can never become a way for an agent to act through
a click the operator did not read.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from eulerlab.agents import log
from eulerlab.agents.runtime import Item, outputs
from eulerlab.agents.spec import home, load_specs

Decision = Literal["approved", "dismissed"]


@dataclass(frozen=True)
class Recorded:
    item: str
    agent: str
    decision: Decision
    note: str
    at: str


def _path(root: Path) -> Path:
    return root / "decisions.jsonl"


def decisions(root: Path | None = None) -> dict[str, Recorded]:
    root = home(root)
    path = _path(root)
    out: dict[str, Recorded] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            recorded = Recorded(
                item=str(row["item"]),
                agent=str(row["agent"]),
                decision=row["decision"],
                note=str(row.get("note", "")),
                at=str(row["at"]),
            )
            out[recorded.item] = recorded
    return out


def pending(root: Path | None = None, names: list[str] | None = None) -> list[dict[str, Any]]:
    """Items waiting for the operator, newest run first, one row per item."""
    root = home(root)
    decided = decisions(root)
    rows: list[dict[str, Any]] = []
    for name in names if names is not None else sorted(load_specs()):
        for output in outputs(name, root, limit=10):
            for item in output.items:
                if item.needs_approval and item.id not in decided:
                    rows.append(
                        {
                            "agent": name,
                            "run": output.run_id,
                            "at": output.started,
                            **item.model_dump(),
                        }
                    )
    rows.sort(key=lambda r: str(r["at"]), reverse=True)
    return rows


def find(
    item_id: str, root: Path | None = None, names: list[str] | None = None
) -> tuple[str, Item] | None:
    root = home(root)
    for name in names if names is not None else sorted(load_specs()):
        for output in outputs(name, root, limit=50):
            for item in output.items:
                if item.id == item_id:
                    return name, item
    return None


def decide(
    item_id: str,
    decision: Decision,
    *,
    note: str = "",
    root: Path | None = None,
    names: list[str] | None = None,
) -> Recorded:
    root = home(root)
    found = find(item_id, root, names)
    if found is None:
        msg = f"no agent item {item_id!r}"
        raise KeyError(msg)
    agent, item = found
    if not item.needs_approval:
        msg = f"{item_id} does not wait for a decision"
        raise ValueError(msg)
    if item_id in decisions(root):
        msg = f"{item_id} was already decided"
        raise ValueError(msg)
    recorded = Recorded(
        item=item_id,
        agent=agent,
        decision=decision,
        note=note.strip()[:500],
        at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    path = _path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(recorded)) + "\n")
    log.append("decision", agent, {"item": item_id, "decision": decision}, root=root)
    return recorded
