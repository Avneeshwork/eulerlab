"""The holdout boundary, and the machinery that refuses to cross it.

`CLAUDE.md`: *The holdout dataset is read exactly once, by the operator's
action. Never read it to "check something".*

A rule like that survives exactly as long as it is inconvenient and not
enforced. So the boundary is data, the enforcement is code, and `make validate`
cannot reach past it even if asked — the panel is truncated before any analysis
sees it, rather than each analysis being trusted to stop.

The asymmetry is deliberate. Accidentally *excluding* data costs a little
statistical power and is visible in the reported sample size. Accidentally
*including* it destroys the only untouched evidence the project has, silently
and permanently, and no later analysis can undo it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from eulerlab.features.panel import PanelRow


@dataclass(frozen=True)
class Holdout:
    starts: date
    status: str

    @property
    def is_unread(self) -> bool:
        return self.status == "unread"


@dataclass(frozen=True)
class Hypothesis:
    id: str
    title: str
    claim: str
    configurations: list[dict[str, object]]
    red_flags: list[str]
    holdout: Holdout
    status: str


def load(path: Path) -> Hypothesis:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    holdout_raw = raw.get("holdout", {})
    return Hypothesis(
        id=str(raw["id"]),
        title=str(raw["title"]),
        claim=str(raw["claim"]).strip(),
        configurations=list(raw.get("configurations", [])),
        red_flags=[str(f).strip() for f in raw.get("red_flags", [])],
        holdout=Holdout(
            starts=holdout_raw["starts"]
            if isinstance(holdout_raw.get("starts"), date)
            else date.fromisoformat(str(holdout_raw.get("starts", "2099-01-01"))),
            status=str(holdout_raw.get("status", "unread")),
        ),
        status=str(raw.get("status", "unknown")),
    )


def truncate(rows: Sequence[PanelRow], holdout: Holdout) -> tuple[list[PanelRow], int]:
    """Drop everything on or after the holdout boundary. Returns (kept, dropped).

    Applied once, at the top of the run, so no downstream analysis has the
    option of reaching past it. Enforcing this per-analysis would mean trusting
    every future caller to remember.
    """
    kept = [r for r in rows if r.day < holdout.starts]
    return kept, len(rows) - len(kept)
