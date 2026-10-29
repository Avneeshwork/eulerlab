"""The optimiser's two rules: the grid is the card's, and a plateau beats a peak (ADR-085).

**The grid is fixed at registration.** A card may declare `grid:` — the values
each parameter may take — and `strategies:` — the strategy ids it covers. Once
it does, `make optimize` refuses a sweep of one of those strategies over any
value the card did not list. Widening the grid after seeing a result is the
quiet way a search grows, and the trial ledger would then be charging for a
search nobody wrote down beforehand.

A card with no `grid:` changes nothing: the optimiser keeps its own small
grids (`optimize_run.SPACES`).

**Report the plateau, not the peak.** `plateau` scores each candidate by the
median of itself and its neighbours one step away on every axis. A sharp peak
among losing neighbours scores low; a flat region of decent results scores
high. That is the number to read, because a peak one grid step wide is what
noise looks like after a search.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

HYPOTHESES = Path("hypotheses")


class OutsideCard(ValueError):
    """A sweep asked for values its card did not register."""


def card_grids(directory: Path = HYPOTHESES) -> dict[str, tuple[str, dict[str, list[float]]]]:
    """strategy id -> (card id, the card's grid), for cards that declare both."""
    out: dict[str, tuple[str, dict[str, list[float]]]] = {}
    for path in sorted(directory.glob("H-*.yaml")):
        spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        grid = spec.get("grid")
        strategies = spec.get("strategies") or []
        if not isinstance(grid, dict) or not strategies:
            continue
        clean = {
            str(k): [float(v) for v in values]
            for k, values in grid.items()
            if isinstance(values, list)
        }
        for sid in strategies:
            out[str(sid)] = (str(spec.get("id", path.stem)), clean)
    return out


def enforce(
    strategy_id: str,
    space: Mapping[str, Sequence[float]],
    grids: Mapping[str, tuple[str, Mapping[str, Sequence[float]]]] | None = None,
) -> str:
    """Raise `OutsideCard` if `space` leaves the card's grid. Returns the card id, or ''."""
    known = card_grids() if grids is None else grids
    if strategy_id not in known:
        return ""
    card_id, grid = known[strategy_id]
    problems: list[str] = []
    for name, values in space.items():
        allowed = {float(v) for v in grid.get(name, [])}
        if name not in grid:
            problems.append(f"{name} is not in {card_id}'s grid")
            continue
        extra = sorted(float(v) for v in values if float(v) not in allowed)
        if extra:
            problems.append(f"{name} values {extra} are not in {card_id}'s grid {sorted(allowed)}")
    if problems:
        raise OutsideCard(f"{strategy_id}: " + "; ".join(problems))
    return card_id


def plateau(
    candidates: Sequence[tuple[Mapping[str, float], float]], space: Mapping[str, Sequence[float]]
) -> list[dict[str, Any]]:
    """Each candidate's value beside the median of it and its grid neighbours."""
    axes = {name: sorted(float(v) for v in values) for name, values in space.items()}
    by_key = {
        tuple(sorted((k, float(v)) for k, v in params.items())): value
        for params, value in candidates
    }

    def neighbours(params: Mapping[str, float]) -> list[float]:
        found = []
        for name, values in axes.items():
            here = float(params.get(name, 0.0))
            if here not in values:
                continue
            index = values.index(here)
            for step in (-1, 1):
                j = index + step
                if 0 <= j < len(values):
                    moved = dict(params)
                    moved[name] = values[j]
                    key = tuple(sorted((k, float(v)) for k, v in moved.items()))
                    if key in by_key:
                        found.append(by_key[key])
        return found

    out = []
    for params, value in candidates:
        around = [value, *neighbours(params)]
        out.append(
            {
                "params": dict(params),
                "value": value,
                "plateau": statistics.median(around),
                "neighbours": len(around) - 1,
            }
        )
    out.sort(key=lambda row: -float(row["plateau"]))  # type: ignore[arg-type]
    return out
