"""Results, mirrored to the same bucket the market data lives in.

The local JSONL is the source of truth and the cloud is a second copy. That
direction matters: a backtest records locally and returns, and the upload
happens afterwards. If the network is down the result still exists, and the
interface says the mirror is behind rather than pretending the run failed.

### Merging two append-only logs

Results are append-only, so two machines running the same workspace both append
and the two files diverge without either being wrong. The merge is a union
keyed by `(configuration, at)` — not by whole-line equality, because the same
run serialised on two machines can differ in a float repr and would then be
counted twice, inflating the `runs` denominator that the whole result store
exists to keep honest.

Ordering is chronological by `at`. `distinct()` already takes the latest row per
configuration, so ordering is not load-bearing; it just keeps the file readable.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from eulerlab.env import load_env
from eulerlab.ingest.cloud import (
    APP_KEY_ENV,
    KEY_ID_ENV,
    MissingCredentials,
    ReadableStore,
    S3ObjectStore,
    load_storage_config,
)
from eulerlab.ingest.landing import sha256_of
from eulerlab.workspace import Workspace

STORAGE_CONFIG = Path("config/storage.yaml")
RESULTS_PREFIX = "results/"


@dataclass
class Mirror:
    """What one mirror pass actually moved."""

    pushed: int = 0
    pulled: int = 0
    merged_rows: int = 0
    failed: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


def configured() -> tuple[bool, str]:
    """Whether a mirror could run at all, and why not when it could not.

    Presence only — the credential values are never returned, so this can be
    surfaced through the HTTP API without putting a secret in a response body.
    """
    # Load .env first, exactly as S3ObjectStore does in its constructor.
    # Reading os.environ without it reported "not configured" on a machine
    # whose credentials were sitting in .env the whole time — the check
    # disagreed with the thing it was supposed to be checking.
    load_env()
    if not STORAGE_CONFIG.exists():
        return False, f"{STORAGE_CONFIG} is missing"
    missing = [name for name in (KEY_ID_ENV, APP_KEY_ENV) if not os.environ.get(name)]
    if missing:
        return False, f"not set: {', '.join(missing)}"
    return True, "credentials present"


def open_store() -> ReadableStore:
    """Build the object store, or raise MissingCredentials."""
    store: ReadableStore = S3ObjectStore(load_storage_config(STORAGE_CONFIG))
    return store


def _key(workspace: Workspace, name: str) -> str:
    return f"{RESULTS_PREFIX}{workspace.id}/{name}"


def _row_identity(line: str) -> tuple[str, str] | None:
    """What makes two recorded runs the same run."""
    try:
        row = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(row, dict):
        return None
    return str(row.get("configuration", "")), str(row.get("at", ""))


def merge_lines(local: list[str], remote: list[str]) -> list[str]:
    """Union of two append-only logs, newest last.

    Torn lines are dropped rather than carried across: a half-written row is
    not a result, and copying one to the other machine would spread the damage.
    """
    seen: dict[tuple[str, str], str] = {}
    for line in [*remote, *local]:
        stripped = line.strip()
        if not stripped:
            continue
        identity = _row_identity(stripped)
        if identity is None:
            continue
        # Local wins a tie: it is the copy this machine just wrote and the one
        # the operator can actually inspect.
        seen[identity] = stripped
    return [line for _, line in sorted(seen.items(), key=lambda item: item[0][1])]


def remote_hashes(store: ReadableStore, prefix: str) -> dict[str, str] | None:
    """MD5 of each object under `prefix`, or None when the store cannot say.

    None means "download and compare": a store that cannot give content hashes
    must not be trusted to say two files are the same.
    """
    lister = getattr(store, "list_md5", None)
    if lister is None:
        return None
    found: dict[str, str] = lister(prefix)
    return found


def _same(path: Path, key: str, hashes: dict[str, str] | None) -> bool:
    """Whether the local file is byte-for-byte the bucket's object.

    By content hash, not by size. Size was the first test and it has a hole:
    two machines each appending a different row of the same length leave two
    different files of equal size, and neither would ever be fetched or sent.
    """
    if hashes is None or key not in hashes or not path.exists():
        return False
    return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest() == hashes[key]


def pull(
    workspace: Workspace,
    store: ReadableStore,
    *,
    hashes: dict[str, str] | None = None,
    full: bool = False,
) -> Mirror:
    """Bring down anything in the bucket this machine does not have, and merge.

    A file whose content hash equals the bucket's is not downloaded. Without
    that every mirror downloaded every result file to find nothing new: 70
    downloads and 40 s after each batch (measured 2026-10-12).

    `hashes` is `remote_hashes(...)` when the caller already has it. `full`
    downloads and merges everything regardless (`make results-pull`).
    """
    outcome = Mirror()
    workspace.results.mkdir(parents=True, exist_ok=True)
    prefix = f"{RESULTS_PREFIX}{workspace.id}/"
    try:
        if hashes is None:
            hashes = remote_hashes(store, prefix)
        remote_keys = list(hashes) if hashes is not None else list(store.list_sizes(prefix))
    except Exception as exc:
        outcome.failed.append(f"list: {exc}")
        return outcome

    for key in sorted(remote_keys):
        name = key[len(prefix) :]
        if not name.endswith(".jsonl"):
            continue
        path = workspace.results / name
        if not full and _same(path, key, hashes):
            continue
        try:
            remote_text = store.get(key).decode("utf-8")
        except Exception as exc:
            outcome.failed.append(f"{name}: {exc}")
            continue
        local_text = path.read_text(encoding="utf-8") if path.exists() else ""
        merged = merge_lines(local_text.splitlines(), remote_text.splitlines())
        before = len([line for line in local_text.splitlines() if line.strip()])
        if len(merged) != before or not path.exists():
            path.write_text("\n".join(merged) + "\n", encoding="utf-8")
            outcome.pulled += 1
            outcome.merged_rows += len(merged) - before
    return outcome


def push(
    workspace: Workspace, store: ReadableStore, *, hashes: dict[str, str] | None = None
) -> Mirror:
    """Upload every result file whose bytes differ from the bucket's copy.

    Judged by content hash when the store gives one, and by size when it
    cannot (the first test, kept for stores without hashes).
    """
    outcome = Mirror()
    if not workspace.results.exists():
        return outcome
    prefix = f"{RESULTS_PREFIX}{workspace.id}/"
    sizes: dict[str, int] = {}
    try:
        if hashes is None:
            hashes = remote_hashes(store, prefix)
        if hashes is None:
            sizes = store.list_sizes(prefix)
    except Exception as exc:
        outcome.failed.append(f"list: {exc}")
        return outcome

    for path in sorted(workspace.results.glob("*.jsonl")):
        key = _key(workspace, path.name)
        payload = path.read_bytes()
        if hashes is not None:
            if hashes.get(key) == hashlib.md5(payload, usedforsecurity=False).hexdigest():
                continue
        elif sizes.get(key) == len(payload):
            continue
        try:
            store.put(key, payload, sha256_of(payload))
        except Exception as exc:
            # One bad object must not stop the rest of the workspace.
            outcome.failed.append(f"{path.name}: {exc}")
            continue
        outcome.pushed += 1
    return outcome


def mirror(
    workspace: Workspace, store: ReadableStore | None = None, *, full: bool = False
) -> Mirror:
    """Pull then push, so both copies end up holding the union.

    Pull first on purpose: pushing first would overwrite the bucket with a file
    that is missing whatever another machine appended, and the next pull would
    have nothing left to restore.

    The bucket is listed once and both halves use the listing. The push is
    judged against hashes from before the pull, which is right: a file the
    pull just merged no longer matches the bucket's, so it is pushed.
    """
    if store is None:
        store = open_store()
    try:
        hashes = remote_hashes(store, f"{RESULTS_PREFIX}{workspace.id}/")
    except Exception as exc:
        return Mirror(failed=[f"list: {exc}"])
    down = pull(workspace, store, hashes=hashes, full=full)
    up = push(workspace, store, hashes=hashes)
    return Mirror(
        pushed=up.pushed,
        pulled=down.pulled,
        merged_rows=down.merged_rows,
        failed=[*down.failed, *up.failed],
    )


def mirror_quietly(workspace: Workspace) -> Mirror:
    """Mirror, converting a missing-credentials setup into a reported failure.

    Used on the batch path, where the run has already succeeded and been
    recorded locally. A cloud outage must not turn a completed backtest into a
    failed one — but it must not be silent either, so the reason travels back
    in the job result.
    """
    ready, reason = configured()
    if not ready:
        return Mirror(failed=[f"cloud not configured: {reason}"])
    try:
        return mirror(workspace)
    except MissingCredentials as exc:
        return Mirror(failed=[str(exc)])
    except Exception as exc:
        return Mirror(failed=[f"{type(exc).__name__}: {exc}"])


def dedupe(workspace: Workspace, *, apply: bool, store: ReadableStore | None = None) -> int:
    """`make results-dedupe`: drop repeated rows here and in the bucket.

    In three steps, in this order. Pull everything first, so no row that only
    the bucket holds is lost. Drop the repeats locally. Then push **without
    pulling again**: a mirror would merge the bucket's repeats straight back,
    because it treats rows with different times as different rows.
    """
    from eulerlab import results as result_store

    if store is None and configured()[0]:
        store = open_store()
    if store is not None and apply:
        down = pull(workspace, store, full=True)
        if down.failed:
            print(f"pull failed, nothing changed: {down.failed[:3]}")
            return 1
    found = result_store.drop_duplicates(workspace, dry_run=not apply)
    dropped = sum(drop for _, drop in found.values())
    for name, (kept, drop) in sorted(found.items()):
        print(f"  {name}: keep {kept}, drop {drop}")
    print(
        f"{'dropped' if apply else 'would drop'} {dropped} repeated row(s) in {len(found)} file(s)"
    )
    if not apply:
        print("nothing changed. Run `make results-dedupe APPLY=1` to do it.")
        return 0
    if store is not None:
        up = push(workspace, store)
        print(f"pushed {up.pushed} file(s) to the bucket; failed {len(up.failed)}")
        return 1 if up.failed else 0
    return 0


def main(argv: list[str] | None = None) -> int:
    """`make results-pull` and `make results-dedupe`."""
    import argparse

    from eulerlab import workspace as workspace_mod

    parser = argparse.ArgumentParser(prog="cloud-results")
    parser.add_argument("--dedupe", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.dedupe:
        return dedupe(workspace_mod.resolve(None), apply=args.apply)

    ok, reason = configured()
    if not ok:
        print(reason)
        return 1
    outcome = mirror(workspace_mod.resolve(None), full=True)
    print(
        f"pulled {outcome.pulled} file(s), {outcome.merged_rows} new row(s); "
        f"pushed {outcome.pushed}; failed {len(outcome.failed)}"
    )
    for failure in outcome.failed:
        print(f"  {failure}")
    return 1 if outcome.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
