"""Three faults found on 2026-11-04 (HISTORY #77): a late F&O file, a stale diagnosis, a test-suite timeout."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from eulerlab.agents.workers import data
from eulerlab.devtools import fixer
from eulerlab.options import nifty_history


def test_options_see_an_fo_file_landed_tonight_and_not_yet_uploaded() -> None:
    def available(tree: str, pattern: str, *, allow_cloud: bool = True) -> list[str]:
        if tree == "fo":
            return ["fo/2026/11/2026-11-02_udiff.zip", "fo/2026/11/2026-11-03_udiff.zip"]
        assert (tree, pattern, allow_cloud) == ("nse", "fo/**/*.zip", False)
        return ["nse/fo/2026/11/2026-11-03_udiff.zip", "nse/fo/2026/11/2026-11-04_udiff.zip"]

    got = nifty_history.archives(available)
    assert sorted(got) == ["2026-11-02", "2026-11-03", "2026-11-04"]
    assert got["2026-11-04"] == "nse/fo/2026/11/2026-11-04_udiff.zip"
    assert got["2026-11-03"].startswith("nse/fo/")  # the local copy is preferred


def _row(name: str, status: str, behind: int = 0) -> Any:
    return SimpleNamespace(name=name, status=status, behind=behind)


def test_a_dataset_the_rerun_caught_up_is_not_sent_for_diagnosis() -> None:
    before = [_row("F&O bhavcopy", "missing"), _row("Nifty options", "behind", 2)]
    after = [_row("F&O bhavcopy", "fresh"), _row("Nifty options", "behind", 2)]
    assert data.caught_up(before, after) == [("F&O bhavcopy", "missing")]
    assert data.caught_up(before, [_row("F&O bhavcopy", "behind", 1)]) == [
        ("F&O bhavcopy", "missing")
    ]
    assert data.caught_up(before, []) == []


def test_a_check_that_runs_too_long_is_a_failed_check_not_a_crash(tmp_path: Path) -> None:
    rc, text = fixer._run([sys.executable, "-c", "import time; time.sleep(5)"], tmp_path, timeout=1)
    assert rc == 124 and "did not finish in 1 s" in text
    rc, text = fixer._run([sys.executable, "-c", "print('ok')"], tmp_path)
    assert rc == 0 and "ok" in text
    assert fixer.SUITE_TIMEOUT > fixer.RUN_TIMEOUT
