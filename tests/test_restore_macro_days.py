"""Restoring macro days the mirror shortened (T-4365, HISTORY #54)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from eulerlab.macro import merge_day_versions
from tools.restore_macro_days import plan_day, run


def _row(at: str, symbol: str = "TVC:DXY", last: float = 99.0) -> str:
    return json.dumps({"at": at, "symbol": symbol, "last": last})


def test_the_union_keeps_every_reading_once_in_time_order() -> None:
    early = "\n".join([_row("09:00"), _row("10:00")]) + "\n"
    full = "\n".join([_row("09:00"), _row("10:00"), _row("11:00")]) + "\n"
    # What the prune-and-recreate left: only the later rows.
    late = "\n".join([_row("12:00"), _row("13:00")]) + "\n"
    merged = merge_day_versions([early, full, late]).splitlines()
    assert merged == [_row(t) for t in ("09:00", "10:00", "11:00", "12:00", "13:00")]


def test_a_line_written_twice_in_one_version_stays_twice() -> None:
    twice = "\n".join([_row("09:00"), _row("09:00")]) + "\n"
    once = _row("09:00") + "\n"
    assert merge_day_versions([twice, once]).splitlines() == [_row("09:00")] * 2


def test_lines_are_kept_byte_for_byte() -> None:
    odd = '{"symbol": "X",  "at": "09:00", "last": 1.50}'
    assert merge_day_versions([odd + "\n"]) == odd + "\n"


class FakeStore:
    def __init__(self, versions: list[bytes]) -> None:
        self.stored = versions
        self.current = versions[-1]
        self.puts: list[tuple[str, bytes, str]] = []

    def versions(self, key: str) -> list[tuple[str, str, int]]:
        return [(str(i), f"2026-10-0{i}T00:00:00", len(v)) for i, v in enumerate(self.stored)]

    def get_version(self, key: str, version_id: str) -> bytes:
        return self.stored[int(version_id)]

    def get(self, key: str) -> bytes:
        return self.current

    def put(self, key: str, payload: bytes, sha256: str) -> None:
        assert hashlib.sha256(payload).hexdigest() == sha256
        self.puts.append((key, payload, sha256))
        self.current = payload


def _short_day() -> FakeStore:
    full = ("\n".join(_row(t) for t in ("09:00", "10:00", "11:00")) + "\n").encode()
    short = (_row("12:00") + "\n").encode()
    return FakeStore([full, short])


def test_a_dry_run_writes_nothing(tmp_path: Path) -> None:
    store = _short_day()
    assert run(store, ["2026-10-29"], prefix="nse/", landing=tmp_path, apply=False) == 0
    assert store.puts == []


def test_apply_writes_the_union_and_never_touches_the_local_copy(tmp_path: Path) -> None:
    store = _short_day()
    local = tmp_path / "macro" / "2026-10-29.jsonl"
    local.parent.mkdir(parents=True)
    local.write_text(_row("12:00") + "\n")
    before = local.read_bytes()

    plan = plan_day(store, "2026-10-29", prefix="nse/", landing=tmp_path)
    assert (plan.current_rows, plan.merged_rows, plan.recovered, plan.local_rows) == (1, 4, 3, 1)
    assert run(store, ["2026-10-29"], prefix="nse/", landing=tmp_path, apply=True) == 0
    assert [key for key, _, _ in store.puts] == ["nse/macro/2026-10-29.jsonl"]
    assert store.current.decode().splitlines() == [
        _row(t) for t in ("09:00", "10:00", "11:00", "12:00")
    ]
    assert local.read_bytes() == before


def test_a_day_already_whole_is_not_written(tmp_path: Path) -> None:
    whole = (_row("09:00") + "\n").encode()
    store = FakeStore([whole, whole])
    assert run(store, ["2026-10-29"], prefix="", landing=tmp_path, apply=True) == 0
    assert store.puts == []


def test_a_day_with_no_versions_fails_the_run(tmp_path: Path) -> None:
    store = FakeStore([b""])
    store.stored = []
    assert run(store, ["2026-10-29"], prefix="", landing=tmp_path, apply=True) == 1
    with pytest.raises(LookupError):
        plan_day(store, "2026-10-29", prefix="", landing=tmp_path)
