"""Builder strategies, saved per workspace.

One small JSON file per strategy under `workspaces/<id>/strategies/`. A save
replaces the file: the spec is a draft being edited, not evidence. The evidence
is the backtest, and every backtest records the spec's digest in its
parameters, so a result can always be traced to the exact rules that produced
it even after the strategy is edited.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from eulerlab.builder.spec import BuilderSpec, is_builder_id
from eulerlab.workspace import Workspace


def _path(workspace: Workspace, strategy_id: str) -> Path:
    if not is_builder_id(strategy_id) or "/" in strategy_id or "\\" in strategy_id:
        msg = f"{strategy_id!r} is not a builder strategy id"
        raise ValueError(msg)
    return workspace.strategies / f"{strategy_id}.json"


def save(workspace: Workspace, spec: BuilderSpec) -> Path:
    path = _path(workspace, spec.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".partial")
    tmp.write_text(json.dumps(spec.model_dump(), indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    return path


def load(workspace: Workspace, strategy_id: str) -> BuilderSpec | None:
    try:
        path = _path(workspace, strategy_id)
    except ValueError:
        return None
    if not path.exists():
        return None
    try:
        return BuilderSpec.model_validate_json(path.read_text(encoding="utf-8"))
    except (ValidationError, OSError):
        return None


def all_specs(workspace: Workspace) -> list[BuilderSpec]:
    folder = workspace.strategies
    if not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.glob("b_*.json")):
        spec = load(workspace, path.stem)
        if spec is not None:
            out.append(spec)
    return out


def delete(workspace: Workspace, strategy_id: str) -> bool:
    """Removes the spec only. Its recorded backtests stay, as every result does."""
    path = _path(workspace, strategy_id)
    if not path.exists():
        return False
    path.unlink()
    return True
