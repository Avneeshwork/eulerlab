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
