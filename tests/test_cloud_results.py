"""Results mirrored to object storage, and the merge that makes it safe.

The interesting case is not upload. It is two machines appending to the same
append-only log: both are correct, neither has the whole truth, and a naive
"last writer wins" silently deletes runs — which would corrupt the `runs`
denominator the result store exists to keep honest.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eulerlab import cloud_results as cr
from eulerlab import results as rs
from eulerlab import workspace as ws
from eulerlab.ingest.cloud import ReadableStore


class FakeStore:
    """An in-memory bucket. No network, and it can be made to fail on demand."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail_on: set[str] = set()

    def list_sizes(self, prefix: str) -> dict[str, int]:
        return {k: len(v) for k, v in self.objects.items() if k.startswith(prefix)}

    def head_sha256(self, key: str) -> str | None:
        return None

    def put(self, key: str, payload: bytes, sha256: str) -> None:
        if key in self.fail_on:
            msg = f"refused {key}"
            raise RuntimeError(msg)
        self.objects[key] = payload

    def get(self, key: str) -> bytes:
        return self.objects[key]


@pytest.fixture()
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ws.Workspace:
    monkeypatch.setattr(ws, "ROOT", tmp_path / "workspaces")
    return ws.Workspace(id="tenant-a").ensure()


def _row(configuration: str, at: str, sharpe: float = 1.0) -> str:
    return json.dumps({"configuration": configuration, "at": at, "sharpe": sharpe}, sort_keys=True)


# --- the merge -------------------------------------------------------------


def test_merge_keeps_runs_from_both_machines() -> None:
    merged = cr.merge_lines([_row("aaa", "2026-01-01")], [_row("bbb", "2026-01-02")])
    assert len(merged) == 2


def test_the_same_run_recorded_twice_counts_once() -> None:
    """Keyed by (configuration, at), not by whole-line equality.

    The same run serialised on two machines can differ in a float repr. Counted
    as two, it would inflate the denominator that prices selection bias — the
    one number this store exists to protect.
    """
    mine = json.dumps({"configuration": "aaa", "at": "2026-01-01", "sharpe": 1.1000000000000001})
    theirs = json.dumps({"configuration": "aaa", "at": "2026-01-01", "sharpe": 1.1})
    assert len(cr.merge_lines([mine], [theirs])) == 1


def test_merge_is_chronological() -> None:
    merged = cr.merge_lines([_row("b", "2026-05-01")], [_row("a", "2026-01-01")])
    assert [json.loads(line)["configuration"] for line in merged] == ["a", "b"]


def test_a_torn_line_is_not_carried_across() -> None:
    """A half-written row is not a result, and copying one would spread it."""
    merged = cr.merge_lines([_row("aaa", "2026-01-01"), '{"configuration": "b'], [])
    assert len(merged) == 1


def test_local_wins_a_tie(space: ws.Workspace) -> None:
    mine = _row("aaa", "2026-01-01", sharpe=9.0)
    theirs = _row("aaa", "2026-01-01", sharpe=1.0)
    merged = cr.merge_lines([mine], [theirs])
    assert json.loads(merged[0])["sharpe"] == 9.0


# --- push and pull ---------------------------------------------------------


def test_push_uploads_every_result_file(space: ws.Workspace) -> None:
    rs.record(
        space,
        rs.Run(
            strategy_id="demo",
            sharpe=1.4,
            total_return=0.1,
            max_drawdown=-0.1,
            fills=10,
            days=800,
            tier="A",
            window_days=800,
            data_version="v1",
        ),
    )
    store = FakeStore()
    outcome = cr.push(space, store)
    assert outcome.pushed == 1
    assert "results/tenant-a/demo.jsonl" in store.objects


def test_push_skips_a_file_the_bucket_already_matches(space: ws.Workspace) -> None:
    rs.record(
        space,
        rs.Run(
            strategy_id="demo",
            sharpe=1.4,
            total_return=0.1,
            max_drawdown=-0.1,
            fills=10,
            days=800,
            tier="A",
            window_days=800,
            data_version="v1",
        ),
    )
    store = FakeStore()
    cr.push(space, store)
    assert cr.push(space, store).pushed == 0


def test_one_failed_upload_does_not_stop_the_rest(space: ws.Workspace) -> None:
    for name in ("alpha", "beta"):
        rs.record(
            space,
            rs.Run(
                strategy_id=name,
                sharpe=1.0,
                total_return=0.1,
                max_drawdown=-0.1,
                fills=10,
                days=800,
                tier="A",
                window_days=800,
                data_version="v1",
            ),
        )
    store = FakeStore()
    store.fail_on = {"results/tenant-a/alpha.jsonl"}
    outcome = cr.push(space, store)
    assert outcome.pushed == 1
    assert len(outcome.failed) == 1
    assert not outcome.ok


def test_pull_brings_down_a_result_this_machine_never_had(space: ws.Workspace) -> None:
    store = FakeStore()
    store.objects["results/tenant-a/remote.jsonl"] = (_row("zzz", "2026-02-02") + "\n").encode()
    assert cr.pull(space, store).pulled == 1
    assert (space.results / "remote.jsonl").exists()


def test_pull_merges_rather_than_overwrites(space: ws.Workspace) -> None:
    """The case that makes a naive mirror lose data: both sides hold a run the
    other does not."""
    path = space.results / "demo.jsonl"
    path.write_text(_row("mine", "2026-01-01") + "\n", encoding="utf-8")
    store = FakeStore()
    store.objects["results/tenant-a/demo.jsonl"] = (_row("theirs", "2026-01-02") + "\n").encode()

    cr.pull(space, store)
    kept = {json.loads(line)["configuration"] for line in path.read_text().splitlines() if line}
    assert kept == {"mine", "theirs"}


def test_mirror_pulls_before_it_pushes(space: ws.Workspace) -> None:
    """Pushing first would overwrite the bucket with a file missing whatever
    another machine appended, and the next pull would have nothing to restore."""
    path = space.results / "demo.jsonl"
    path.write_text(_row("mine", "2026-01-01") + "\n", encoding="utf-8")
    store = FakeStore()
    store.objects["results/tenant-a/demo.jsonl"] = (_row("theirs", "2026-01-02") + "\n").encode()

    cr.mirror(space, store)
    remote = store.objects["results/tenant-a/demo.jsonl"].decode()
    kept = {json.loads(line)["configuration"] for line in remote.splitlines() if line}
    assert kept == {"mine", "theirs"}, "the bucket must end up holding the union, not just ours"


def test_an_outage_is_reported_not_raised(
    space: ws.Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A backtest that succeeded and was recorded locally must not be reported
    as failed because the network was down."""
    monkeypatch.setattr(cr, "configured", lambda: (True, "present"))

    def explode() -> ReadableStore:
        msg = "no route to host"
        raise OSError(msg)

    monkeypatch.setattr(cr, "open_store", explode)
    outcome = cr.mirror_quietly(space)
    assert not outcome.ok
    assert "no route to host" in outcome.failed[0]


def test_results_do_not_leak_between_workspaces_in_the_bucket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ws, "ROOT", tmp_path / "workspaces")
    a = ws.Workspace(id="tenant-a").ensure()
    b = ws.Workspace(id="tenant-b").ensure()
    rs.record(
        a,
        rs.Run(
            strategy_id="demo",
            sharpe=2.0,
            total_return=0.1,
            max_drawdown=-0.1,
            fills=10,
            days=800,
            tier="A",
            window_days=800,
            data_version="v1",
        ),
    )
    store = FakeStore()
    cr.push(a, store)
    assert cr.pull(b, store).pulled == 0, "one tenant's prefix must not be visible to another"
