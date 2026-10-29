"""The agent log: every run, brief and approval, hash-chained like the trial ledger.

`data/agents/log.jsonl`. Each entry carries the hash of the one before it, so
deleting or editing a row breaks every link after it (`verify`). The same
construction as `validation/ledger.py`, kept separate on purpose: agent runs
are not trials, and nothing here may raise or lower the trial count.

What is logged: which agent ran, under which brief, with which model, how many
requests it used, what it wrote, and every operator decision on its inbox.
What is not: model replies or paper text. Those stay in the run's own folder.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eulerlab.agents.spec import home

GENESIS = "0" * 64
_LOCK = threading.Lock()


@dataclass(frozen=True)
class Entry:
    seq: int
    at: str
    kind: str
    """run · brief · decision · setting"""
    agent: str
    detail: dict[str, Any]
    prev_hash: str
    entry_hash: str

    def payload(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "at": self.at,
            "kind": self.kind,
            "agent": self.agent,
            "detail": self.detail,
            "prev_hash": self.prev_hash,
        }


def path_for(root: Path | None = None) -> Path:
    root = home(root)
    return root / "log.jsonl"


def compute_hash(payload: dict[str, Any]) -> str:
    material = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(material.encode()).hexdigest()


def read(root: Path | None = None) -> list[Entry]:
    root = home(root)
    path = path_for(root)
    if not path.exists():
        return []
    out: list[Entry] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        out.append(
            Entry(
                seq=int(row["seq"]),
                at=str(row["at"]),
                kind=str(row["kind"]),
                agent=str(row["agent"]),
                detail=dict(row["detail"]),
                prev_hash=str(row["prev_hash"]),
                entry_hash=str(row["entry_hash"]),
            )
        )
    return out


def append(
    kind: str,
    agent: str,
    detail: dict[str, Any],
    *,
    root: Path | None = None,
    at: datetime | None = None,
) -> Entry:
    """Add one entry linked to the last. No update and no delete exist."""
    root = home(root)
    with _LOCK:
        existing = read(root)
        payload: dict[str, Any] = {
            "seq": len(existing) + 1,
            "at": (at or datetime.now(UTC)).isoformat(timespec="seconds"),
            "kind": kind,
            "agent": agent,
            "detail": json.loads(json.dumps(detail, default=str)),
            "prev_hash": existing[-1].entry_hash if existing else GENESIS,
        }
        entry = Entry(**payload, entry_hash=compute_hash(payload))
        path = path_for(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(entry), sort_keys=True) + "\n")
        return entry


def verify(root: Path | None = None) -> tuple[bool, str]:
    """Whether every link holds. Returns (ok, the first problem found)."""
    root = home(root)
    previous = GENESIS
    for index, entry in enumerate(read(root), start=1):
        if entry.seq != index:
            return False, f"entry {index} has seq {entry.seq}: a row was removed or reordered"
        if entry.prev_hash != previous:
            return False, f"entry {entry.seq} does not link to the one before it"
        if compute_hash(entry.payload()) != entry.entry_hash:
            return False, f"entry {entry.seq} was edited after it was written"
        previous = entry.entry_hash
    return True, ""


def requests_on(agent: str, day: str, root: Path | None = None) -> int:
    """Model requests one agent used on one IST day, from its run entries."""
    root = home(root)
    used = 0
    for entry in read(root):
        if entry.kind == "run" and entry.agent == agent and entry.detail.get("ist_day") == day:
            used += int(entry.detail.get("requests", 0))
    return used
