"""`filecache.FileMemo`: a parsed file is reused only while the file is unchanged."""

from __future__ import annotations

import os
from pathlib import Path

from eulerlab.filecache import FileMemo


def test_reused_while_unchanged_and_reread_after_any_change(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    path.write_text("a\n", encoding="utf-8")
    reads: list[str] = []

    def load(p: Path) -> str:
        text = p.read_text(encoding="utf-8")
        reads.append(text)
        return text

    memo = FileMemo(load)
    assert memo(path) == "a\n" and memo(path) == "a\n"
    assert len(reads) == 1

    with path.open("a", encoding="utf-8") as handle:  # an append changes the size
        handle.write("b\n")
    assert memo(path) == "a\nb\n"

    path.write_text("c\nd\n", encoding="utf-8")  # same size, new time
    os.utime(path, ns=(1, 1))
    assert memo(path) == "c\nd\n"
    assert len(reads) == 3


def test_a_missing_file_is_asked_again_once_it_exists(tmp_path: Path) -> None:
    path = tmp_path / "later.txt"
    memo = FileMemo(lambda p: p.read_text(encoding="utf-8") if p.exists() else "")
    assert memo(path) == ""
    path.write_text("now", encoding="utf-8")
    assert memo(path) == "now"


def test_only_the_most_recent_files_are_kept(tmp_path: Path) -> None:
    memo = FileMemo(lambda p: p.name, size=2)
    for name in ("a", "b", "c"):
        (tmp_path / name).write_text(name, encoding="utf-8")
        memo(tmp_path / name)
    assert list(memo._held) == [tmp_path / "b", tmp_path / "c"]
