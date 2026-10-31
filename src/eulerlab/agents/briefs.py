"""The operator's briefs: instructions and context that steer what agents look at.

Written from the control room or Telegram (`instruct <agent> <text>`), kept in
`data/agents/briefs.jsonl`, append-only. The newest brief for an agent, plus
the newest brief for `all`, is what its next run sees, and the run records the
ids of both, so any output can be traced to the words that produced it.

**What a brief can and cannot do.** It is text handed to the agent as the
operator's wishes. It can change which papers the research agent reads, what
the market brief dwells on, which datasets the data agent looks at first. It
cannot switch off the gate, raise a budget, or reach a tool the agent's
definition does not allow, because none of those are read from the brief.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from eulerlab.agents import log
from eulerlab.agents.spec import home

ALL = "all"
MAX_CHARS = 4000


@dataclass(frozen=True)
class Brief:
    id: str
    agent: str
    text: str
    at: str
    by: str
    """Where it came from: control-room, telegram, cli."""


def _path(root: Path) -> Path:
    return root / "briefs.jsonl"


def read_all(root: Path | None = None) -> list[Brief]:
    root = home(root)
    path = _path(root)
    if not path.exists():
        return []
    out: list[Brief] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            out.append(Brief(**{k: str(row[k]) for k in ("id", "agent", "text", "at", "by")}))
    return out


def write(agent: str, text: str, *, by: str = "cli", root: Path | None = None) -> Brief:
    """Save a brief. An empty text clears the agent's brief (an empty brief is saved)."""
    root = home(root)
    clean = text.strip()[:MAX_CHARS]
    at = datetime.now(UTC).isoformat(timespec="seconds")
    digest = hashlib.sha256(f"{agent}|{at}|{clean}".encode()).hexdigest()[:12]
    brief = Brief(id=f"b-{digest}", agent=agent, text=clean, at=at, by=by)
    path = _path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(brief)) + "\n")
    log.append("brief", agent, {"brief": brief.id, "by": by, "chars": len(clean)}, root=root)
    return brief


def current(agent: str, root: Path | None = None) -> Brief | None:
    """The newest brief for one agent, or None. An empty newest brief is None."""
    root = home(root)
    latest: Brief | None = None
    for brief in read_all(root):
        if brief.agent == agent:
            latest = brief
    return latest if latest is not None and latest.text else None


def for_run(agent: str, root: Path | None = None) -> tuple[str, list[str]]:
    """The text an agent's run sees, and the ids it came from."""
    root = home(root)
    parts: list[str] = []
    ids: list[str] = []
    for name, label in ((ALL, "For every agent"), (agent, "For you")):
        brief = current(name, root)
        if brief is not None:
            parts.append(f"{label} ({brief.at[:10]}): {brief.text}")
            ids.append(brief.id)
    return "\n".join(parts), ids


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="agent-brief", description="Give an agent standing context."
    )
    parser.add_argument("agent")
    parser.add_argument("text")
    args = parser.parse_args(argv)
    from eulerlab.agents.spec import load_specs

    if args.agent != ALL and args.agent not in load_specs():
        print(f"no agent named {args.agent!r}")
        return 2
    saved = write(args.agent, args.text, by="cli")
    print(f"brief {saved.id} saved for {args.agent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
