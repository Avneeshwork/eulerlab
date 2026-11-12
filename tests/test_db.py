"""Postgres as the trial ledger's home (ADR-165): same API, same chain, edits refused.

These run against a throwaway Postgres: `EULERLAB_TEST_DATABASE_URL` when set
(the compose service, a CI database), else a server started for the session
from the local Postgres binaries. With neither, they skip; everything else in
the suite runs on files, which is what the Mac uses until the setting is made.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from eulerlab import db, evidence, paths
from eulerlab.db import importer
from eulerlab.db.stream import NotImported, Stream, stream_for, stream_name
from eulerlab.validation import ledger

psycopg = pytest.importorskip("psycopg")


def _bindir() -> Path | None:
    candidates = []
    if shutil.which("pg_config"):
        out = subprocess.run(["pg_config", "--bindir"], capture_output=True, text=True, check=False)
        candidates.append(Path(out.stdout.strip()))
    candidates += sorted(Path("/usr/lib/postgresql").glob("*/bin"), reverse=True)
    candidates += sorted(Path("/opt/homebrew/opt").glob("postgresql@*/bin"), reverse=True)
    return next((c for c in candidates if (c / "initdb").exists()), None)


@pytest.fixture(scope="session")
def server() -> Iterator[str]:
    """A connection string to a Postgres server the tests may create databases on."""
    url = os.environ.get("EULERLAB_TEST_DATABASE_URL", "").strip()
    if url:
        yield url
        return
    bindir = _bindir()
    if bindir is None:
        pytest.skip("no Postgres: set EULERLAB_TEST_DATABASE_URL or install postgresql")
    # Not tmp_path_factory: pytest's base directory is private to its owner, and
    # the cluster runs as `postgres` when the suite runs as root.
    root = Path(tempfile.mkdtemp(prefix="eulerlab-pg-"))
    as_user: list[str] = []
    if os.geteuid() == 0:  # initdb refuses to run as root
        if shutil.which("runuser") is None:
            pytest.skip("running as root without runuser")
        shutil.chown(root, "postgres")
        as_user = ["runuser", "-u", "postgres", "--"]
    port = 54000 + os.getpid() % 900
    subprocess.run(
        [
            *as_user,
            str(bindir / "initdb"),
            "-D",
            str(root / "data"),
            "-A",
            "trust",
            "-U",
            "eulerlab",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            *as_user,
            str(bindir / "pg_ctl"),
            "-D",
            str(root / "data"),
            "-o",
            f"-k {root} -c listen_addresses='' -p {port}",
            "-l",
            str(root / "log"),
            "-w",
            "start",
        ],
        check=True,
        capture_output=True,
    )
    try:
        yield f"postgresql://eulerlab@/postgres?host={root}&port={port}"
    finally:
        subprocess.run(
            [*as_user, str(bindir / "pg_ctl"), "-D", str(root / "data"), "-m", "fast", "stop"],
            check=False,
            capture_output=True,
        )
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def database(server: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    """A fresh, migrated database, the data directory at tmp_path, the setting on."""
    name = f"t_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(server, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    url = server.replace("/postgres?", f"/{name}?")
    monkeypatch.setenv(db.ENV_VAR, url)
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path))
    db.migrate()
    return url


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
