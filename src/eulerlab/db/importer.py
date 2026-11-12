"""`make db-import` — copy the trial ledger and order journal files into Postgres, and prove the copy.

Run once per install, after `make db-migrate`, when `EULERLAB_DATABASE_URL`
is first set. Safe to run again: a stream already in the database must match
the file line for line as far as it goes, and only the lines after that are
added. A mismatch means the two have diverged, and the import refuses rather
than pick a winner (the same rule as the reconciler: look, do not guess).

The files are not touched. The landing-zone rule (raw data is never edited or
deleted) applies in spirit: the file stays as the record of what was true
before the switch, and from the switch on the database is the ledger.

After the copy, every imported stream is checked *from the database*: the
ledger's hash chain through `ledger.verify_chain`, the gate's own check, and a
journal's sequence through `Journal.read`, which refuses a gap.

Which files: the shared ledger (`derived/trial_ledger.jsonl`) and each
workspace's (`workspaces/*/trial_ledger.jsonl`, `workspace.py`), the trials
counter (`derived/trials.jsonl`, `features/trials.py`), and every
order journal under `oms/` and `deployments/` (`orders.jsonl`). A journal's
torn final line, left by a crash mid-write, is not imported: the journal
itself treats that event as never having happened. Files go into generation 1
of their stream; a reset after the switch is a later generation (ADR-166), so
importing again still compares against what the file held.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from eulerlab import db
from eulerlab.db.stream import Stream, file_lines, parse_time, stream_name
from eulerlab.features import trials
from eulerlab.oms import journal
from eulerlab.paths import data_dir
from eulerlab.validation import ledger

TIME_KEY = {ledger.KIND: "logged_at", trials.KIND: "logged_at", journal.KIND: "at"}
"""Which field of a line is its event time, per kind."""


class Diverged(RuntimeError):
    """The database and the file disagree about a line both hold."""


@dataclass(frozen=True)
class Imported:
    stream: str
    in_file: int
    already: int
    added: int
    chain: str


def ledger_files(root: Path | None = None) -> list[Path]:
    base = root or data_dir()
    found = [base / "derived" / "trial_ledger.jsonl"]
    found += sorted((base / "workspaces").glob("*/trial_ledger.jsonl"))
    return [p for p in found if p.exists()]


def journal_files(root: Path | None = None) -> list[Path]:
    base = root or data_dir()
    found = sorted((base / "oms").rglob("orders.jsonl"))
    found += sorted((base / "deployments").glob("*/orders.jsonl"))
    return found


def trials_files(root: Path | None = None) -> list[Path]:
    path = (root or data_dir()) / "derived" / "trials.jsonl"
    return [path] if path.exists() else []


def import_ledger(path: Path) -> Imported:
    return import_stream(path, ledger.KIND)


def import_journal(path: Path) -> Imported:
    return import_stream(path, journal.KIND)


def _check(path: Path, kind: str) -> tuple[bool, str]:
    """Read the imported stream back from the database, through its own reader."""
    if kind == ledger.KIND:
        chain = ledger.verify_chain(path)
        return chain.intact, chain.detail
    if kind == trials.KIND:
        n, in_file = trials.count(path), len(file_lines(path))
        return n >= in_file, f"{n} trials read back from the database ({in_file} in the file)"
    try:
        n = len(journal.Journal(path).read())
    except journal.CorruptJournal as exc:
        return False, str(exc)
    return True, f"journal reads back whole: {n} events, seq 1 to {n}"


def import_stream(path: Path, kind: str) -> Imported:
    name = stream_name(path)
    if name is None:
        msg = f"{path} is not under the data directory {data_dir()}"
        raise ValueError(msg)
    stream = Stream(kind, name)
    lines = file_lines(path)
    have = stream.read()
    # More rows than the file is normal once the switch is made: the database
    # carried on from where the file stopped. Only the file's lines are compared.
    for i, (db_line, file_line) in enumerate(zip(have, lines, strict=False), start=1):
        if db_line != file_line:
            msg = f"{name}: line {i} differs between the database and the file"
            raise Diverged(msg)
    rest = lines[len(have) :]
    added = stream.append_many(
        [(line, parse_time(str(json.loads(line)[TIME_KEY[kind]]))) for line in rest]
    )
    whole, detail = _check(path, kind)
    if not whole:
        msg = f"{name}: imported, but what reads back from the database is not whole: {detail}"
        raise Diverged(msg)
    return Imported(name, len(lines), len(have), added, detail)


def main() -> int:
    if not db.configured():
        print(f"{db.ENV_VAR} is not set: nothing to import into.")
        return 2
    db.migrate()
    files = [(p, ledger.KIND) for p in ledger_files()]
    files += [(p, trials.KIND) for p in trials_files()]
    files += [(p, journal.KIND) for p in journal_files()]
    if not files:
        print("no ledger or journal files under the data directory; nothing to import")
        return 0
    failed = False
    for path, kind in files:
        try:
            done = import_stream(path, kind)
        except Diverged as exc:
            print(f"REFUSED {exc}")
            failed = True
            continue
        print(
            f"{done.stream}: {done.in_file} lines in the file, {done.already} already in the "
            f"database, {done.added} added. {done.chain}"
        )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
