"""The doctor: after every agent run, look for known trouble and act on it from a fixed list (ADR-113).

    runtime.run -> output.json -> doctor.after_run(output)
        -> problems found in the output and in stalled runs
        -> safe remedies, from REMEDIES only:
             stalled run      : close it with a failed output, so the card stops saying "running"
             too good to be true : flag it; it never reaches the inbox as a win
             model unavailable : note it; the next run tries again (the runtime already falls back)
             data refused     : log it; the work runner makes it a task for the data agent (ADR-124)
             code error       : queue it for the engineering agent, which fixes one file on a branch
        -> data/agents/doctor/log.jsonl   one line per problem and what was done

It never edits code, never deletes data, never trades, never touches the gate.
A problem with no remedy in the list is written down and shown to the operator.
It must never break the run it inspects: `after_run` swallows its own errors.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from eulerlab.agents.spec import home

FOLDER = "doctor"
LOG = "log.jsonl"
QUEUE = "code_queue.jsonl"
"""Code problems waiting for the engineering agent."""

STALLED_AFTER = timedelta(hours=3)
"""A run with no output and no step for this long has died (the lab's longest is 90 minutes)."""

SUSPECT_SHARPE = 3.0
"""A long-only daily rule above this robust Sharpe is far more likely a data or cost artefact than an edge."""
SUSPECT_T = 10.0
"""An IC t-statistic above this on overlapping monthly windows is more likely a bug than a signal."""

Kind = Literal["stalled", "suspicious", "model_down", "data_refused", "code_error"]
Remedy = Literal["closed_run", "flagged", "noted", "data_request", "queued_for_engineering"]

REMEDIES: dict[str, Remedy] = {
    "stalled": "closed_run",
    "suspicious": "flagged",
    "model_down": "noted",
    "data_refused": "data_request",
    "code_error": "queued_for_engineering",
}
"""The whole list. A remedy not here is not taken."""

MODEL_ERRORS = ("ModelUnavailable", "Refused", "BudgetSpent")
"""How a run's summary starts when the model, not the code, failed (`runtime.run`)."""

_RUN = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{6}")
"""A run folder's name (`runtime._run_id`); anything else under an agent's folder is not a run."""
_FRAME = re.compile(r'File "(?P<path>[^"]*?(?P<rel>src/eulerlab/[^"]+\.py))", line (?P<line>\d+)')


@dataclass
class Problem:
    kind: Kind
    agent: str
    run: str
    detail: str
    file: str = ""
    """For a code error: the repository path of the deepest frame inside src/eulerlab."""
    line: int = 0
    error: str = ""
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    remedy: str = ""


def suspect_file(text: str) -> tuple[str, int]:
    """The deepest `src/eulerlab/...` frame in a traceback, as (repo path, line)."""
    found = list(_FRAME.finditer(text))
    if not found:
        return "", 0
    last = found[-1]
    return last.group("rel"), int(last.group("line"))


def examine(output: Any) -> list[Problem]:
    """Problems visible in one finished run's output."""
    out: list[Problem] = []
    notes = "\n".join(output.notes)
    model_failed = output.status == "failed" and output.summary.startswith(MODEL_ERRORS)
    if model_failed:
        # A spent quota or a missing key is not a bug: the engineering agent
        # must not be sent to "fix" it (HISTORY #64).
        out.append(Problem("model_down", output.agent, output.run_id, output.summary[:300]))
    elif output.status == "failed":
        path, line = suspect_file(notes)
        if path:
            out.append(
                Problem(
                    "code_error",
                    output.agent,
                    output.run_id,
                    output.summary[:300],
                    file=path,
                    line=line,
                    error=notes[-3000:],
                )
            )
    if output.status == "refused" and ("grade" in output.summary or "data" in output.summary):
        out.append(Problem("data_refused", output.agent, output.run_id, output.summary[:300]))
    if not model_failed and ("no model ideas today" in notes or "Refused" in notes):
        out.append(Problem("model_down", output.agent, output.run_id, "the model did not answer"))
    for result in output.data.get("results", []) if isinstance(output.data, dict) else []:
        for screen in result.get("screens", []):
            if abs(float(screen.get("t_stat", 0.0))) > SUSPECT_T:
                out.append(
                    Problem(
                        "suspicious",
                        output.agent,
                        output.run_id,
                        f"{result.get('card')}: IC t-statistic {screen.get('t_stat')} on "
                        f"{screen.get('feature')}; check for lookahead or stale prices",
                    )
                )
        for bt in result.get("backtests", []):
            if float(bt.get("robust_sharpe", 0.0)) > SUSPECT_SHARPE:
                out.append(
                    Problem(
                        "suspicious",
                        output.agent,
                        output.run_id,
                        f"{result.get('card')}: robust Sharpe {bt.get('robust_sharpe')} for "
                        f"{bt.get('label')}; check which stocks it held and their turnover",
                    )
                )
    return out


def stalled_runs(root: Path, now: datetime, agents: Iterable[str]) -> list[Path]:
    """Run folders with no output.json whose last step is older than STALLED_AFTER."""
    out: list[Path] = []
    for name in agents:
        folder = root / name
        if not folder.is_dir():
            continue
        for run_dir in folder.iterdir():
            if (
                not run_dir.is_dir()
                or not _RUN.fullmatch(run_dir.name)
                or (run_dir / "output.json").exists()
            ):
                continue
            progress = run_dir / "progress.jsonl"
            stamp = progress if progress.exists() else run_dir
            last = datetime.fromtimestamp(stamp.stat().st_mtime, UTC)
            if now - last > STALLED_AFTER:
                out.append(run_dir)
    return out


def _close(run_dir: Path, now: datetime) -> None:
    """Write a failed output for a dead run, so the agent's card stops showing it as running."""
    payload = {
        "agent": run_dir.parent.name,
        "run_id": run_dir.name,
        "started": now.isoformat(timespec="seconds"),
        "finished": now.isoformat(timespec="seconds"),
        "status": "failed",
        "summary": "stopped without finishing (the computer slept, or the process was closed); "
        "closed by the doctor",
        "items": [],
        "notes": [f"no step for more than {STALLED_AFTER}; closed {now.isoformat()}"],
        "data": {"closed_by": "doctor"},
    }
    (run_dir / "output.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _append(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")


def treat(problems: list[Problem], root: Path) -> list[Problem]:
    """Take each problem's remedy from REMEDIES and write it down."""
    base = root / FOLDER
    for p in problems:
        p.remedy = REMEDIES[p.kind]
        if p.kind == "code_error":
            _append(base / QUEUE, asdict(p))
        _append(base / LOG, asdict(p))
    return problems


def after_run(output: Any, root: Path | None = None, now: datetime | None = None) -> list[Problem]:
    """Examine one run and the stalled runs of every agent. Never raises."""
    try:
        root = home(root)
        now = now or datetime.now(UTC)
        found = examine(output)
        agents = [p.name for p in root.iterdir() if p.is_dir() and p.name != FOLDER]
        for run_dir in stalled_runs(root, now, agents):
            _close(run_dir, now)
            found.append(Problem("stalled", run_dir.parent.name, run_dir.name, "no step for hours"))
        return treat(found, root)
    except Exception:  # the doctor must never fail the run it inspects
        return []


def queued(root: Path | None = None) -> list[Problem]:
    """Code problems waiting for the engineering agent, oldest first, one per file."""
    path = home(root) / FOLDER / QUEUE
    if not path.exists():
        return []
    seen: dict[str, Problem] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        p = Problem(**row)
        seen.setdefault(p.file, p)
    return list(seen.values())


def done(file: str, outcome: str, root: Path | None = None) -> None:
    """Take a file's problems off the queue, and log how they ended."""
    base = home(root) / FOLDER
    path = base / QUEUE
    if path.exists():
        keep = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and json.loads(line).get("file") != file
        ]
        path.write_text("".join(f"{line}\n" for line in keep), encoding="utf-8")
    _append(
        base / LOG,
        {"at": datetime.now(UTC).isoformat(timespec="seconds"), "file": file, "outcome": outcome},
    )
