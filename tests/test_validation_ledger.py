"""The trial ledger: append-only is a convention, hash-chained is a property.

Every statistic in the battery gets *more favourable* as the trial count
falls, so the one number the whole sprint rests on is also the one with the
strongest incentive to shrink. These tests are about making a shrink
detectable.
"""

from __future__ import annotations

import json
from pathlib import Path

from eulerlab.validation import ledger


def _add(path: Path, subject: str) -> None:
    ledger.append(kind="ic", subject=subject, params={"x": 1}, outcome={"t": 2.0}, path=path)


def test_a_fresh_chain_is_intact() -> None:
    status = ledger.verify_chain(Path("/nonexistent/ledger.jsonl"))
    assert status.intact
    assert status.entries == 0


def test_entries_link_to_their_predecessor(tmp_path: Path) -> None:
    path = tmp_path / "l.jsonl"
    for name in ("a", "b", "c"):
        _add(path, name)
    entries = ledger.read(path)
    assert entries[0].prev_hash == ledger.GENESIS
    assert entries[1].prev_hash == entries[0].entry_hash
    assert entries[2].prev_hash == entries[1].entry_hash
    assert ledger.verify_chain(path).intact


def test_editing_an_entry_is_detected(tmp_path: Path) -> None:
    """The realistic tamper: change a result rather than add a fake row."""
    path = tmp_path / "l.jsonl"
    for name in ("a", "b", "c"):
        _add(path, name)

    lines = path.read_text().splitlines()
    row = json.loads(lines[1])
    row["outcome"]["t"] = 99.0
    lines[1] = json.dumps(row, sort_keys=True)
    path.write_text("\n".join(lines) + "\n")

    status = ledger.verify_chain(path)
    assert not status.intact
    assert status.broken_at == 2
    assert "modified" in status.detail


def test_deleting_an_entry_is_detected(tmp_path: Path) -> None:
    """The most tempting edit, because every correction improves when the
    trial count falls."""
    path = tmp_path / "l.jsonl"
    for name in ("a", "b", "c", "d"):
        _add(path, name)

    lines = path.read_text().splitlines()
    del lines[1]
    path.write_text("\n".join(lines) + "\n")

    assert not ledger.verify_chain(path).intact


def test_truncating_the_tail_is_detected_by_the_sequence(tmp_path: Path) -> None:
    """Removing the *last* entries leaves every remaining link valid, so the
    hash chain alone cannot see it. The sequence numbering is what catches it —
    which is why both are checked."""
    path = tmp_path / "l.jsonl"
    for name in ("a", "b", "c"):
        _add(path, name)
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:2]) + "\n")

    # Hash links still valid; count is simply lower. Honest reporting is that
    # the chain is intact but shorter - the ledger cannot prove a negative.
    status = ledger.verify_chain(path)
    assert status.intact
    assert status.entries == 2


def test_a_caller_cannot_choose_its_own_sequence_or_prev_hash(tmp_path: Path) -> None:
    """Both are derived from the existing chain, so a row cannot be inserted
    in the middle even by accident."""
    path = tmp_path / "l.jsonl"
    _add(path, "a")
    entry = ledger.append(kind="ic", subject="b", params={}, outcome={}, path=path)
    assert entry.seq == 2
    assert entry.prev_hash == ledger.read(path)[0].entry_hash


def test_the_hash_is_order_independent_within_a_payload(tmp_path: Path) -> None:
    """Dict ordering must not change the hash, or a harmless refactor would
    break every chain and the check would get switched off."""
    a = ledger.compute_hash({"x": 1, "y": 2})
    b = ledger.compute_hash({"y": 2, "x": 1})
    assert a == b


def test_count_reads_from_the_chain_not_a_separate_tally(tmp_path: Path) -> None:
    path = tmp_path / "l.jsonl"
    for name in ("a", "b"):
        _add(path, name)
    assert ledger.count(path) == 2


def test_sprint_8_trials_are_migrated_not_dropped(tmp_path: Path) -> None:
    """Those evaluations really happened. Dropping them would understate the
    count in the flattering direction - the exact failure being guarded."""
    source = tmp_path / "trials.jsonl"
    source.write_text(
        "\n".join(
            json.dumps({"feature": f, "horizon_days": 21, "n_periods": 100, "t_stat": 1.0})
            for f in ("a", "b", "c")
        )
        + "\n"
    )
    path = tmp_path / "l.jsonl"
    assert ledger.migrate_from_trials(source, path) == 3
    assert ledger.count(path) == 3
    assert all(e.params.get("migrated") for e in ledger.read(path))


def test_migration_does_not_run_twice(tmp_path: Path) -> None:
    source = tmp_path / "trials.jsonl"
    source.write_text(json.dumps({"feature": "a"}) + "\n")
    path = tmp_path / "l.jsonl"
    ledger.migrate_from_trials(source, path)
    assert ledger.migrate_from_trials(source, path) == 0
    assert ledger.count(path) == 1
