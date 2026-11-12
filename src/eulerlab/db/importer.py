"""`make db-import` — copy the trial ledger files into Postgres, and prove the copy.

Run once per install, after `make db-migrate`, when `EULERLAB_DATABASE_URL`
is first set. Safe to run again: a stream already in the database must match
the file line for line as far as it goes, and only the lines after that are
added. A mismatch means the two have diverged, and the import refuses rather
than pick a winner (the same rule as the reconciler: look, do not guess).

The files are not touched. The landing-zone rule (raw data is never edited or
deleted) applies in spirit: the file stays as the record of what was true
before the switch, and from the switch on the database is the ledger.

After the copy, every imported stream's hash chain is verified *from the
database*, through the same `ledger.verify_chain` the gate runs.

Which files: the shared ledger (`derived/trial_ledger.jsonl`) and each
workspace's (`workspaces/*/trial_ledger.jsonl`, `workspace.py`). The order
journals are not imported yet: paper books reset theirs by deleting the file,
which an append-only table cannot express, so they wait for a design with
journal generations (T-4561).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from eulerlab import db
from eulerlab.db.stream import Stream, parse_time, stream_name
from eulerlab.paths import data_dir
from eulerlab.validation import ledger


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


def import_ledger(path: Path) -> Imported:
    name = stream_name(path)
    if name is None:
        msg = f"{path} is not under the data directory {data_dir()}"
        raise ValueError(msg)
    stream = Stream(ledger.KIND, name)
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    have = stream.read()
    if len(have) > len(lines):
        msg = f"{name}: the database holds {len(have)} lines, the file only {len(lines)}"
        raise Diverged(msg)
    for i, (db_line, file_line) in enumerate(zip(have, lines, strict=False), start=1):
        if db_line != file_line:
            msg = f"{name}: line {i} differs between the database and the file"
            raise Diverged(msg)
    rest = lines[len(have) :]
    added = stream.append_many(
        [(line, parse_time(str(json.loads(line)["logged_at"]))) for line in rest]
    )
    chain = ledger.verify_chain(path)
    if not chain.intact:
        msg = (
            f"{name}: imported, but the chain read back from the database is broken: {chain.detail}"
        )
        raise Diverged(msg)
    return Imported(name, len(lines), len(have), added, chain.detail)


def main() -> int:
    if not db.configured():
        print(f"{db.ENV_VAR} is not set: nothing to import into.")
        return 2
    db.migrate()
    files = ledger_files()
    if not files:
        print("no trial ledger files under the data directory; nothing to import")
        return 0
    failed = False
    for path in files:
        try:
            done = import_ledger(path)
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
