"""A trial log that cannot be quietly edited.

`CLAUDE.md`: *Every strategy configuration evaluated increments the trial
counter in the append-only log. Never bypass it, never reset it.*

Sprint 8 built the append-only part. Append-only is a convention, though, not
a property: the file is plain JSONL on a disk anyone can write to, and the
tempting edit is not adding a fake row — it is **deleting a few real ones**.
Every statistic in this sprint gets more favourable as the trial count falls.
Deflated Sharpe rises. Minimum backtest length shrinks. The multiple-testing
correction weakens. So the one number the whole battery rests on is also the
one with the strongest incentive to shrink, and "we promised not to touch it"
is not a control.

Hash chaining fixes that. Each entry carries the hash of the entry before it,
so altering or removing any row breaks every link after it. That does not make
tampering impossible — anyone can rewrite the whole chain — but it makes it
**detectable and deliberate** rather than quiet, which is the difference
between an accident and a decision. `verify_chain` is what `make validate`
runs before it will report anything.

The genesis hash is a fixed constant rather than a random seed, so the chain
is reproducible from the file alone and two people can independently confirm
it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

LEDGER_PATH = Path("data/derived/trial_ledger.jsonl")
GENESIS = "0" * 64
"""The chain's anchor. Fixed and public so the whole chain is verifiable from
the file with no external secret."""


@dataclass(frozen=True)
class LedgerEntry:
    """One evaluated configuration, linked to its predecessor."""

    seq: int
    logged_at: str
    kind: str
    """What was evaluated: 'ic', 'backtest', 'validation'. Kept free-form
    rather than an enum because a new kind of trial must never be *harder* to
    log than to skip."""

    subject: str
    """Feature name, strategy id, or hypothesis id."""

    params: dict[str, object]
    outcome: dict[str, object]
    prev_hash: str
    entry_hash: str

    def payload(self) -> dict[str, object]:
        """Exactly the fields the hash covers."""
        return {
            "seq": self.seq,
            "logged_at": self.logged_at,
            "kind": self.kind,
            "subject": self.subject,
            "params": self.params,
            "outcome": self.outcome,
            "prev_hash": self.prev_hash,
        }


def compute_hash(payload: dict[str, object]) -> str:
    """Hash a payload deterministically.

    `sort_keys` matters: dict ordering must not change the hash, or a chain
    would fail to verify after a harmless refactor and the check would be
    switched off.
    """
    material = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode()).hexdigest()


def read(path: Path = LEDGER_PATH) -> list[LedgerEntry]:
    if not path.exists():
        return []
    out: list[LedgerEntry] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        out.append(
            LedgerEntry(
                seq=int(row["seq"]),
                logged_at=str(row["logged_at"]),
                kind=str(row["kind"]),
                subject=str(row["subject"]),
                params=dict(row["params"]),
                outcome=dict(row["outcome"]),
                prev_hash=str(row["prev_hash"]),
                entry_hash=str(row["entry_hash"]),
            )
        )
    return out


def append(
    *,
    kind: str,
    subject: str,
    params: dict[str, object],
    outcome: dict[str, object],
    path: Path = LEDGER_PATH,
) -> LedgerEntry:
    """Add one trial, linked to whatever came before. Returns the new entry.

    There is deliberately no update, no delete, and no way to write a
    `seq` or a `prev_hash` from outside — both are derived from the existing
    chain, so a caller cannot insert a row in the middle even by accident.
    """
    existing = read(path)
    prev_hash = existing[-1].entry_hash if existing else GENESIS
    payload: dict[str, object] = {
        "seq": len(existing) + 1,
        "logged_at": datetime.now(UTC).isoformat(),
        "kind": kind,
        "subject": subject,
        "params": params,
        "outcome": outcome,
        "prev_hash": prev_hash,
    }
    entry = LedgerEntry(**payload, entry_hash=compute_hash(payload))  # type: ignore[arg-type]

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(entry), sort_keys=True) + "\n")
    return entry


@dataclass(frozen=True)
class ChainStatus:
    intact: bool
    entries: int
    broken_at: int | None
    detail: str


def verify_chain(path: Path = LEDGER_PATH) -> ChainStatus:
    """Walk the chain and report the first break.

    Reports the *first* break rather than counting them, because after one
    broken link every subsequent hash mismatches too — a count would suggest
    widespread corruption when the truth is one edited row.
    """
    entries = read(path)
    if not entries:
        return ChainStatus(True, 0, None, "empty ledger; nothing has been evaluated yet")

    expected_prev = GENESIS
    for entry in entries:
        if entry.prev_hash != expected_prev:
            return ChainStatus(
                False,
                len(entries),
                entry.seq,
                f"entry {entry.seq} points at {entry.prev_hash[:12]}... but the previous "
                f"entry hashes to {expected_prev[:12]}... — a row was edited or removed",
            )
        recomputed = compute_hash(entry.payload())
        if recomputed != entry.entry_hash:
            return ChainStatus(
                False,
                len(entries),
                entry.seq,
                f"entry {entry.seq} has been modified: its contents hash to "
                f"{recomputed[:12]}... but it records {entry.entry_hash[:12]}...",
            )
        expected_prev = entry.entry_hash

    if [e.seq for e in entries] != list(range(1, len(entries) + 1)):
        return ChainStatus(False, len(entries), None, "sequence numbers are not contiguous")

    return ChainStatus(
        True, len(entries), None, f"{len(entries)} entries, chain intact from genesis"
    )


def count(path: Path = LEDGER_PATH) -> int:
    """How many configurations have ever been evaluated.

    The denominator of every multiple-testing correction in this sprint. It is
    read from the chain rather than tracked separately so it cannot drift from
    the evidence.
    """
    return len(read(path))


SHARPE_KEY = "sharpe"
"""The canonical place a trial records the Sharpe it realised.

New writers use this. `sharpe_of` also accepts the older
`best_full_sample_sharpe`, because the ledger is append-only and hash-chained:
renaming a key in the eleven entries that already exist would rewrite history
and break every link after it, which is precisely the tampering the chain is
built to expose. Old rows keep their old key forever.
"""

_LEGACY_SHARPE_KEYS = ("best_full_sample_sharpe",)


def sharpe_of(entry: LedgerEntry) -> float | None:
    """The Sharpe this trial realised, or None when it never produced one.

    None is a real answer, not a gap to paper over. An `ic` trial measures rank
    correlation between a feature and forward returns; it has no Sharpe to
    report, and inventing one would be worse than admitting the absence.
    """
    for key in (SHARPE_KEY, *_LEGACY_SHARPE_KEYS):
        value = entry.outcome.get(key)
        if isinstance(value, int | float) and not isinstance(value, bool):
            return float(value)
    return None


MIN_SUBJECTS_FOR_DISPERSION = 5
"""Distinct strategies needed before a dispersion of Sharpes means anything.

A judgement, not a result. A standard deviation exists at two points and is
worthless there; five is the point at which it stops being an artefact of which
two things happened to be measured. Set deliberately so that refusing is the
default — the failure this guards against is quoting a confident sigma computed
from almost nothing, which would scale the entire noise bar.
"""


@dataclass(frozen=True)
class Dispersion:
    """How much the Sharpes of distinct evaluated strategies vary.

    This is sigma_SR in the expected-maximum-Sharpe correction, where it scales
    the whole bar. `usable` is False far more often than people expect, and the
    honest response to that is to say so rather than to return a number anyway.
    """

    observations: int
    """Ledger entries carrying a Sharpe at all."""

    subjects: int
    """Distinct subjects among them. This is the number that matters."""

    sigma: float | None
    usable: bool
    reason: str


def sharpe_dispersion(path: Path = LEDGER_PATH) -> Dispersion:
    """Measure sigma_SR from the ledger, or explain why it cannot be measured.

    **One Sharpe per subject, not one per entry.** H-0001 appears three times
    with Sharpes 1.0088, 1.0088 and 1.2667 — that is one hypothesis measured at
    three stages, not three strategies. Averaging them into a sample of three
    would report the noise of our own re-measurement as if it were the spread
    between different ideas, and it would shrink sigma toward zero, which lowers
    the bar. The flattering direction is exactly the one to distrust.

    The last value per subject wins, being the most complete evaluation.
    """
    entries = read(path)
    scored = [(e.subject, s) for e in entries if (s := sharpe_of(e)) is not None]

    by_subject: dict[str, float] = {}
    for subject, value in scored:
        by_subject[subject] = value

    observations, subjects = len(scored), len(by_subject)
    if subjects < MIN_SUBJECTS_FOR_DISPERSION:
        return Dispersion(
            observations=observations,
            subjects=subjects,
            sigma=None,
            usable=False,
            reason=(
                f"{observations} entr{'y' if observations == 1 else 'ies'} carry a Sharpe, "
                f"covering {subjects} distinct subject{'' if subjects == 1 else 's'}; "
                f"{MIN_SUBJECTS_FOR_DISPERSION} are needed before a dispersion means anything. "
                f"Until then the bar's assumed sigma is an assumption, not a measurement (A-021)"
            ),
        )

    values = list(by_subject.values())
    mean = sum(values) / len(values)
    sigma = (sum((v - mean) ** 2 for v in values) / (len(values) - 1)) ** 0.5
    return Dispersion(
        observations=observations,
        subjects=subjects,
        sigma=sigma,
        usable=True,
        reason=f"measured across {subjects} distinct subjects",
    )


def migrate_from_trials(source: Path, path: Path = LEDGER_PATH) -> int:
    """Fold Sprint 8's unchained `trials.jsonl` into the chain.

    Those trials really happened, so dropping them would understate the count
    in the flattering direction — the exact failure the ledger exists to
    prevent. They are marked `migrated` in their params, because a chain built
    over rows that were never hash-linked can only attest to what it has held
    since, and claiming otherwise would be the same dishonesty one layer up.
    """
    if not source.exists() or read(path):
        return 0
    added = 0
    for line in source.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        append(
            kind="ic",
            subject=str(row.get("feature", "unknown")),
            params={
                "horizon_days": row.get("horizon_days"),
                "step_days": row.get("step_days"),
                "panel_start": row.get("panel_start"),
                "panel_end": row.get("panel_end"),
                "migrated": True,
            },
            outcome={
                "n_periods": row.get("n_periods"),
                "mean_ic": row.get("mean_ic"),
                "t_stat": row.get("t_stat"),
            },
            path=path,
        )
        added += 1
    return added
