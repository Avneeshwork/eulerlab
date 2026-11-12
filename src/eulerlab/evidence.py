"""Every place a result or a trial can live, and one reader that knows them all.

Eight stores accumulated, each reasonable on its own:

| file | holds | who reads it |
|---|---|---|
| `derived/trial_ledger.jsonl` | validated hypotheses, hash-chained | the gate |
| `derived/trials.jsonl` | every configuration evaluated | `make optimize` |
| `derived/sweeps.jsonl` | parameter grids and their candidates | the library |
| `derived/adopted_results.jsonl` | each strategy on its adopted parameters | the library |
| `derived/us_all_results.jsonl` | every strategy on QQQ | the library |
| `derived/walk_results.jsonl` | walk-forward and PBO | the library |
| `workspaces/*/results/*.jsonl` | runs executed from the interface | the library |
| `workspaces/*/reports/*/*.json` | the detail behind one run | the report dialog |

### Why this module exists rather than a ninth store

The proliferation has already produced one serious bug and the shape of it is
worth stating plainly. The noise bar is computed from "how many configurations
have ever been evaluated". Two files answer that question — the hash-chained
ledger of 19 validated results, and the append-only log of 388 configurations —
and the bar was reading the first. It understated the denominator by an order
of magnitude, and every result on the platform was being judged against a bar
that had never been charged for the search that found it.

Nothing was wrong with either file. What was missing was anyone whose job it
was to know both existed.

So this is a **reader, not a store**. It writes nothing. Adding a ninth file is
fine; adding one this module does not know about is the failure being guarded
against, which is why `census()` enumerates them rather than taking a path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from eulerlab.db.stream import stream_for
from eulerlab.paths import data_path
from eulerlab.validation.ledger import KIND as ledger_kind

DERIVED = data_path("derived")


@dataclass(frozen=True)
class Store:
    """One place results live, and what it is for."""

    name: str
    path: Path
    holds: str
    counts_toward_bar: bool
    """Whether rows here are configurations the multiple-testing correction
    should be charged for. Getting this wrong in either direction is the bug
    this module exists to prevent — too few flatters, too many blocks work that
    should pass."""

    @property
    def rows(self) -> int:
        # The trial ledger lives in Postgres when the database is on (ADR-165).
        # A census that kept counting the old file would shrink the noise bar's
        # denominator, the exact failure this module exists to prevent.
        if self.name == ledger_kind:
            stream = stream_for(self.path, ledger_kind)
            if stream is not None:
                return stream.count()
        if not self.path.exists():
            return 0
        if self.path.is_dir():
            # `*.json*` rather than `*.json`: workspace runs are `.jsonl` and
            # reports are `.json`, and the narrower glob reported thirty-one
            # strategies' runs as zero — a census that misses a store is the
            # exact failure this module was written to prevent, committed by
            # the module itself.
            return sum(
                1
                for path in self.path.rglob("*.json*")
                if path.is_file()
                for _ in (
                    path.read_text(encoding="utf-8").splitlines()
                    if path.suffix == ".jsonl"
                    else [""]
                )
            )
        return sum(1 for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip())


def stores() -> list[Store]:
    """Every store, enumerated rather than assumed."""
    from eulerlab import workspace as workspace_mod

    tenant = workspace_mod.resolve(None)
    return [
        Store(
            "trial_ledger",
            DERIVED / "trial_ledger.jsonl",
            "validated hypotheses, hash-chained",
            counts_toward_bar=True,
        ),
        Store(
            "trials",
            DERIVED / "trials.jsonl",
            "every configuration evaluated",
            counts_toward_bar=True,
        ),
        Store(
            "sweeps",
            DERIVED / "sweeps.jsonl",
            "parameter grids and their candidates",
            # The candidates inside a sweep are already recorded in `trials`
            # one by one. Counting the sweep document too would charge the same
            # search twice.
            counts_toward_bar=False,
        ),
        Store(
            "adopted_results",
            DERIVED / "adopted_results.jsonl",
            "each strategy on the parameters it uses",
            counts_toward_bar=False,
        ),
        Store(
            "us_all_results",
            DERIVED / "us_all_results.jsonl",
            "every strategy on QQQ",
            counts_toward_bar=False,
        ),
        Store(
            "walk_results",
            DERIVED / "walk_results.jsonl",
            "walk-forward and PBO",
            counts_toward_bar=False,
        ),
        Store(
            "workspace_runs",
            Path(tenant.results),
            "runs executed from the interface",
            # Screening spends no trial (T-3321), which is a deliberate policy
            # and the reason the library can report how much of its own
            # evidence the bar has never seen.
            counts_toward_bar=False,
        ),
        Store(
            "workspace_reports",
            Path(tenant.root) / "reports",
            "the detail behind one run",
            counts_toward_bar=False,
        ),
    ]


def census() -> list[tuple[Store, int]]:
    """Every store with its row count. The answer to "where does evidence live"."""
    return [(store, store.rows) for store in stores()]


def bar_denominator() -> int:
    """Configurations the multiple-testing correction is charged for.

    The sum of the stores that say they count, rather than a hardcoded pair.
    `research/budget.searches_run` computes the same number directly; this is
    the auditable form, and a test holds them equal so neither can drift.
    """
    return sum(store.rows for store in stores() if store.counts_toward_bar)


def render() -> str:
    """A table an operator can read, for `make evidence`."""
    lines = [
        "",
        "-- where evidence lives --",
        f"  {'store':20s} {'rows':>8}  {'bar':>4}  holds",
    ]
    for store, rows in census():
        mark = "yes" if store.counts_toward_bar else " no"
        lines.append(f"  {store.name:20s} {rows:>8,}  {mark:>4}  {store.holds}")
    lines.append("-" * 62)
    lines.append(f"  configurations charged to the noise bar: {bar_denominator():,}")
    return "\n".join(lines)


def main() -> int:
    print(render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
