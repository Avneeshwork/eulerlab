"""Quality checks that read only the local manifests.

These cost **zero** B2 downloads, which is why they come first. The landing
zone is pruned after upload (ADR-010), so every row-level check has to pay a
transaction per file against a 2,500/day cap — a constraint that stopped the
Sprint 5 factor build outright. Anything answerable from the manifests should
therefore be answered there, and a surprising amount is: coverage, gaps,
staleness, duplicate keys, and impossible file sizes are all metadata
questions.

None of these can pass vacuously. A check over an empty manifest reports the
emptiness rather than returning no findings, because "nothing to report" and
"nothing to read" look identical in a summary and mean opposite things.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from itertools import pairwise
from pathlib import Path

from eulerlab.quality.findings import Finding, Severity

LANDING_ROOT = Path("data/landing")

EXPECTED_SEGMENTS = frozenset({"cm", "fo"})
"""Cash and F&O should both exist for a normal NSE trading day."""

STALE_AFTER = timedelta(days=5)
"""A dataset with no new data for a week of trading is probably not updating.

Five calendar days spans a weekend plus a holiday without firing, which is the
longest ordinary quiet period.
"""


def _rows(path: Path) -> Iterator[dict[str, object]]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def check_manifest_present(path: Path, dataset: str) -> list[Finding]:
    """A missing or empty manifest is a finding, never silence."""
    if not path.exists():
        return [
            Finding(
                check="manifest-present",
                severity=Severity.ERROR,
                dataset=dataset,
                detail=f"no manifest at {path}; nothing has been ingested",
            )
        ]
    if not any(_rows(path)):
        return [
            Finding(
                check="manifest-present",
                severity=Severity.ERROR,
                dataset=dataset,
                detail=f"{path} exists but holds no rows",
            )
        ]
    return []


def check_duplicate_keys(path: Path, dataset: str) -> list[Finding]:
    """A key that landed more than once, split by whether the bytes agree.

    The severity turns entirely on the hash, and the first draft of this check
    missed that. Re-landing the *same* bytes is harmless: it happens when a
    file has been pruned to B2 and a later run legitimately re-fetches it to
    confirm something, which is exactly what produced the two real instances
    in this repo during the S-009 investigation.

    Re-landing *different* bytes under the same key is a different event
    entirely. The landing zone's whole claim is that raw data is immutable
    (ADR-010 and `landing.py`), so two different contents for one
    date-and-segment means either the exchange silently revised a published
    file or our own writer overwrote history. Both are ERROR, and neither is
    something to discover later.
    """
    seen: dict[tuple[str, str], list[str]] = {}
    for row in _rows(path):
        key = (str(row.get("trade_date") or row.get("key") or ""), str(row.get("segment") or ""))
        seen.setdefault(key, []).append(str(row.get("sha256") or ""))

    out: list[Finding] = []
    for (key_id, segment), hashes in sorted(seen.items()):
        if len(hashes) < 2:
            continue
        label = f"{key_id}/{segment or '-'}"
        if len(set(hashes)) == 1:
            out.append(
                Finding(
                    check="duplicate-key",
                    severity=Severity.INFO,
                    dataset=dataset,
                    detail=f"{label} landed {len(hashes)} times, byte-identical each time",
                )
            )
        else:
            out.append(
                Finding(
                    check="content-changed",
                    severity=Severity.ERROR,
                    dataset=dataset,
                    detail=(
                        f"{label} landed {len(hashes)} times with "
                        f"{len(set(hashes))} different checksums; the landing zone "
                        f"claims raw data is immutable"
                    ),
                )
            )
    return out


def check_zero_row_files(path: Path, dataset: str) -> list[Finding]:
    """A landed file that parsed to zero rows.

    The distinction that matters is *where* the emptiness sits. A minute-bar
    window before the symbol's first data legitimately predates its listing —
    1,052 of these exist and none is a defect. A window after data has already
    started is a hole in the middle of a history, which is a real absence.

    Reporting both as one number was the first draft, and it was wrong: a
    blanket suppression for the 1,052 also hid the 3 genuine gaps, and would
    have hidden a fourth appearing tomorrow. Splitting them means the benign
    case can be silenced without ever silencing the real one.
    """
    out: list[Finding] = []
    by_symbol: dict[str, list[dict[str, object]]] = {}
    for row in _rows(path):
        by_symbol.setdefault(str(row.get("symbol") or ""), []).append(row)

    for symbol, rows in sorted(by_symbol.items()):
        rows.sort(key=lambda r: str(r.get("start") or r.get("trade_date") or ""))
        first_with_data = next(
            (i for i, r in enumerate(rows) if _row_count(r) > 0),
            None,
        )
        for index, row in enumerate(rows):
            if _row_count(row) != 0:
                continue
            before_listing = first_with_data is None or index < first_with_data
            out.append(
                Finding(
                    check="empty-chunk-pre-listing" if before_listing else "empty-chunk",
                    severity=Severity.INFO if before_listing else Severity.WARN,
                    dataset=dataset,
                    symbol=symbol,
                    day=_start_date(row),
                    detail=(
                        f"{row.get('path')} parsed to 0 rows"
                        + ("; before this symbol's first data" if before_listing else "")
                    ),
                )
            )
    return out


def _row_count(row: dict[str, object]) -> int:
    value = row.get("rows", 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _start_date(row: dict[str, object]) -> date | None:
    raw = row.get("start") or row.get("trade_date")
    try:
        return date.fromisoformat(str(raw)) if raw else None
    except ValueError:
        return None


def check_segment_coverage(path: Path, dataset: str = "nse") -> list[Finding]:
    """Every date with one NSE segment should have the other.

    A day with cash but no derivatives is either a genuine source gap or a
    failed download, and the two are indistinguishable from the manifest — so
    this reports the asymmetry and lets the documented exception (S-009) be
    suppressed by name.
    """
    by_date: dict[str, set[str]] = {}
    for row in _rows(path):
        segment = str(row.get("segment") or "")
        if segment in EXPECTED_SEGMENTS:
            by_date.setdefault(str(row.get("trade_date")), set()).add(segment)

    out: list[Finding] = []
    for day, segments in sorted(by_date.items()):
        if missing := EXPECTED_SEGMENTS - segments:
            out.append(
                Finding(
                    check="segment-coverage",
                    severity=Severity.WARN,
                    dataset=dataset,
                    day=date.fromisoformat(day),
                    detail=f"has {sorted(segments)} but not {sorted(missing)}",
                )
            )
    return out


def check_calendar_gaps(
    path: Path, dataset: str = "nse", *, max_gap_days: int = 5
) -> list[Finding]:
    """Runs of consecutive calendar days with no data at all.

    Weekends and single holidays are normal, so only gaps longer than
    `max_gap_days` are reported. A long gap is either a market closure worth
    knowing about or a backfill that silently stopped.
    """
    days = sorted(
        {date.fromisoformat(str(row["trade_date"])) for row in _rows(path) if row.get("trade_date")}
    )
    out: list[Finding] = []
    for earlier, later in pairwise(days):
        gap = (later - earlier).days
        if gap > max_gap_days:
            out.append(
                Finding(
                    check="calendar-gap",
                    severity=Severity.WARN,
                    dataset=dataset,
                    day=earlier,
                    detail=f"{gap} days with no data, until {later.isoformat()}",
                )
            )
    return out


def check_staleness(path: Path, dataset: str, *, now: datetime | None = None) -> list[Finding]:
    """The dataset stopped receiving data.

    Compares against the most recent `knowledge_time`, i.e. when we last
    fetched anything, not the newest trade date — a feed can keep returning
    stale content, and the question here is whether the pipeline is running.
    """
    fetched = [
        datetime.fromisoformat(str(row["knowledge_time"]))
        for row in _rows(path)
        if row.get("knowledge_time")
    ]
    if not fetched:
        return []
    latest = max(fetched)
    reference = now or datetime.now(latest.tzinfo)
    age = reference - latest
    if age <= STALE_AFTER:
        return []
    return [
        Finding(
            check="staleness",
            severity=Severity.WARN,
            dataset=dataset,
            detail=f"nothing fetched for {age.days} days (last {latest.date().isoformat()})",
        )
    ]


def run_manifest_checks(root: Path = LANDING_ROOT) -> list[Finding]:
    """Every free check across every dataset tree found under `root`."""
    out: list[Finding] = []
    trees = sorted(d for d in root.iterdir() if d.is_dir()) if root.exists() else []
    if not trees:
        return [
            Finding(
                check="manifest-present",
                severity=Severity.ERROR,
                detail=f"no dataset trees under {root}",
            )
        ]

    for tree in trees:
        dataset = tree.name
        manifest = tree / "manifest.jsonl"
        if present := check_manifest_present(manifest, dataset):
            out.extend(present)
            continue
        out.extend(check_duplicate_keys(manifest, dataset))
        out.extend(check_zero_row_files(manifest, dataset))
        out.extend(check_staleness(manifest, dataset))
        if dataset == "nse":
            out.extend(check_segment_coverage(manifest, dataset))
            out.extend(check_calendar_gaps(manifest, dataset))
    return out
