"""The journal: durability, and refusing to look healthier than it is.

The failure this file is really guarding against is a journal that returns an
empty list when it is actually damaged. Everything downstream — positions,
reconciliation, recovery — believes what it is told, so "no orders" from a
corrupt file is worse than a crash.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eulerlab.oms.journal import CorruptJournal, Journal, verify_replay
from eulerlab.oms.states import Event, OrderState


def _journal(tmp_path: Path) -> Journal:
    return Journal(tmp_path / "orders.jsonl")


def _three(journal: Journal) -> None:
    journal.append("A", Event.CREATED, OrderState.INTENT, {"symbol": "X"})
    journal.append("A", Event.SEND_OK, OrderState.SENT, {})
    journal.append("A", Event.FILL, OrderState.FILLED, {"filled_quantity": 5})


def test_an_empty_journal_reads_as_empty(tmp_path: Path) -> None:
    assert _journal(tmp_path).read() == []


def test_events_round_trip(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    _three(journal)
    entries = Journal(tmp_path / "orders.jsonl").read()
    assert [e.event for e in entries] == [Event.CREATED, Event.SEND_OK, Event.FILL]
    assert entries[-1].state is OrderState.FILLED
    assert entries[-1].detail["filled_quantity"] == 5


def test_sequence_numbers_continue_across_processes(tmp_path: Path) -> None:
    """A new Journal object on the same file must not restart at 1, or every
    later read fails the gap check for a reason that is our own doing."""
    _three(_journal(tmp_path))
    second = _journal(tmp_path)
    entry = second.append("B", Event.CREATED, OrderState.INTENT, {})
    assert entry.seq == 4


def test_a_torn_final_line_is_dropped(tmp_path: Path) -> None:
    """Crashing mid-write is normal. The event never completed, so it never
    happened."""
    path = tmp_path / "orders.jsonl"
    _three(_journal(tmp_path))
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"seq": 4, "at": "2026-0')
    assert len(Journal(path).read()) == 3


def test_a_corrupt_line_in_the_middle_raises(tmp_path: Path) -> None:
    path = tmp_path / "orders.jsonl"
    _three(_journal(tmp_path))
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[1] = "not json at all"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(CorruptJournal, match="not the last"):
        Journal(path).read()


def test_a_deleted_line_is_detected(tmp_path: Path) -> None:
    """Sequence numbers exist for exactly this. Removing an event is the edit
    that would otherwise leave no trace."""
    path = tmp_path / "orders.jsonl"
    _three(_journal(tmp_path))
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")
    with pytest.raises(CorruptJournal, match="missing"):
        Journal(path).read()


def test_replay_gives_the_current_state_of_every_order(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    _three(journal)
    journal.append("B", Event.CREATED, OrderState.INTENT, {})
    journal.append("B", Event.SEND_AMBIGUOUS, OrderState.UNKNOWN, {})
    assert journal.replay() == {"A": OrderState.FILLED, "B": OrderState.UNKNOWN}


def test_verify_replay_finds_a_state_that_the_machine_disagrees_with(tmp_path: Path) -> None:
    """The recorded state and the state machine are two independent claims.
    Checking one against the other is the point of recording both."""
    journal = _journal(tmp_path)
    journal.append("A", Event.CREATED, OrderState.INTENT, {})
    journal.append("A", Event.SEND_OK, OrderState.FILLED, {})  # machine says SENT
    problems = verify_replay(journal)
    assert len(problems) == 1
    assert "recorded filled" in problems[0]
    assert "machine says sent" in problems[0]


def test_verify_replay_is_silent_on_a_healthy_journal(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    _three(journal)
    assert verify_replay(journal) == []


def test_reload_picks_up_another_process_writing(tmp_path: Path) -> None:
    path = tmp_path / "orders.jsonl"
    first = _journal(tmp_path)
    _three(first)
    assert len(first.read()) == 3

    second = Journal(path)
    second.append("B", Event.CREATED, OrderState.INTENT, {})

    assert len(first.read()) == 3, "the cached view should not change on its own"
    assert len(first.reload()) == 4, "reload must go back to the file"


def test_history_is_per_order(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    _three(journal)
    journal.append("B", Event.CREATED, OrderState.INTENT, {})
    assert len(journal.history("A")) == 3
    assert len(journal.history("B")) == 1
