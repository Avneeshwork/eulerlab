"""Which research cards the lab queues (HISTORY #73)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from eulerlab.agents import runtime
from eulerlab.agents.runtime import Item, WorkerResult
from eulerlab.agents.workers import lab

NOW = datetime(2026, 11, 4, 6, 0, tzinfo=UTC)


def _draft(root: Path, name: str, verdict: str) -> Path:
    folder = root / "drafts" / name
    folder.mkdir(parents=True)
    (folder / "card.yaml").write_text("id: PENDING\n", encoding="utf-8")
    (folder / "draft.json").write_text(json.dumps({"card": verdict}), encoding="utf-8")
    return folder


def test_incomplete_and_unfixable_cards_are_not_queued(tmp_path: Path) -> None:
    good = _draft(tmp_path, "good", "valid")
    half = _draft(tmp_path, "half", "incomplete")
    broken = _draft(tmp_path, "broken", "valid")
    waiting = _draft(tmp_path, "waiting", "valid")
    items = [Item(kind="draft", title=p.name, ref=str(p)) for p in (good, half, broken, waiting)]
    runtime.run(
        "research", root=tmp_path, now=NOW, worker=lambda ctx: WorkerResult("drafted", items)
    )
    unbuildable = [
        {"card": str(broken / "card.yaml"), "features": []},
        {"card": str(waiting / "card.yaml"), "features": ["liquidity_beta"]},
    ]
    runtime.run(
        "lab",
        root=tmp_path,
        now=NOW,
        worker=lambda ctx: WorkerResult("tested", data={"unbuildable": unbuildable}),
    )
    ctx = SimpleNamespace(args={}, root=tmp_path, name="lab")
    queued = lab.candidates(ctx)  # type: ignore[arg-type]
    assert queued == [good / "card.yaml", waiting / "card.yaml"]
