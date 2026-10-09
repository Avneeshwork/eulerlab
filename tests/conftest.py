"""Test-wide defaults.

The suite runs offline. Tests reached the bucket only transitively — calling
`catalog.search` listed 34,000 remote keys — and one stalled connection hung a
run for 33 minutes instead of failing it. A hang is worse than a failure: it
looks the same as slow work, so it blocked every commit behind it without ever
saying why.

Set `EULERLAB_NO_CLOUD=0` to run a test against the real bucket deliberately.
"""

from __future__ import annotations

import os

import pytest

from eulerlab.ingest import landing_reader


@pytest.fixture(autouse=True, scope="session")
def _offline() -> None:
    os.environ.setdefault(landing_reader.OFFLINE_ENV, "1")


@pytest.fixture(autouse=True)
def _private_locks(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every test gets its own lock folder.

    The repo's `data/derived/.locks` belongs to real runs. On 2026-10-09 three
    feed tests failed because `make feed` was running and held the real `feed`
    lock; a test must not depend on what else the machine is doing.
    """
    from eulerlab.ingest import filelock

    monkeypatch.setattr(filelock, "LOCK_DIR", tmp_path_factory.mktemp("locks"))
