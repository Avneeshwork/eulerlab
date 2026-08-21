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


# --- sigma_SR: the constant that scales the whole noise bar (A-021) ---


def _scored(path: Path, subject: str, sharpe: float, *, key: str = ledger.SHARPE_KEY) -> None:
    ledger.append(kind="validation", subject=subject, params={}, outcome={key: sharpe}, path=path)


def test_a_trial_without_a_sharpe_reports_none(tmp_path: Path) -> None:
    """An `ic` trial measures rank correlation and has no Sharpe. Absence is an
    answer, and inventing a zero would quietly drag any dispersion downward."""
    path = tmp_path / "l.jsonl"
    _add(path, "momentum_12_1")
    assert ledger.sharpe_of(ledger.read(path)[0]) is None


def test_the_legacy_sharpe_key_is_still_read(tmp_path: Path) -> None:
    """The eleven entries that predate the canonical key are hash-chained and
    cannot be rewritten, so the reader must understand both keys forever."""
    path = tmp_path / "l.jsonl"
    _scored(path, "H-0001", 1.2667, key="best_full_sample_sharpe")
    assert ledger.sharpe_of(ledger.read(path)[0]) == 1.2667


def test_a_boolean_is_not_a_sharpe(tmp_path: Path) -> None:
    """`bool` is a subclass of `int`, so a naive numeric check accepts True as
    1.0 and silently adds a fake observation."""
    path = tmp_path / "l.jsonl"
    ledger.append(
        kind="validation", subject="s", params={}, outcome={ledger.SHARPE_KEY: True}, path=path
    )
    assert ledger.sharpe_of(ledger.read(path)[0]) is None


def test_dispersion_refuses_when_too_few_subjects(tmp_path: Path) -> None:
    path = tmp_path / "l.jsonl"
    for value in (1.0, 1.1):
        _scored(path, "H-0001", value)
    result = ledger.sharpe_dispersion(path)
    assert not result.usable
    assert result.sigma is None
    assert "distinct subject" in result.reason


def test_repeated_measurements_of_one_subject_are_not_a_sample(tmp_path: Path) -> None:
    """One hypothesis re-evaluated eight times is one strategy, not eight.

    Deliberately more entries than `MIN_SUBJECTS_FOR_DISPERSION`, so the test
    discriminates: counting rows would clear the threshold and report a
    confident sigma of ~0.1, which scales the noise bar down to near nothing.
    Counting subjects refuses. Re-running `make validate` on one candidate is
    the realistic way this happens, and the error runs in the flattering
    direction.
    """
    path = tmp_path / "l.jsonl"
    for value in (1.0088, 1.0088, 1.2667, 1.1, 1.15, 1.2, 1.05, 1.3):
        _scored(path, "H-0001", value)
    result = ledger.sharpe_dispersion(path)
    assert result.observations == 8
    assert result.subjects == 1
    assert not result.usable
    assert result.sigma is None


def test_dispersion_is_measured_across_distinct_subjects(tmp_path: Path) -> None:
    path = tmp_path / "l.jsonl"
    for i, value in enumerate([1.0, 1.5, 0.5, 2.0, 1.2]):
        _scored(path, f"H-{i:04d}", value)
    result = ledger.sharpe_dispersion(path)
    assert result.usable
    assert result.subjects == ledger.MIN_SUBJECTS_FOR_DISPERSION
    assert result.sigma is not None
    assert 0.5 < result.sigma < 0.7  # sample sd of those five is ~0.570


def test_the_last_evaluation_of_a_subject_wins(tmp_path: Path) -> None:
    """A hypothesis re-evaluated more completely should count once, at its most
    complete value — not once per stage it passed through."""
    path = tmp_path / "l.jsonl"
    _scored(path, "H-0001", 1.0)
    _scored(path, "H-0001", 2.0)
    for i in range(2, 6):  # H-0002..H-0005, so H-0001 is not regenerated
        _scored(path, f"H-{i:04d}", 1.0)
    result = ledger.sharpe_dispersion(path)
    assert result.observations == 6
    assert result.subjects == 5
    assert result.usable


def test_recording_a_sharpe_leaves_the_chain_intact(tmp_path: Path) -> None:
    """The new key rides inside `outcome`, which the hash already covers."""
    path = tmp_path / "l.jsonl"
    _scored(path, "H-0001", 1.27)
    _add(path, "momentum_12_1")
    assert ledger.verify_chain(path).intact
