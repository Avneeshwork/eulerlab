"""The snapshot's live-quote reuse, its deadline, and the bucket listing (ADR-077)."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest

from eulerlab import cloud_results, quotes
from eulerlab import workspace as workspace_mod
from eulerlab.api import server


def test_a_deadline_returns_when_it_expires_not_when_the_work_ends() -> None:
    """The `with` block it replaced waited out the abandoned call: a 3 s hang
    behind a 0.5 s deadline took 3 s."""
    release = threading.Event()
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        server._bounded(release.wait, 5.0, timeout=0.2)
    assert time.monotonic() - started < 1.0
    release.set()


def test_a_complete_answer_is_reused_and_a_failed_one_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    answers: list[tuple[dict[str, Any], str]] = [
        ({"AAA": "q"}, "TimeoutError: cut short"),
        ({"AAA": "q"}, ""),
    ]

    def universe(symbols: list[str]) -> tuple[dict[str, Any], str]:
        calls.append("asked")
        return answers[min(len(calls), len(answers)) - 1]

    monkeypatch.setattr(quotes, "nse_universe", universe)

    assert server._universe_quotes(["AAA"])[1] == "TimeoutError: cut short"
    assert server._universe_quotes(["AAA"]) == ({"AAA": "q"}, "")
    assert server._universe_quotes(["AAA"]) == ({"AAA": "q"}, "")
    assert calls == ["asked", "asked"], "the partial answer was asked again; the whole one was not"

    monkeypatch.setattr(server, "LIVE_UNIVERSE_TTL", 0.0)
    server._universe_quotes(["AAA"])
    assert len(calls) == 3, "an expired answer is asked again"


class _Bucket:
    def __init__(self) -> None:
        self.keys = {"results/default/a.jsonl": 1}
        self.lists = 0

    def list_sizes(self, prefix: str) -> dict[str, int]:
        self.lists += 1
        return {k: v for k, v in self.keys.items() if k.startswith(prefix)}


@pytest.fixture
def bucket(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _Bucket:
    found = _Bucket()

    class _Config:
        bucket = "test-bucket"

    monkeypatch.setattr(cloud_results, "configured", lambda: (True, ""))
    monkeypatch.setattr(cloud_results, "open_store", lambda: found)
    monkeypatch.setattr(server, "load_storage_config", lambda path: _Config())
    monkeypatch.setattr(workspace_mod, "ROOT", tmp_path)
    tenant = workspace_mod.Workspace(id="default")
    monkeypatch.setattr(workspace_mod, "resolve", lambda name=None: tenant)
    return found


def test_the_bucket_listing_is_reused_until_a_mirror_or_a_refresh(
    bucket: _Bucket, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = server.cloud_status()
    assert first["reachable"] and first["remote_files"] == ["a.jsonl"]
    assert first["listed_at"]

    bucket.keys["results/default/b.jsonl"] = 1
    assert server.cloud_status()["remote_files"] == ["a.jsonl"], "kept inside the window"
    assert bucket.lists == 1

    assert server.cloud_status(refresh=True)["remote_files"] == ["a.jsonl", "b.jsonl"]
    assert bucket.lists == 2

    bucket.keys["results/default/c.jsonl"] = 1
    monkeypatch.setattr(cloud_results, "mirror_quietly", lambda workspace: cloud_results.Mirror())
    server._mirror(workspace_mod.Workspace(id="default"))
    assert server.cloud_status()["remote_files"] == ["a.jsonl", "b.jsonl", "c.jsonl"], (
        "a mirror from this server must not leave the old listing on screen"
    )
