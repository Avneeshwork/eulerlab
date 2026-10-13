"""Strategies the operator has put away, per workspace (ADR-069).

Operator, 2026-10-13: "add option in strategy library to archieve some
strategies and undo if wanted". The library lists every strategy ever
registered, and most have been rejected; the dead ones crowd the live ones.

Archiving hides a strategy from the library's default view and does nothing
else. Its results, reports, trials and any running deployment are untouched:
the trial ledger counts every configuration ever evaluated, and a strategy
that could be made to vanish from it would lower the bar for the rest.
Restoring removes the entry and the strategy is back exactly as it was.

One small JSON file, `workspaces/<id>/archived_strategies.json`, mapping a
strategy id to the day it was archived.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from eulerlab.workspace import Workspace

FILE = "archived_strategies.json"
MAX_IDS = 500
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


def _path(workspace: Workspace) -> Path:
    return workspace.root / FILE


def read(workspace: Workspace) -> dict[str, str]:
    """{strategy id: ISO date archived}. Empty when nothing is, or the file is unreadable."""
    path = _path(workspace)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items() if _ID.fullmatch(str(key))}


def change(
    workspace: Workspace, ids: Iterable[str], *, archived: bool, today: str = ""
) -> dict[str, str]:
    """Archive or restore `ids` and return the new list.

    Safe to repeat: archiving twice keeps the first date, restoring something
    that is not archived changes nothing. An id that is not a plain strategy
    id is refused before anything is written.
    """
    wanted = list(dict.fromkeys(ids))
    bad = [strategy for strategy in wanted if not _ID.fullmatch(strategy)]
    if bad:
        msg = f"{bad[0]!r} is not a strategy id"
        raise ValueError(msg)
    if len(wanted) > MAX_IDS:
        msg = f"at most {MAX_IDS} strategies at a time"
        raise ValueError(msg)
    held = read(workspace)
    stamp = today or datetime.now(UTC).date().isoformat()
    for strategy in wanted:
        if archived:
            held.setdefault(strategy, stamp)
        else:
            held.pop(strategy, None)
    path = _path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".partial")
    tmp.write_text(json.dumps(held, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    return held
