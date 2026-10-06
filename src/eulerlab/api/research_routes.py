"""The research library's endpoints: list, read, save and link papers.

Backtesting is not here. A paper's linked strategy runs where every strategy
runs — `/api/run/batch` for builder and registered strategies, `/api/tweezer`
for the Tweezer scanner — so a result from the library is the same result the
Strategies page would show.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ValidationError

from eulerlab import results as result_store
from eulerlab import workspace as workspace_mod
from eulerlab.builder import store as builder_store
from eulerlab.intraday import tweezer_report
from eulerlab.research import library
from eulerlab.strategies import REGISTRY

router = APIRouter(prefix="/api/research")


class PaperRequest(BaseModel):
    paper: dict[str, Any]
    workspace: str = ""


class LinkRequest(BaseModel):
    link: dict[str, Any]


def _errors(exc: ValidationError) -> list[str]:
    out = []
    for error in exc.errors():
        where = " → ".join(str(part) for part in error["loc"])
        message = str(error["msg"]).removeprefix("Value error, ")
        out.append(f"{where}: {message}" if where else message)
    return out


def _tweezer_measured(timeframe: int) -> list[dict[str, Any]]:
    path = Path(tweezer_report.OUT)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [
        {
            "window": data.get("window"),
            "universe": data.get("universe"),
            "hold_sessions": run.get("hold_sessions", 1),
            "signals": run.get("signals"),
            "triggered": run.get("triggered"),
            "gross": run.get("gross"),
            "net": run.get("net"),
        }
        for run in data.get("runs", [])
        if run.get("timeframe") == timeframe
    ]


def _link_view(tenant: workspace_mod.Workspace, link: library.StrategyLink) -> dict[str, Any]:
    """A link, with what it currently points at and its latest result."""
    view: dict[str, Any] = link.model_dump()
    if link.kind == "builder":
        spec = builder_store.load(tenant, link.id)
        view["title"] = spec.name if spec else link.id
        view["exists"] = spec is not None
        view["runnable"] = spec is not None
        view["result"] = result_store.summary(tenant, link.id)
    elif link.kind == "registered":
        declaration = REGISTRY.get(link.id)
        view["title"] = declaration.title if declaration else link.id
        view["exists"] = declaration is not None
        view["runnable"] = declaration is not None
        view["result"] = result_store.summary(tenant, link.id)
    else:
        view["title"] = f"Tweezer Bottom, {link.timeframe or 15}-minute candles"
        view["exists"] = True
        view["runnable"] = True
        view["result"] = None
        view["measured"] = _tweezer_measured(link.timeframe or 15)
    return view


def _paper_view(tenant: workspace_mod.Workspace, paper: library.Paper) -> dict[str, Any]:
    return {
        "paper": paper.model_dump(),
        "links": [_link_view(tenant, link) for link in paper.strategies],
    }


@router.get("/papers")
def papers(workspace: str = "") -> dict[str, Any]:
    tenant = workspace_mod.resolve(workspace or None)
    return {"papers": [_paper_view(tenant, p) for p in library.all_papers()]}


@router.post("/papers")
def save_paper(request: PaperRequest) -> dict[str, Any]:
    try:
        paper = library.Paper.model_validate(request.paper).with_id()
    except ValidationError as exc:
        return {"ok": False, "errors": _errors(exc)}
    library.save(paper)
    tenant = workspace_mod.resolve(request.workspace or None)
    return {"ok": True, **_paper_view(tenant, paper)}


@router.post("/papers/{paper_id}/links")
def add_link(paper_id: str, request: LinkRequest) -> dict[str, Any]:
    """Attach a strategy to a paper — what the builder calls after saving a
    strategy it was opened for."""
    paper = library.load(paper_id)
    if paper is None:
        return {"ok": False, "errors": [f"no paper {paper_id!r}"]}
    try:
        link = library.StrategyLink.model_validate(request.link)
    except ValidationError as exc:
        return {"ok": False, "errors": _errors(exc)}
    if any(x.kind == link.kind and x.id == link.id for x in paper.strategies):
        return {"ok": True, "unchanged": True}
    status = "specified" if paper.status == "idea" else paper.status
    library.save(
        paper.model_copy(update={"strategies": [*paper.strategies, link], "status": status})
    )
    return {"ok": True}
