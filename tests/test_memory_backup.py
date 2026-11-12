"""The agents' memory goes to B2 and comes back only into empty folders (ADR-128)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from eulerlab.ingest import memory_backup as mb


@dataclass
class FakeStore:
    objects: dict[str, bytes] = field(default_factory=dict)
    puts: list[str] = field(default_factory=list)

    def list_md5(self, prefix: str) -> dict[str, str]:
        return {
            k: hashlib.md5(v, usedforsecurity=False).hexdigest()
            for k, v in self.objects.items()
            if k.startswith(prefix)
        }

    def put(self, key: str, payload: bytes, sha256: str) -> None:
        self.puts.append(key)
        self.objects[key] = payload

    def get(self, key: str) -> bytes:
        return self.objects[key]


def _trees(tmp_path: Path) -> tuple[mb.Tree, ...]:
    agents = tmp_path / "data/agents"
    (agents / "lab/run1").mkdir(parents=True)
    (agents / "memory").mkdir()
    (agents / "engineering/worktrees/x").mkdir(parents=True)
    (agents / "lab/run1/output.json").write_text('{"status": "ok"}')
    (agents / "memory/lab_ideas.jsonl").write_text('{"a": 1}\n')
    (agents / "tasks.lock").write_text("")
    (agents / "engineering/worktrees/x/big.py").write_text("checkout")
    derived = tmp_path / "data/derived"
    derived.mkdir(parents=True)
    (derived / "trials.jsonl").write_text('{"t": 1}\n')
    (derived / "panel.parquet").write_text("huge")
    return (
        mb.Tree("agents", agents, "memory/agents/"),
        mb.Tree("ledger", derived, "derived/", pattern="trials.jsonl"),
    )


def test_memory_is_sent_without_locks_checkouts_or_other_derived_files(tmp_path: Path) -> None:
    store = FakeStore()
    [agents, ledger] = mb.backup(store, "nse/", _trees(tmp_path))
    assert sorted(store.puts) == [
        "nse/derived/trials.jsonl",
        "nse/memory/agents/lab/run1/output.json",
        "nse/memory/agents/memory/lab_ideas.jsonl",
    ]
    assert (agents.sent, ledger.sent) == (2, 1)


def test_only_changed_files_are_sent_again_even_when_they_shrink(tmp_path: Path) -> None:
    store = FakeStore()
    trees = _trees(tmp_path)
    mb.backup(store, "nse/", trees)
    store.puts.clear()
    (trees[0].root / "lab/run1/output.json").write_text("{}")  # smaller, still sent
    [agents, ledger] = mb.backup(store, "nse/", trees)
    assert store.puts == ["nse/memory/agents/lab/run1/output.json"]
    assert (agents.sent, agents.same, ledger.same) == (1, 1, 1)


def test_a_dry_run_sends_nothing(tmp_path: Path) -> None:
    store = FakeStore()
    [agents, _] = mb.backup(store, "nse/", _trees(tmp_path), dry_run=True)
    assert agents.sent == 2 and store.puts == []


def test_restore_fills_an_empty_folder_and_refuses_a_full_one(tmp_path: Path) -> None:
    store = FakeStore()
    trees = _trees(tmp_path / "old")
    mb.backup(store, "nse/", trees)
    fresh = mb.Tree("agents", tmp_path / "new/agents", "memory/agents/")
    [done] = mb.restore(store, "nse/", [fresh])
    assert done.sent == 2 and (fresh.root / "memory/lab_ideas.jsonl").read_text() == '{"a": 1}\n'
    [refused] = mb.restore(store, "nse/", [trees[0]])
    assert refused.sent == 0 and "not empty" in refused.failed[0]


def test_a_key_that_would_land_outside_the_folder_is_skipped(tmp_path: Path) -> None:
    store = FakeStore({"nse/memory/agents/../../escape.txt": b"x"})
    [r] = mb.restore(store, "nse/", [mb.Tree("agents", tmp_path / "a", "memory/agents/")])
    assert r.sent == 0 and "outside" in r.failed[0] and not (tmp_path / "escape.txt").exists()


def test_the_committed_trees_cover_every_kind_of_memory() -> None:
    roots = {t.name: str(t.root) for t in mb.TREES}
    assert roots == {
        "agents": "data/agents",
        "drafts": "research/agent_drafts",
        "papers": "research/papers",
        "ledger": "data/derived",
        "database": "data/db_export",  # the database's rows, exported first (T-4562)
        "kill-log": "data/oms",
        "kill-dep": "data/deployments",
    }


@pytest.mark.parametrize("target", ["agents-backup", "agents-restore"])
def test_the_make_targets_exist_and_the_daily_job_backs_up_last(target: str) -> None:
    text = Path("Makefile").read_text(encoding="utf-8")
    assert f"\n{target}:" in text
    ideas = text.split("\nagents-ideas:", 1)[1].split("\n\n", 1)[0]
    order = [line.split()[-1] for line in ideas.splitlines() if "python -m" in line]
    assert order[-6:] == [
        "research",
        "eulerlab.research.autopilot",  # ADR-150: after research, before the lab
        "lab",
        "eulerlab.agents.work",
        "watchdog",
        "eulerlab.ingest.memory_backup",
    ]
