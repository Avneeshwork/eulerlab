"""Archiving a strategy hides it from the library and changes nothing else (ADR-069)."""

from __future__ import annotations

from pathlib import Path

import pytest

import eulerlab.workspace as workspace_mod
from eulerlab.strategies import archive


@pytest.fixture
def tenant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> workspace_mod.Workspace:
    monkeypatch.setattr(workspace_mod, "ROOT", tmp_path)
    return workspace_mod.Workspace(id="default")


def test_nothing_is_archived_until_something_is(tenant: workspace_mod.Workspace) -> None:
    assert archive.read(tenant) == {}


def test_archive_then_restore_leaves_no_trace(tenant: workspace_mod.Workspace) -> None:
    held = archive.change(
        tenant, ["momentum_12_1", "small_size"], archived=True, today="2026-10-13"
    )
    assert held == {"momentum_12_1": "2026-10-13", "small_size": "2026-10-13"}
    assert archive.read(tenant) == held
    assert archive.change(tenant, ["small_size"], archived=False) == {"momentum_12_1": "2026-10-13"}
    assert archive.change(tenant, ["momentum_12_1"], archived=False) == {}
    assert archive.read(tenant) == {}


def test_archiving_twice_keeps_the_first_date_and_restoring_twice_is_harmless(
    tenant: workspace_mod.Workspace,
) -> None:
    archive.change(tenant, ["small_size"], archived=True, today="2026-10-13")
    again = archive.change(tenant, ["small_size", "small_size"], archived=True, today="2026-11-01")
    assert again == {"small_size": "2026-10-13"}
    assert archive.change(tenant, ["never_archived"], archived=False) == again


def test_an_id_that_is_not_a_strategy_id_is_refused_and_nothing_is_written(
    tenant: workspace_mod.Workspace,
) -> None:
    for bad in ("../secrets", "a/b", "", "x" * 81):
        with pytest.raises(ValueError, match="not a strategy id"):
            archive.change(tenant, ["small_size", bad], archived=True)
    assert archive.read(tenant) == {}
    with pytest.raises(ValueError, match="at most"):
        archive.change(tenant, [f"s{i}" for i in range(archive.MAX_IDS + 1)], archived=True)


def test_a_broken_file_reads_as_nothing_archived(tenant: workspace_mod.Workspace) -> None:
    tenant.root.mkdir(parents=True, exist_ok=True)
    (tenant.root / archive.FILE).write_text("{not json", encoding="utf-8")
    assert archive.read(tenant) == {}
    (tenant.root / archive.FILE).write_text("[1, 2]", encoding="utf-8")
    assert archive.read(tenant) == {}


def test_the_route_archives_restores_and_the_library_says_so(
    tenant: workspace_mod.Workspace,
) -> None:
    from eulerlab.api import server

    done = server.archive_strategies(server.ArchiveRequest(ids=["small_size"]))
    assert done == {"ok": True, "archived": ["small_size"]}
    rows = {s["id"]: s for s in server.fleet()["strategies"]}
    assert rows["small_size"]["archived"] is True
    assert rows["momentum_12_1"]["archived"] is False
    # Archived, not removed: it is still listed, with its evidence.
    assert "result" in rows["small_size"]

    back = server.archive_strategies(server.ArchiveRequest(ids=["small_size"], archived=False))
    assert back == {"ok": True, "archived": []}
    assert all(not s["archived"] for s in server.fleet()["strategies"])

    refused = server.archive_strategies(server.ArchiveRequest(ids=["../x"]))
    assert refused["ok"] is False
