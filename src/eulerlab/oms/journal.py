"""The write-ahead order journal.

**The intent is durable before the network call.** That ordering is the whole
design, and everything the chaos tests prove follows from it. Write the
intention to disk, `fsync` it, *then* send. If the process dies at any point
after that, recovery finds an order it knows it meant to place and can go ask
the broker what became of it.

Reverse the order — send first, record after — and a crash in between leaves an
order at the exchange that no local record mentions. Nothing will ever
reconcile it, because reconciliation compares against a list that does not
contain it. That is the one failure mode in an OMS with no recovery path, and
it is avoided by two lines in the right sequence rather than by any cleverness
later.

**A torn final line is dropped; a torn line anywhere else raises.** Crashing
mid-`write` is normal and expected, and the event it was recording never
completed, so discarding it is correct. Malformed JSON in the *middle* of the
file cannot have come from a crash — the lines after it were written
successfully — so it means corruption or editing, and the journal refuses to
load.

**Sequence numbers, not a hash chain.** The trial ledger is hash-chained
because someone has a standing incentive to delete rows from it (every
statistic improves as the trial count falls). Nobody gains from deleting order
history, and the property actually needed here is *did we lose an event*,
which strictly increasing sequence numbers answer at a fraction of the
complexity. Recovery runs on a bad day, and a simpler recovery path is worth
more than a stronger tamper proof.

**Two homes (ADR-165, ADR-166).** With `EULERLAB_DATABASE_URL` set, a journal
under the data directory is a stream in Postgres's `append_log`: a committed
insert is the durable write that the fsync is here. A reset (`reset`) then
starts a new generation of the stream instead of deleting the file, so the
orders a reset book forgot are still on record. Elsewhere, or with the
database off, the journal is the file described above.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eulerlab.db.stream import parse_time, stream_for
from eulerlab.oms.states import Event, OrderState
from eulerlab.paths import data_path

JOURNAL_PATH = data_path("oms/orders.jsonl")
KIND = "order_journal"
"""The journal's kind in the database's append-only log."""


class CorruptJournal(RuntimeError):
    """The journal cannot be trusted, so nothing built on it may run.

    Raised rather than repaired. Silently skipping a bad line would produce a
    position view that looks complete and is not, which is worse than
    stopping.
    """


@dataclass(frozen=True)
class JournalEntry:
    seq: int
    at: str
    client_order_id: str
    event: Event
    state: OrderState
    """The state *after* the event, recorded rather than recomputed so a
    replay can be compared against what the machine decided at the time."""

    detail: dict[str, Any]

    def to_json(self) -> str:
        return json.dumps(
            {
                "seq": self.seq,
                "at": self.at,
                "client_order_id": self.client_order_id,
                "event": self.event.value,
                "state": self.state.value,
                "detail": self.detail,
            },
            sort_keys=True,
        )

    @classmethod
    def from_obj(cls, obj: dict[str, Any]) -> JournalEntry:
        return cls(
            seq=int(obj["seq"]),
            at=str(obj["at"]),
            client_order_id=str(obj["client_order_id"]),
            event=Event(obj["event"]),
            state=OrderState(obj["state"]),
            detail=dict(obj.get("detail") or {}),
        )


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Journal:
    """Append-only, fsynced, replayable."""

    def __init__(self, path: Path = JOURNAL_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = stream_for(path, KIND)
        self._cache: list[JournalEntry] | None = None
        self._next_seq = self._scan_next_seq()

    def _scan_next_seq(self) -> int:
        entries = self.read()
        return entries[-1].seq + 1 if entries else 1

    def append(
        self,
        client_order_id: str,
        event: Event,
        state: OrderState,
        detail: dict[str, Any] | None = None,
    ) -> JournalEntry:
        """Record one event and do not return until it is on disk.

        The `fsync` is the point. Without it the write sits in the operating
        system's page cache, and a power loss or a hard kill takes it with no
        trace — which puts us back to sending orders we have no record of.
        """

        def make(seq: int) -> JournalEntry:
            return JournalEntry(
                seq=seq,
                at=_now(),
                client_order_id=client_order_id,
                event=event,
                state=state,
                detail=detail or {},
            )

        if self._stream is not None:
            # The database numbers it, under the stream's lock: the commit is
            # the durable write, and returns only once it is.
            made: list[JournalEntry] = []

            def line(_last: str | None, seq: int) -> tuple[str, datetime]:
                made.append(make(seq))
                return made[-1].to_json(), parse_time(made[-1].at)

            self._stream.append(line)
            entry = made[-1]
            self._next_seq = entry.seq + 1
            if self._cache is not None:
                self._cache.append(entry)
            return entry

        entry = make(self._next_seq)
        # Opened and closed per event rather than held open. The fsync
        # dominates the cost of a write by orders of magnitude, so keeping a
        # handle buys nothing measurable and costs a file descriptor that has
        # to survive forks, restarts and exceptions correctly.
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(entry.to_json() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._next_seq += 1
        if self._cache is not None:
            self._cache.append(entry)
        return entry

    def reload(self) -> list[JournalEntry]:
        """Drop the in-memory copy and re-read the file.

        Needed when another process has written to the same journal — which,
        outside the chaos tests, should not be happening, and is worth having
        to ask for explicitly.
        """
        self._cache = None
        return self.read()

    def read(self) -> list[JournalEntry]:
        """Every event, in order, with a torn tail tolerated.

        Cached after the first read and kept current by `append`. Without
        this, a paper run re-parsed the whole journal once per order — which
        is quadratic in the number of orders, and the journal is the hot path
        for every state lookup the OMS makes.
        """
        if self._cache is not None:
            return list(self._cache)
        if self._stream is not None:
            lines = self._stream.read()
            torn_tail_possible = False  # a row is whole or absent
        elif not self.path.exists():
            return []
        else:
            lines = self.path.read_text(encoding="utf-8").splitlines()
            torn_tail_possible = True
        entries: list[JournalEntry] = []
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                entries.append(JournalEntry.from_obj(json.loads(line)))
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                if torn_tail_possible and index == len(lines) - 1:
                    # A crash during the final write. That event never
                    # completed, so it never happened.
                    break
                msg = (
                    f"{self.path} line {index + 1} is unreadable and is not the last "
                    f"line, so it cannot be a torn write: {exc}"
                )
                raise CorruptJournal(msg) from exc

        for position, entry in enumerate(entries, start=1):
            if entry.seq != position:
                msg = (
                    f"{self.path}: expected seq {position}, found {entry.seq}. "
                    f"Events are missing — the journal has been edited or truncated."
                )
                raise CorruptJournal(msg)
        self._cache = entries
        return list(entries)

    def replay(self) -> dict[str, OrderState]:
        """Current state of every order the journal has ever seen.

        Reads the recorded state rather than re-deriving it. Re-deriving would
        make replay agree with the state machine by construction and prove
        nothing; `verify_replay` compares the two on purpose.
        """
        return {entry.client_order_id: entry.state for entry in self.read()}

    def history(self, client_order_id: str) -> list[JournalEntry]:
        return [e for e in self.read() if e.client_order_id == client_order_id]


def reset(path: Path, reason: str) -> None:
    """Start this journal again from empty.

    On a file, the file is deleted, as the paper books always did. In the
    database, a new generation begins and the old one stays on record
    (ADR-166); the frozen pre-switch file, if any, is left alone.
    """
    stream = stream_for(path, KIND)
    if stream is None:
        path.unlink(missing_ok=True)
    else:
        stream.next_generation(reason)


def verify_replay(journal: Journal) -> list[str]:
    """Re-derive every state from the events and report disagreements.

    An audit, not a repair. If the recorded state and the state machine
    disagree, one of them was wrong when it mattered, and the answer is to look
    rather than to pick a winner.
    """
    from eulerlab.oms.states import transition

    derived: dict[str, OrderState] = {}
    problems: list[str] = []
    for entry in journal.read():
        current = derived.get(entry.client_order_id)
        if current is None:
            derived[entry.client_order_id] = entry.state
            continue
        try:
            expected = transition(current, entry.event)
        except Exception as exc:
            problems.append(f"seq {entry.seq} {entry.client_order_id}: {exc}")
            derived[entry.client_order_id] = entry.state
            continue
        if expected is not entry.state:
            problems.append(
                f"seq {entry.seq} {entry.client_order_id}: recorded {entry.state.value}, "
                f"machine says {expected.value}"
            )
        derived[entry.client_order_id] = entry.state
    return problems
