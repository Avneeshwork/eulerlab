"""The experiment store: every test of a rule, kept with its daily returns (ADR-172).

The trial ledger counts gate runs and `features/trials.py` counts parameter
sets. A screen (the autopilot's ten a night) was counted by neither, and none
of the three kept the daily returns, so two questions had no answer: how many
*different* ideas have been tried, and is tonight's rule one of them again.

One line per evaluation in `data/derived/experiments.jsonl`, appended only:

    id           hash of the line's content
    at           when it ran (UTC)
    purpose      screen | sweep | selection | gate | forward
    hypothesis   H-NNNN, or "" for a candidate that has no card
    fingerprint  the rule's own fingerprint (same rule, same fingerprint)
    family       the card's family, for the coverage map
    parents      ids of the experiments this one was changed from (its lineage)
    asked_by     the agent or person that ran it
    first, end   the window read
    metrics      what came out (count, net Sharpe, ...)
    returns      name of the file holding its daily net returns, or null

The daily returns are one JSON file per distinct series under
`data/derived/experiment_returns/`, named by the hash of its content, so the
same series tested twice is stored once.

**The forward period is sealed here.** A row whose window ends after the
constitution's `backtest_end` is refused unless its purpose is `forward`
(scoring the forward test, once). So nothing that finds or tunes a rule can
leave a record of reading 2026, and a caller that tries is stopped before it
can use the answer.

With `EULERLAB_DATABASE_URL` set the lines live in Postgres's `append_log`
(ADR-165), like the trials counter. The returns stay files.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from eulerlab import constitution
from eulerlab.db.stream import stream_for
from eulerlab.paths import data_path

PATH = data_path("derived/experiments.jsonl")
RETURNS = data_path("derived/experiment_returns")
KIND = "experiments"

Purpose = Literal["screen", "sweep", "selection", "gate", "forward"]
PURPOSES: tuple[Purpose, ...] = ("screen", "sweep", "selection", "gate", "forward")


class SealedPeriod(PermissionError):
    """A test that is not the forward test tried to read the forward period."""


def _path(path: Path | None) -> Path:
    return path if path is not None else PATH


def _root(root: Path | None) -> Path:
    return root if root is not None else RETURNS


def _returns_file(daily: Mapping[date, float], root: Path) -> str:
    body = json.dumps({d.isoformat(): round(v, 10) for d, v in sorted(daily.items())})
    name = hashlib.sha256(body.encode()).hexdigest()[:20] + ".json"
    path = root / name
    if not path.exists():
        root.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return name


def record(
    *,
    purpose: Purpose,
    fingerprint: str,
    first: date,
    end: date,
    metrics: Mapping[str, Any],
    daily: Mapping[date, float] | None = None,
    hypothesis: str = "",
    family: str = "",
    parents: Sequence[str] = (),
    asked_by: str = "",
    now: datetime | None = None,
    path: Path | None = None,
    returns_root: Path | None = None,
) -> str:
    """Append one evaluation. Returns its id."""
    if purpose not in PURPOSES:
        msg = f"purpose {purpose!r} is not one of {', '.join(PURPOSES)}"
        raise ValueError(msg)
    sealed = constitution.load().periods.backtest_end
    last = max([end, *(daily or {})])
    if purpose != "forward" and last > sealed:
        msg = (
            f"a {purpose} read {last}, after {sealed}: that is the forward test, which "
            "nothing that finds or tunes a rule may read (config/constitution.yaml)"
        )
        raise SealedPeriod(msg)
    at = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    row: dict[str, Any] = {
        "at": at,
        "purpose": purpose,
        "hypothesis": hypothesis,
        "fingerprint": fingerprint,
        "family": family,
        "parents": list(parents),
        "asked_by": asked_by,
        "first": first.isoformat(),
        "end": end.isoformat(),
        "metrics": dict(metrics),
        "returns": _returns_file(daily, _root(returns_root)) if daily else None,
    }
    body = json.dumps(row, sort_keys=True, default=str)
    row["id"] = hashlib.sha256(body.encode()).hexdigest()[:16]
    line = json.dumps(row, sort_keys=True, default=str)
    path = _path(path)
    stream = stream_for(path, KIND)
    if stream is not None:
        stream.append(lambda _last, _seq: (line, datetime.fromisoformat(at)))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    return str(row["id"])


def rows(path: Path | None = None, *, purpose: Purpose | None = None) -> list[dict[str, Any]]:
    """Every recorded evaluation, oldest first."""
    path = _path(path)
    stream = stream_for(path, KIND)
    if stream is not None:
        lines = stream.read()
    elif path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []
    out = [json.loads(line) for line in lines if line.strip()]
    return [r for r in out if purpose is None or r.get("purpose") == purpose]


def returns_of(row: Mapping[str, Any], returns_root: Path | None = None) -> dict[date, float]:
    """A row's daily net returns, or {} when it stored none."""
    name = row.get("returns")
    if not name:
        return {}
    try:
        raw = json.loads((_root(returns_root) / str(name)).read_text(encoding="utf-8"))
    except OSError:
        return {}
    return {date.fromisoformat(d): float(v) for d, v in raw.items()}


def universe(
    path: Path | None = None, returns_root: Path | None = None, *, skip: Sequence[str] = ()
) -> list[dict[date, float]]:
    """One daily-return series per distinct rule tried (by fingerprint), oldest first.

    `skip` leaves out fingerprints, so a rule is not counted against itself.
    """
    seen: dict[str, dict[date, float]] = {}
    for row in rows(path):
        key = str(row.get("fingerprint"))
        if key in seen or key in skip or row.get("purpose") == "forward":
            continue
        series = returns_of(row, returns_root)
        if series:
            seen[key] = series
    return list(seen.values())


def counts(path: Path | None = None, *, since: datetime | None = None) -> dict[str, int]:
    """Evaluations by purpose, plus `rules`: distinct fingerprints."""
    found = rows(path)
    if since is not None:
        found = [r for r in found if datetime.fromisoformat(str(r["at"])) >= since]
    out: dict[str, int] = dict(Counter(str(r.get("purpose")) for r in found))
    out["rules"] = len({r.get("fingerprint") for r in found})
    return out


def coverage(path: Path | None = None) -> dict[str, int]:
    """Distinct rules tried per family: where the search has already been."""
    seen: dict[str, set[str]] = {}
    for row in rows(path):
        seen.setdefault(str(row.get("family") or "unknown"), set()).add(str(row["fingerprint"]))
    return {k: len(v) for k, v in sorted(seen.items(), key=lambda kv: -len(kv[1]))}
