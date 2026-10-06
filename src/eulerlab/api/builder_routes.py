"""The strategy builder's endpoints.

Validating, previewing, saving and listing builder specs. Running one is not
here: a saved builder strategy is backtested through `/api/run/batch` like any
registered strategy, so it gets the same engine, the same result store and the
same report. A second run path would be a second answer.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ValidationError

from eulerlab import results as result_store
from eulerlab import workspace as workspace_mod
from eulerlab.builder import store
from eulerlab.builder.indicators import DEFINITIONS
from eulerlab.builder.spec import COMPARATOR_WORDS, BuilderSpec, summarise
from eulerlab.builder.templates import TEMPLATES

router = APIRouter(prefix="/api/builder")


class SpecRequest(BaseModel):
    spec: dict[str, Any]
    workspace: str = ""


def _errors(exc: ValidationError) -> list[str]:
    """Pydantic's errors, as sentences a person can act on."""
    out = []
    for error in exc.errors():
        where = " → ".join(str(part) for part in error["loc"] if part not in ("value",))
        message = str(error["msg"]).removeprefix("Value error, ")
        out.append(f"{where}: {message}" if where else message)
    return out


def _check(raw: dict[str, Any]) -> tuple[BuilderSpec | None, list[str]]:
    try:
        return BuilderSpec.model_validate(raw), []
    except ValidationError as exc:
        return None, _errors(exc)


@router.get("/catalog")
def catalog() -> dict[str, Any]:
    """Everything the builder page offers, from the code that implements it."""
    return {
        "indicators": [d.to_row() for d in DEFINITIONS],
        "comparators": [{"name": k, "label": v} for k, v in COMPARATOR_WORDS.items()],
        "templates": [t.model_dump() for t in TEMPLATES],
        "limits": {"max_rules": 8, "max_positions": 100},
        "caveats": [
            "Decisions are made on each day's close and filled by the engine afterwards, with costs.",
            "Stops, targets and trailing stops are judged on closes, measured from the signal close.",
            "Long only. Open, high and low fall back to the close where the panel has no range.",
        ],
    }


@router.post("/validate")
def validate(request: SpecRequest) -> dict[str, Any]:
    spec, errors = _check(request.spec)
    if spec is None:
        return {"ok": False, "errors": errors}
    return {
        "ok": True,
        "id": spec.id,
        "summary": summarise(spec),
        "warmup": spec.warmup(),
        "digest": spec.digest(),
    }


@router.post("/save")
def save(request: SpecRequest) -> dict[str, Any]:
    spec, errors = _check(request.spec)
    if spec is None:
        return {"ok": False, "errors": errors}
    tenant = workspace_mod.resolve(request.workspace or None)
    store.save(tenant, spec)
    return {"ok": True, "id": spec.id, "summary": summarise(spec), "spec": spec.model_dump()}


@router.get("/strategies")
def strategies(workspace: str = "") -> dict[str, Any]:
    tenant = workspace_mod.resolve(workspace or None)
    return {
        "strategies": [
            {
                "spec": spec.model_dump(),
                "summary": summarise(spec),
                "result": result_store.summary(tenant, spec.id),
            }
            for spec in store.all_specs(tenant)
        ]
    }


@router.delete("/strategies/{strategy_id}")
def remove(strategy_id: str, workspace: str = "") -> dict[str, Any]:
    tenant = workspace_mod.resolve(workspace or None)
    try:
        removed = store.delete(tenant, strategy_id)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": removed}
