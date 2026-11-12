"""Postgres as the trial ledger's home (ADR-165): same API, same chain, edits refused.

These run against a throwaway Postgres (the `server` and `database` fixtures
in `conftest.py`). Without one they skip; everything else in the suite runs
on files, which is what the Mac uses until the setting is made.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest

from eulerlab import db, evidence, paths
from eulerlab.agents import log as agent_log
from eulerlab.db import export as db_export
from eulerlab.db import importer
from eulerlab.db.stream import NotImported, Stream, stream_for, stream_name
from eulerlab.features import trials
from eulerlab.oms import journal
from eulerlab.oms.states import Event, OrderState
from eulerlab.validation import ledger

psycopg = pytest.importorskip("psycopg")


def _ledger_path(tmp_path: Path) -> Path:
    return tmp_path / "derived" / "trial_ledger.jsonl"


# --- setting and naming -----------------------------------------------------------------------


def test_off_means_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(db.ENV_VAR, raising=False)
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path))
    assert stream_for(_ledger_path(tmp_path), ledger.KIND) is None


def test_a_path_outside_the_data_directory_stays_a_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(db.ENV_VAR, "postgresql://nowhere/none")
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path / "data"))
    assert stream_for(tmp_path / "elsewhere" / "trial_ledger.jsonl", ledger.KIND) is None
    assert stream_name(tmp_path / "data" / "derived" / "x.jsonl") == "derived/x.jsonl"


def test_migrations_are_numbered_without_gaps() -> None:
    versions = [v for v, _, _ in db.migrations()]
    assert versions == list(range(1, len(versions) + 1))


# --- the ledger in Postgres -------------------------------------------------------------------


def test_migrate_is_idempotent(database: str) -> None:
    assert db.migrate() == []


def test_the_ledger_appends_reads_and_verifies_from_postgres(database: str, tmp_path: Path) -> None:
    path = _ledger_path(tmp_path)
    first = ledger.append(
        kind="backtest", subject="H-1", params={"a": 1}, outcome={"sharpe": 1.2}, path=path
    )
    second = ledger.append(
        kind="backtest", subject="H-2", params={}, outcome={"sharpe": float("nan")}, path=path
    )
    assert not path.exists()  # nothing went to the file
    assert (first.seq, second.seq) == (1, 2)
    assert second.prev_hash == first.entry_hash
    assert ledger.count(path) == 2
    assert [e.subject for e in ledger.read(path)] == ["H-1", "H-2"]
    status = ledger.verify_chain(path)
    assert status.intact and status.entries == 2


def test_the_table_refuses_edits_deletes_and_gaps(database: str, tmp_path: Path) -> None:
    path = _ledger_path(tmp_path)
    ledger.append(kind="ic", subject="f", params={}, outcome={}, path=path)
    with psycopg.connect(database, autocommit=True) as conn:
        for sql in (
            "UPDATE append_log SET body = '{}'",
            "DELETE FROM append_log",
            "TRUNCATE append_log",
            "INSERT INTO append_log (kind, stream, seq, body, event_time)"
            " VALUES ('trial_ledger', 'derived/trial_ledger.jsonl', 5, '{}', now())",
        ):
            with pytest.raises(psycopg.errors.RaiseException):
                conn.execute(sql)
    assert ledger.count(path) == 1 and ledger.verify_chain(path).intact


def test_two_writers_never_fork_the_chain(database: str, tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    path = _ledger_path(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(
            pool.map(
                lambda i: ledger.append(
                    kind="ic", subject=f"s{i}", params={}, outcome={}, path=path
                ),
                range(40),
            )
        )
    status = ledger.verify_chain(path)
    assert status.intact and status.entries == 40


def test_the_noise_bar_census_counts_the_database(database: str, tmp_path: Path) -> None:
    path = _ledger_path(tmp_path)
    for i in range(3):
        ledger.append(kind="ic", subject=f"s{i}", params={}, outcome={}, path=path)
    store = next(s for s in evidence.stores() if s.name == ledger.KIND)
    store = evidence.Store(store.name, path, store.holds, store.counts_toward_bar)
    assert store.rows == 3


# --- import ------------------------------------------------------------------------------------


def _file_ledger(path: Path, n: int, monkeypatch: pytest.MonkeyPatch) -> None:
    """Write n entries the old way, with the database switched off."""
    url = os.environ[db.ENV_VAR]
    monkeypatch.delenv(db.ENV_VAR)
    for i in range(n):
        ledger.append(kind="ic", subject=f"old{i}", params={"i": i}, outcome={}, path=path)
    monkeypatch.setenv(db.ENV_VAR, url)


def test_import_copies_the_file_byte_for_byte_and_is_safe_twice(
    database: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _ledger_path(tmp_path)
    _file_ledger(path, 5, monkeypatch)
    file_lines = path.read_text().splitlines()
    done = importer.import_ledger(path)
    assert (done.in_file, done.already, done.added) == (5, 0, 5)
    assert Stream(ledger.KIND, "derived/trial_ledger.jsonl").read() == file_lines
    again = importer.import_ledger(path)
    assert (again.already, again.added) == (5, 0)
    # The chain continues from the imported rows.
    new = ledger.append(kind="ic", subject="after", params={}, outcome={}, path=path)
    assert new.seq == 6 and ledger.verify_chain(path).intact
    assert path.read_text().splitlines() == file_lines  # the file is never touched
    # Run again after the database has moved on: still safe, nothing added.
    assert importer.import_ledger(path).added == 0


def test_import_refuses_a_file_that_disagrees(
    database: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _ledger_path(tmp_path)
    _file_ledger(path, 3, monkeypatch)
    importer.import_ledger(path)
    lines = path.read_text().splitlines()
    row = json.loads(lines[1])
    row["subject"] = "edited"
    lines[1] = json.dumps(row, sort_keys=True)
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(importer.Diverged):
        importer.import_ledger(path)


def test_switching_on_before_the_import_refuses_instead_of_undercounting(
    database: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _ledger_path(tmp_path)
    _file_ledger(path, 4, monkeypatch)
    for call in (ledger.count, ledger.read, ledger.verify_chain):
        with pytest.raises(NotImported):
            call(path)
    with pytest.raises(NotImported):
        ledger.append(kind="ic", subject="x", params={}, outcome={}, path=path)
    importer.import_ledger(path)
    assert ledger.count(path) == 4


# --- order journals and generations (ADR-166) ---------------------------------------------------


def _book(tmp_path: Path) -> Path:
    return tmp_path / "oms" / "paper" / "orders.jsonl"


def _order(j: journal.Journal, coid: str) -> None:
    j.append(coid, Event.CREATED, OrderState.INTENT, {"qty": 1})
    j.append(coid, Event.SEND_OK, OrderState.SENT)


def test_a_reset_on_files_deletes_the_journal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(db.ENV_VAR, raising=False)
    path = tmp_path / "orders.jsonl"
    _order(journal.Journal(path), "a")
    journal.reset(path, "test")
    assert not path.exists() and journal.Journal(path).read() == []


def test_the_journal_writes_and_replays_from_postgres(database: str, tmp_path: Path) -> None:
    path = _book(tmp_path)
    j = journal.Journal(path)
    _order(j, "a")
    _order(j, "b")
    assert not path.exists()
    again = journal.Journal(path)  # a restart: nothing cached
    assert [e.seq for e in again.read()] == [1, 2, 3, 4]
    assert again.replay() == {"a": OrderState.SENT, "b": OrderState.SENT}
    assert journal.verify_replay(again) == []


def test_a_reset_starts_a_new_generation_and_keeps_the_old_one(
    database: str, tmp_path: Path
) -> None:
    path = _book(tmp_path)
    _order(journal.Journal(path), "a")
    journal.reset(path, "paper --reset")
    fresh = journal.Journal(path)
    assert fresh.read() == []
    _order(fresh, "b")
    assert [e.seq for e in journal.Journal(path).read()] == [1, 2]
    assert journal.Journal(path).replay() == {"b": OrderState.SENT}
    # The forgotten orders are still on record, under generation 1.
    first = Stream(journal.KIND, "oms/paper/orders.jsonl")
    assert len(first.read()) == 2
    assert stream_for(path, journal.KIND) == Stream(journal.KIND, first.name, generation=2)


def test_generations_cannot_be_edited_or_skipped(database: str, tmp_path: Path) -> None:
    path = _book(tmp_path)
    journal.reset(path, "one")
    with psycopg.connect(database, autocommit=True) as conn:
        for sql in (
            "UPDATE stream_generation SET reason = 'x'",
            "DELETE FROM stream_generation",
            "TRUNCATE stream_generation",
            "INSERT INTO stream_generation (stream, generation, reason)"
            " VALUES ('oms/paper/orders.jsonl', 4, 'skip')",
        ):
            with pytest.raises(psycopg.errors.RaiseException):
                conn.execute(sql)


def test_import_copies_a_journal_and_drops_a_torn_last_line(
    database: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _book(tmp_path)
    url = os.environ[db.ENV_VAR]
    monkeypatch.delenv(db.ENV_VAR)
    _order(journal.Journal(path), "a")
    with path.open("a") as handle:
        handle.write('{"seq": 3, "at": "2026')  # a crash mid-write
    monkeypatch.setenv(db.ENV_VAR, url)
    with pytest.raises(NotImported):
        journal.Journal(path)
    assert importer.journal_files() == [path]
    done = importer.import_journal(path)
    assert (done.in_file, done.added) == (2, 2)
    j = journal.Journal(path)
    assert [e.seq for e in j.read()] == [1, 2]
    j.append("a", Event.ACK, OrderState.ACKNOWLEDGED)
    assert journal.Journal(path).read()[-1].seq == 3
    # A reset after the switch does not make the file look unimported.
    journal.reset(path, "after the switch")
    assert importer.import_journal(path).added == 0


# --- the trials counter ------------------------------------------------------------------------


def _trial(feature: str) -> trials.Trial:
    return trials.Trial(
        trials.now_iso(), feature, 21, 21, "2020-01-01", "2024-12-31", 48, 0.01, 1.2
    )


def test_the_trials_counter_counts_from_postgres(
    database: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab.research import agent_trials

    path = tmp_path / "derived" / "trials.jsonl"
    url = os.environ[db.ENV_VAR]
    monkeypatch.delenv(db.ENV_VAR)
    trials.append(_trial("old"), path)
    trials.append(_trial(f"{agent_trials.PREFIX}card|x"), path)
    monkeypatch.setenv(db.ENV_VAR, url)
    with pytest.raises(NotImported):
        trials.count(path)
    assert importer.trials_files() == [path]
    assert importer.import_stream(path, trials.KIND).added == 2
    assert trials.append(_trial("new"), path) == 3
    assert len(path.read_text().splitlines()) == 2  # the file is never touched
    assert [json.loads(ln)["feature"] for ln in trials.lines(path)][2] == "new"
    assert agent_trials.spent_this_week(path=path) == 1
    store = next(s for s in evidence.stores() if s.name == "trials")
    assert evidence.Store(store.name, path, store.holds, store.counts_toward_bar).rows == 3


# --- the agent log -----------------------------------------------------------------------------


def test_the_agent_log_chains_in_postgres_and_imports(
    database: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "agents"
    url = os.environ[db.ENV_VAR]
    monkeypatch.delenv(db.ENV_VAR)
    agent_log.append("run", "research", {"requests": 3}, root=home)
    monkeypatch.setenv(db.ENV_VAR, url)
    with pytest.raises(NotImported):
        agent_log.read(home)
    assert importer.agent_log_files() == [home / "log.jsonl"]
    assert importer.import_stream(home / "log.jsonl", agent_log.KIND).added == 1
    second = agent_log.append("decision", "ceo", {"ok": True}, root=home)
    assert second.seq == 2 and second.prev_hash == agent_log.read(home)[0].entry_hash
    assert agent_log.verify(home) == (True, "")
    assert len((home / "log.jsonl").read_text().splitlines()) == 1


# --- backup: export and restore ----------------------------------------------------------------


def test_export_then_restore_into_an_empty_database_gives_back_every_row(
    database: str, server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger.append(
        kind="ic", subject="a", params={}, outcome={"s": float("nan")}, path=_ledger_path(tmp_path)
    )
    _order(journal.Journal(_book(tmp_path)), "a")
    journal.reset(_book(tmp_path), "test")
    _order(journal.Journal(_book(tmp_path)), "b")
    target = tmp_path / "export"
    streams, changed = db_export.export(target)
    assert (streams, changed) == (3, 4)  # ledger, journal gen 1 and 2, the generations file
    assert db_export.export(target) == (3, 0)  # unchanged: nothing for the backup to send
    with pytest.raises(RuntimeError, match="empty"):
        db_export.load(target)

    name = f"t_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(server, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    monkeypatch.setenv(db.ENV_VAR, server.replace("/postgres?", f"/{name}?"))
    db.migrate()
    assert db_export.load(target) == 1 + 2 + 2
    assert ledger.verify_chain(_ledger_path(tmp_path)).intact
    assert journal.Journal(_book(tmp_path)).replay() == {"b": OrderState.SENT}
    assert len(Stream(journal.KIND, "oms/paper/orders.jsonl").read()) == 2
