"""Clear local files the upload refused: merge each into the bucket's copy, then delete it.

`sync_directory` never replaces a bucket object with a smaller local file
(HISTORY #52), and `prune_tree` deletes a local file only when the bucket holds
it at the same size. A file that differs from the bucket is therefore kept
forever and refused every night. On 2026-11-03 that was 12,107 files: US
actions and bars re-fetched with new knowledge times (HISTORY #68), crypto
months re-landed, and two news months that held only part of the month while
the bucket held all of it (HISTORY #70).

For a `.jsonl.gz` file, one JSON record a line, the two copies are merged:

- A row is the same row when every field but `knowledge_time` and
  `receipt_time` is equal. It is kept once, with the earliest `knowledge_time`
  of the two (the first moment we held it; CLAUDE.md: every record carries its
  knowledge time, and a later re-fetch must not move it later).
- The bucket's rows keep their order; rows only the local copy has follow.
- Nothing is dropped: the merged file holds every distinct row of both.

If the merge adds nothing to the bucket's copy, the local file is a duplicate
and is deleted. Otherwise the merged file is uploaded, a fresh listing must
show it at its new size, and only then is the local file deleted. A file that
is not `.jsonl.gz`, or that does not parse, is left alone and reported.

The bucket keeps the replaced object as an older version (A-098), so the
merge can be undone from B2.
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from eulerlab.ingest.cloud import MissingCredentials, ReadableStore, load_storage_config
from eulerlab.ingest.landing import sha256_of

TIME_FIELDS = ("knowledge_time", "receipt_time")
"""Fields that say when we held a row, not what the row is."""
TREES = ("crypto", "fx", "news", "us", "mf", "calendar", "marketdata", "delta")
"""Landing trees of `.jsonl.gz` files that `make daily` uploads and deletes."""
LANDING = Path("data/landing")
REPORT = Path("data/derived/merge_back.json")
WORKERS = 8
DEFAULT_LIMIT = 4000
"""Files merged a run at most, so one run stays under about half an hour; the
rest wait for the next run (the data agent runs every two hours)."""


class NotRows(ValueError):
    """The file is not one JSON object a line."""


def read_rows(payload: bytes) -> list[tuple[str, dict[str, Any]]]:
    """(line, row) for each line of a gzipped JSON-lines file."""
    try:
        text = gzip.decompress(payload).decode("utf-8")
    except (OSError, EOFError, UnicodeDecodeError) as exc:
        raise NotRows(f"not gzip text: {type(exc).__name__}") from exc
    out: list[tuple[str, dict[str, Any]]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise NotRows(f"a line is not JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise NotRows("a line is not a JSON object")
        out.append((line, row))
    return out


def identity(row: dict[str, Any]) -> str:
    """The row without the fields that only say when we held it."""
    return json.dumps(
        {k: v for k, v in row.items() if k not in TIME_FIELDS}, sort_keys=True, default=str
    )


@dataclass(frozen=True)
class Merged:
    lines: list[str]
    added: int
    """Rows only the local copy had."""
    earlier: int
    """Rows both had, where the local copy knew them earlier."""
    repeats: int
    """Rows the bucket's copy itself held more than once, now held once."""

    @property
    def changes_bucket(self) -> bool:
        return bool(self.added or self.earlier or self.repeats)


def merge(
    bucket: Iterable[tuple[str, dict[str, Any]]], local: Iterable[tuple[str, dict[str, Any]]]
) -> Merged:
    """Every distinct row of both copies, once, at its earliest knowledge time."""
    kept: dict[str, tuple[str, dict[str, Any]]] = {}
    order: list[str] = []
    repeats = 0
    for line, row in bucket:
        key = identity(row)
        if key in kept:
            repeats += 1
            if _earlier(row, kept[key][1]):
                kept[key] = (line, row)
            continue
        kept[key] = (line, row)
        order.append(key)
    added = earlier = 0
    for line, row in local:
        key = identity(row)
        if key not in kept:
            kept[key] = (line, row)
            order.append(key)
            added += 1
        elif _earlier(row, kept[key][1]):
            kept[key] = (line, row)
            earlier += 1
    return Merged([kept[k][0] for k in order], added, earlier, repeats)


def _earlier(a: dict[str, Any], b: dict[str, Any]) -> bool:
    ka, kb = str(a.get("knowledge_time") or ""), str(b.get("knowledge_time") or "")
    return bool(ka) and bool(kb) and _instant(ka) < _instant(kb)


def _instant(text: str) -> datetime:
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return datetime.max.replace(tzinfo=UTC)
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def pack(lines: Sequence[str]) -> bytes:
    """Gzip the lines with a fixed timestamp: the same rows give the same bytes."""
    return gzip.compress(("\n".join(lines) + "\n").encode("utf-8"), mtime=0)


@dataclass
class TreeReport:
    tree: str
    checked: int = 0
    duplicates_deleted: int = 0
    merged_uploaded: int = 0
    rows_added: int = 0
    rows_earlier: int = 0
    rows_repeated: int = 0
    unresolved: list[str] = field(default_factory=list)
    left_for_next_run: int = 0


def differing(root: Path, tree: str, remote: dict[str, int], prefix: str) -> list[tuple[Path, str]]:
    """Local files of the tree whose bucket copy exists at another size."""
    out: list[tuple[Path, str]] = []
    base = root / tree
    for path in sorted(p for p in base.rglob("*") if p.is_file()):
        key = f"{prefix}{tree}/{path.relative_to(base).as_posix()}"
        size = remote.get(key)
        if size is not None and size != path.stat().st_size:
            out.append((path, key))
    return out


def merge_tree(
    root: Path,
    tree: str,
    store: ReadableStore,
    *,
    prefix: str,
    limit: int = DEFAULT_LIMIT,
    dry_run: bool = False,
    workers: int = WORKERS,
) -> TreeReport:
    """Merge every differing local file of one tree into the bucket, then delete it."""
    report = TreeReport(tree)
    if not (root / tree).is_dir():
        return report
    jobs = differing(root, tree, store.list_sizes(f"{prefix}{tree}/"), prefix)
    report.left_for_next_run = max(0, len(jobs) - limit)
    jobs = jobs[:limit]
    report.checked = len(jobs)
    lock = Lock()
    sent: dict[str, tuple[Path, int]] = {}

    def one(job: tuple[Path, str]) -> None:
        path, key = job
        name = path.relative_to(root).as_posix()
        if not path.name.endswith(".jsonl.gz"):
            with lock:
                report.unresolved.append(f"{name}: differs from the bucket and is not JSON lines")
            return
        try:
            local = read_rows(path.read_bytes())
            bucket = read_rows(store.get(key))
        except NotRows as exc:
            with lock:
                report.unresolved.append(f"{name}: {exc}")
            return
        except Exception as exc:  # one unreadable object must not stop the tree
            with lock:
                report.unresolved.append(
                    f"{name}: could not read the bucket's copy ({type(exc).__name__})"
                )
            return
        merged = merge(bucket, local)
        with lock:
            report.rows_added += merged.added
            report.rows_earlier += merged.earlier
            report.rows_repeated += merged.repeats
        if not merged.changes_bucket:
            if not dry_run:
                path.unlink()
            with lock:
                report.duplicates_deleted += 1
            return
        if dry_run:
            with lock:
                report.merged_uploaded += 1
            return
        payload = pack(merged.lines)
        try:
            store.put(key, payload, sha256_of(payload))
        except Exception as exc:
            with lock:
                report.unresolved.append(f"{name}: upload failed ({type(exc).__name__})")
            return
        with lock:
            sent[key] = (path, len(payload))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, jobs))

    if sent:
        # Delete only what a listing taken now shows at the merged size.
        listed = store.list_sizes(f"{prefix}{tree}/")
        for key, (path, size) in sorted(sent.items()):
            if listed.get(key) == size:
                path.unlink()
                report.merged_uploaded += 1
            else:
                report.unresolved.append(
                    f"{path.relative_to(root).as_posix()}: uploaded, but the bucket does not show it at {size} bytes yet"
                )
    report.unresolved.sort()
    return report


def run(
    store: ReadableStore,
    *,
    prefix: str,
    trees: Sequence[str] = TREES,
    root: Path = LANDING,
    limit: int = DEFAULT_LIMIT,
    dry_run: bool = False,
    log: Callable[[str], Any] = print,
) -> list[TreeReport]:
    reports: list[TreeReport] = []
    left = limit
    for tree in trees:
        report = merge_tree(root, tree, store, prefix=prefix, limit=max(0, left), dry_run=dry_run)
        left -= report.checked
        reports.append(report)
        if report.checked or report.left_for_next_run:
            log(
                f"{tree}: {report.checked} differed from B2 — {report.duplicates_deleted} were "
                f"duplicates (deleted), {report.merged_uploaded} merged and uploaded "
                f"(+{report.rows_added} rows, {report.rows_earlier} earlier knowledge times, "
                f"{report.rows_repeated} repeats removed), {len(report.unresolved)} unresolved, "
                f"{report.left_for_next_run} left for the next run"
            )
            for line in report.unresolved[:10]:
                log(f"    {line}")
    return reports


def save(
    reports: Sequence[TreeReport], *, path: Path = REPORT, now: datetime | None = None
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "at": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
        "trees": [asdict(r) for r in reports],
    }
    path.write_text(json.dumps(body, indent=1) + "\n", encoding="utf-8")


def saved(path: Path = REPORT) -> dict[str, Any]:
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return body if isinstance(body, dict) else {}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="data-merge-back", description=__doc__)
    parser.add_argument("--trees", default=",".join(TREES))
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--config", type=Path, default=Path("config/storage.yaml"))
    args = parser.parse_args(argv)
    from eulerlab.ingest.cloud import S3ObjectStore

    config = load_storage_config(args.config)
    try:
        store = S3ObjectStore(config)
    except MissingCredentials as exc:
        print(f"merge-back: {exc}")
        return 2
    trees = [t.strip() for t in args.trees.split(",") if t.strip()]
    reports = run(store, prefix=config.prefix, trees=trees, limit=args.limit, dry_run=args.dry_run)
    if not args.dry_run:
        save(reports)
    unresolved = sum(len(r.unresolved) for r in reports)
    left = sum(r.left_for_next_run for r in reports)
    print(
        f"merge-back: {sum(r.checked for r in reports)} checked, {unresolved} unresolved, "
        f"{left} left for the next run{' (dry run: nothing changed)' if args.dry_run else ''}"
    )
    return 1 if unresolved else 0


if __name__ == "__main__":
    raise SystemExit(main())
