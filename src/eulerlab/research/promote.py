"""An approved idea-lab survivor goes to the gate: register it, validate it, gate it (ADR-116).

    operator approves a lab survivor in the inbox (`POST /api/agents/inbox/<id>`)
        -> `eligible(item)`: a lab finding with survivors, a card that exists,
           every configuration with a liquidity floor, not registered before
        -> `register(card)`: hypotheses/H-NNNN.yaml, a fresh id, the card's own
           configurations unchanged (pre-registration), status `draft`
        -> `make validate H=` then `make gate H=`, each in its own process
           (the panel is too large to load twice inside the web server)
        -> data/agents/promote/<H-id>.json   the verdict and both outputs

Nothing here decides anything. The gate (`gates.py`) and the mandate are run
as they are, the validation logs itself as a trial, and the gate appends its
own ledger entry. The holdout is never read: `gate_run` is called without
`--read-holdout`, which stays the operator's command.

The operator chose on 2026-11-01 that approving a survivor runs the gate with
no further tap. Cards tested before the liquidity floor (ADR-112) are refused,
so the fifteen survivors approved that morning are not gated by this.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from eulerlab.paths import data_path
from eulerlab.research import card as card_mod

FOLDER = data_path("agents/promote")
MARKER = "registered.json"
"""Written beside a lab card once it is registered, so one card is never registered twice."""

TIMEOUT_S = 3 * 60 * 60

Runner = Callable[[Sequence[str]], tuple[int, str]]


class Refused(ValueError):
    """This item cannot go to the gate; the message says why."""


@dataclass
class Promotion:
    item: str
    card: str
    hypothesis: str = ""
    verdict: str = ""
    """PROMOTE or KILL from the gate, or why it never reached the gate."""
    started: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    finished: str = ""
    validate_output: str = ""
    gate_output: str = ""


def eligible(agent: str, item: Any) -> Path:
    """The card to register for an approved inbox item. Raises `Refused` otherwise."""
    if agent != "lab":
        raise Refused(f"only idea lab survivors go to the gate from the inbox, not {agent}")
    data = item.data if isinstance(item.data, dict) else {}
    if int(data.get("survivors", 0) or 0) < 1 or not item.ref:
        raise Refused("not a survivor: nothing to gate")
    path = Path(item.ref)
    path = path / "card.yaml" if path.is_dir() else path
    if not path.exists():
        raise Refused(f"the card is gone: {path}")
    if (path.parent / MARKER).exists():
        raise Refused(f"already registered: {(path.parent / MARKER).read_text().strip()}")
    spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    configs = spec.get("configurations") or []
    if not configs or not all(float(c.get("min_turnover", 0) or 0) > 0 for c in configs):
        raise Refused(
            "tested before the liquidity floor (ADR-112); retest it with today's rules before the gate"
        )
    return path


def register(path: Path, hypotheses: Path = card_mod.HYPOTHESES) -> str:
    """Write the card into `hypotheses/` under a fresh id. Its configurations are not touched."""
    spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    hid = card_mod.next_id(hypotheses)
    spec["id"] = hid
    spec["status"] = "draft"
    hypotheses.mkdir(parents=True, exist_ok=True)
    target = hypotheses / f"{hid}.yaml"
    if target.exists():
        raise Refused(f"{target} exists; ids are never reused")
    target.write_text(
        yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=80), encoding="utf-8"
    )
    (path.parent / MARKER).write_text(
        json.dumps({"hypothesis": hid, "at": datetime.now(UTC).isoformat(timespec="seconds")})
        + "\n",
        encoding="utf-8",
    )
    return hid


def _run(cmd: Sequence[str]) -> tuple[int, str]:
    done = subprocess.run(list(cmd), capture_output=True, text=True, check=False, timeout=TIMEOUT_S)
    return done.returncode, (done.stdout + done.stderr)[-6000:]


def commands(hid: str) -> list[list[str]]:
    """Validate, then gate. Fixed arguments; never `--read-holdout`."""
    py = sys.executable
    return [
        [py, "-m", "eulerlab.validation.run", "--hypothesis", hid],
        [py, "-m", "eulerlab.gate_run", "--hypothesis", hid],
    ]


def _verdict(gate_output: str) -> str:
    """The gate's own `VERDICT:` line (`gates.Decision.render`)."""
    for line in gate_output.splitlines():
        if line.startswith("VERDICT:"):
            return line.removeprefix("VERDICT:").strip()[:200]
    return "no verdict printed"


_FINDING = re.compile(r"^  (pass|KILL)  (.{38,}?) (.*)$")
"""`Finding.line`: the rule padded to 38 characters, a space, then the detail."""


def findings(gate_output: str) -> list[dict[str, Any]]:
    """Each rule the gate printed (`gates.Finding.line`), in the gate's order, with its value and threshold.

    Read back from the gate's own output, so the panel shows exactly what the
    gate judged; nothing is recomputed here.
    """
    out: list[dict[str, Any]] = []
    for line in gate_output.splitlines():
        match = _FINDING.match(line)
        if match:
            mark, rule, detail = match.groups()
            out.append({"rule": rule.strip(), "passed": mark == "pass", "detail": detail.strip()})
    return out


def gate(
    item_id: str,
    path: Path,
    *,
    hypotheses: Path = card_mod.HYPOTHESES,
    folder: Path = FOLDER,
    run: Runner = _run,
) -> Promotion:
    """Register the card, validate it and gate it. Writes the result; never raises for a failed step."""
    out = Promotion(item=item_id, card=str(path))
    try:
        out.hypothesis = register(path, hypotheses)
        validate_cmd, gate_cmd = commands(out.hypothesis)
        code, out.validate_output = run(validate_cmd)
        if code != 0:
            out.verdict = f"validation stopped (exit {code}); see validate_output"
        else:
            _, out.gate_output = run(gate_cmd)
            out.verdict = _verdict(out.gate_output)
    except Refused as exc:
        out.verdict = f"refused: {exc}"
    except Exception as exc:  # recorded for the operator, not raised into the web server
        out.verdict = f"error: {type(exc).__name__}: {str(exc)[:300]}"
    out.finished = datetime.now(UTC).isoformat(timespec="seconds")
    folder.mkdir(parents=True, exist_ok=True)
    name = out.hypothesis or item_id.replace("/", "_")
    (folder / f"{name}.json").write_text(json.dumps(asdict(out), indent=2), encoding="utf-8")
    return out


def results(folder: Path = FOLDER, limit: int = 50) -> list[dict[str, Any]]:
    """Recent promotions, newest first."""
    if not folder.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in folder.glob("*.json"):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        row["findings"] = findings(str(row.get("gate_output", "")))
        rows.append(row)
    rows.sort(key=lambda r: str(r.get("started", "")), reverse=True)
    return rows[:limit]
