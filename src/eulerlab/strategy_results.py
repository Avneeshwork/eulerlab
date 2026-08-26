"""Every measured strategy result, in one file, discriminated by what it asked.

Two files held the identical 25-field schema: `adopted_results.jsonl` for each
strategy on its paper's market, and `us_all_results.jsonl` for every strategy on
QQQ. Same dataclass, same writer, same reader — separated only by filename.

That is a comparison encoded as a directory listing. `_best_asset` had to open
both and `max` across them, which works and quietly assumes the two files are
the only ones, that neither is stale relative to the other, and that a strategy
present in one is comparable to itself in the other. None of that is checked by
anything, because there is nothing to check it in.

One file with a `kind` column makes the comparison a query. Adding a third
question — the same strategy on a third market — becomes a new value rather
than a new file and a new reader and a new `max`.

### Migration

`load()` reads the merged file and falls back to the two legacy ones, so this
works before `make migrate-results` has run and keeps working after. The
fallback is deliberately silent: an operator who has not migrated should see
correct data, not an error about file layout.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RESULTS_PATH = Path("data/derived/strategy_results.jsonl")

LEGACY = (
    (Path("data/derived/adopted_results.jsonl"), "home"),
    (Path("data/derived/us_all_results.jsonl"), "us_cross"),
)
"""The two files this replaces, with the `kind` each one implied by its name."""

HOME = "home"
"""The strategy on the market its paper tested, with its adopted parameters."""

US_CROSS = "us_cross"
"""The same strategy on QQQ, whatever market its paper used. For the ten crypto
signals this is the only US evidence there is."""


@dataclass(frozen=True)
class Row:
    """One result and the question it answers."""

    kind: str
    data: dict[str, Any]

    @property
    def strategy_id(self) -> str:
        return str(self.data.get("strategy_id", ""))

    @property
    def sharpe(self) -> float | None:
        value = self.data.get("sharpe")
        return float(value) if isinstance(value, int | float) else None


def load(path: Path = RESULTS_PATH) -> list[Row]:
    """Every result, merged file first, legacy files as a fallback."""
    rows = _read(path)
    if rows:
        return rows

    out: list[Row] = []
    for legacy_path, kind in LEGACY:
        out.extend(Row(kind=kind, data=row) for row in _rows_of(legacy_path))
    return out


def by_kind(kind: str, path: Path = RESULTS_PATH) -> dict[str, dict[str, Any]]:
    """One kind of result, keyed by strategy — the shape callers already use."""
    return {row.strategy_id: row.data for row in load(path) if row.kind == kind}


def for_strategy(strategy_id: str, path: Path = RESULTS_PATH) -> list[Row]:
    """Every measurement of one strategy, across every question asked of it.

    What `_best_asset` wants: the candidates to compare, without knowing how
    many files they came from or how many there will be next time.
    """
    return [row for row in load(path) if row.strategy_id == strategy_id]


def write(rows: list[Row], path: Path = RESULTS_PATH) -> None:
    """Replace the merged file. Callers that write a subset must merge first."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps({"kind": r.kind, **r.data}, sort_keys=True) + "\n" for r in rows),
        encoding="utf-8",
    )


def merge(kind: str, results: list[dict[str, Any]], path: Path = RESULTS_PATH) -> None:
    """Write these results of this kind, leaving every other row untouched.

    Keyed on `(kind, strategy_id)`: re-running the US cross-test must not
    disturb a strategy's home-market result, and vice versa. Replacing the file
    is how a subset run wiped twenty strategies twice already.
    """
    existing = {(row.kind, row.strategy_id): row for row in load(path)}
    for data in results:
        row = Row(kind=kind, data=data)
        existing[(kind, row.strategy_id)] = row
    write(sorted(existing.values(), key=lambda r: (r.strategy_id, r.kind)), path)


def _read(path: Path) -> list[Row]:
    out: list[Row] = []
    for data in _rows_of(path):
        kind = str(data.pop("kind", "")) or HOME
        out.append(Row(kind=kind, data=data))
    return out


def _rows_of(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("strategy_id"):
            out.append(row)
    return out


def migrate() -> int:
    """Fold the two legacy files into one. Returns rows written."""
    rows: list[Row] = []
    for legacy_path, kind in LEGACY:
        rows.extend(Row(kind=kind, data=row) for row in _rows_of(legacy_path))
    write(sorted(rows, key=lambda r: (r.strategy_id, r.kind)))
    return len(rows)


def main() -> int:
    written = migrate()
    print(f"merged {written} results into {RESULTS_PATH}")
    print("the legacy files are left in place; delete them once this looks right")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
