"""`make build-factors` — build both adjustment-factor series and persist them.

Reads the landed corporate-actions files, fetches only the close prices the
engine actually needs, and writes two JSONL files: one price-adjusted series
(share-count changes) and one total-return series (plus dividends).

The output is sorted and written deterministically, so two builds of the same
inputs are byte-identical — the same property `eulerlab.master.store` holds,
and the reason a factor file can be diffed in review rather than trusted.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from eulerlab.bitemporal.store import BitemporalStore
from eulerlab.corp_actions.adjust import (
    build_price_factor_store,
    build_total_return_factor_store,
)
from eulerlab.corp_actions.parse import CorporateAction, Kind, parse_rows
from eulerlab.corp_actions.prices import (
    CACHE_PATH as CLOSE_CACHE,
)
from eulerlab.corp_actions.prices import (
    TransactionCapExceeded,
    build_close_index,
    cash_entries,
    close_price_lookup,
    instrument_key,
)
from eulerlab.ingest import landing_reader
from eulerlab.ingest.landing import Landing
from eulerlab.paths import data_path

MANIFEST = data_path("landing/nse/manifest.jsonl")
ACTIONS_GLOB = "corp_actions/*/*/*_json.json"
PRICE_FACTORS = data_path("derived/price_factors.jsonl")
TOTAL_RETURN_FACTORS = data_path("derived/total_return_factors.jsonl")


def cached_dates(path: Path) -> set[str]:
    """Trade dates already in the close-price cache, so the builder can say
    how much of the run will actually hit the network."""
    if not path.exists():
        return set()
    return {
        json.loads(line)["d"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def _action_files(landing_root: Path) -> list[str]:
    """Every corporate-action file landed, on disk or pruned to B2 (ADR-187).

    The manifest lists files the prune removed; globbing the disk alone found
    none once they were pruned, and the factors were rebuilt empty."""
    found = {p.relative_to(landing_root).as_posix() for p in landing_root.glob(ACTIONS_GLOB)}
    if (landing_root / "manifest.jsonl").exists():
        found |= {
            e.path for e in Landing(landing_root).entries().values() if e.segment == "corp_actions"
        }
    return sorted(found)


def _read_landed(landing_root: Path, relative: str) -> bytes:
    local = landing_root / relative
    if local.exists():
        return local.read_bytes()
    # Raises when the file is neither here nor in the bucket: a missing year
    # must stop the build, never shrink it.
    return landing_reader.read(f"{landing_root.name}/{relative}", cache=False)


def load_actions(landing_root: Path) -> tuple[list[CorporateAction], int]:
    """Every landed corporate action, oldest ex-date first."""
    rows: list[dict[str, object]] = []
    for relative in _action_files(landing_root):
        rows.extend(json.loads(_read_landed(landing_root, relative).decode("utf-8")))
    actions, skipped = parse_rows(rows)
    return sorted(actions, key=lambda a: (a.ex_date, a.isin)), skipped


def no_isin_actions(actions: Sequence[CorporateAction], master_path: Path) -> list[CorporateAction]:
    """Splits and bonuses of companies that never traded with an ISIN (ADR-187).

    The action's symbol is resolved on its ex-date through the no-ISIN master,
    which bounds every ticker by the days it was observed trading, so a reused
    symbol resolves to whoever held it then. A copy of the action is keyed to
    that instrument's own id. Dividends and rights need a price lookup by ISIN
    and are not copied."""
    from dataclasses import replace

    from eulerlab.master import store

    registry, _ = store.load(master_path)
    out: list[CorporateAction] = []
    for action in actions:
        if not any(c.kind in (Kind.BONUS, Kind.SPLIT) for c in action.components):
            continue
        instrument = registry.resolve(action.symbol, action.ex_date)
        if instrument is not None:
            out.append(replace(action, isin=str(instrument.instrument_id)))
    return out


def needed_price_keys(actions: Sequence[CorporateAction]) -> set[tuple[str, str]]:
    """(instrument_key, ex_date) for every action that needs a market price.

    Only dividends and rights do. Bonuses and splits are pure ratio
    arithmetic, so asking for their prices would download files for nothing.

    Keyed by `InstrumentId`, not the raw ISIN — the feed and the bhavcopy
    disagree about trailing ISIN serials for the same company (see
    `prices.py`), and using the raw string here would silently under-fetch.
    """
    keys: set[tuple[str, str]] = set()
    for action in actions:
        if not any(c.kind in (Kind.DIVIDEND, Kind.RIGHTS) for c in action.components):
            continue
        key = instrument_key(action.isin)
        if key:
            keys.add((key, action.ex_date.isoformat()))
    return keys


def write_factors(store: BitemporalStore, path: Path) -> int:
    """Persist a factor store as sorted JSONL. Returns the row count.

    Reads through `query` with an `as_of` far in the future rather than
    touching the store's internals: the firewall applies to persistence too,
    and reaching past it here would be the obvious place for a leak to enter.
    """
    far_future = datetime(2999, 1, 1, tzinfo=ZoneInfo("Asia/Kolkata"))
    records = sorted(
        store.query(as_of=far_future),
        key=lambda r: (r.key, r.event_time),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(
                json.dumps(
                    {
                        "isin": record.key,
                        "event_time": record.event_time.isoformat(),
                        "knowledge_time": record.knowledge_time.isoformat(),
                        "factor": record.value,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
    return len(records)


@dataclass
class BuildReport:
    actions: int
    skipped_rows: int
    price_keys_needed: int
    files_fetched: int
    prices_found: int
    price_factor_rows: int
    total_return_rows: int

    def summary(self) -> str:
        coverage = (
            100.0 * self.prices_found / self.price_keys_needed if self.price_keys_needed else 0.0
        )
        return (
            f"actions            : {self.actions:,} ({self.skipped_rows:,} rows skipped)\n"
            f"price lookups need : {self.price_keys_needed:,}\n"
            f"bhavcopy fetched   : {self.files_fetched:,} files\n"
            f"prices found       : {self.prices_found:,} ({coverage:.1f}% coverage)\n"
            f"price factors      : {self.price_factor_rows:,} rows\n"
            f"total-return       : {self.total_return_rows:,} rows"
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build-factors")
    parser.add_argument("--landing", type=Path, default=data_path("landing/nse"))
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument(
        "--limit-files",
        type=int,
        default=None,
        help="fetch at most N bhavcopy files - for a quick smoke run",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write the two factor files and the close cache here, not data/derived",
    )
    parser.add_argument(
        "--no-isin-master",
        type=Path,
        default=None,
        help="instruments without an ISIN (legacy-isin); their splits and bonuses are keyed to them",
    )
    args = parser.parse_args(argv)
    price_path, tr_path, cache = PRICE_FACTORS, TOTAL_RETURN_FACTORS, CLOSE_CACHE
    if args.out is not None:
        args.out.mkdir(parents=True, exist_ok=True)
        price_path = args.out / PRICE_FACTORS.name
        tr_path = args.out / TOTAL_RETURN_FACTORS.name
        cache = args.out / CLOSE_CACHE.name

    actions, skipped = load_actions(args.landing)
    print(f"loaded {len(actions):,} corporate actions ({skipped:,} rows skipped)")
    if args.no_isin_master is not None:
        extra = no_isin_actions(actions, args.no_isin_master)
        print(f"{len(extra):,} splits and bonuses keyed to instruments without an ISIN")
        actions = sorted([*actions, *extra], key=lambda a: (a.ex_date, a.isin))
    if not actions:
        # On 2026-11-14 a pruned landing loaded nothing and this wrote both
        # factor files empty, i.e. no adjustment anywhere (HISTORY).
        print("no corporate actions found: the factor files are left as they are")
        return 1

    needed = needed_price_keys(actions)
    ex_dates = {d for _, d in needed}
    print(f"{len(needed):,} price lookups needed, across {len(ex_dates):,} ex-dates")

    entries = [e for e in cash_entries(args.manifest) if e.trade_date in ex_dates]
    if args.limit_files:
        entries = entries[: args.limit_files]

    already_cached = cached_dates(cache)
    to_fetch = sum(1 for e in entries if e.trade_date not in already_cached)
    print(
        f"{len(entries):,} cash bhavcopy files needed; "
        f"{len(entries) - to_fetch:,} already cached, {to_fetch:,} to download"
    )
    if to_fetch:
        print(
            "  (B2 free tier allows 2,500 downloads/day - see docs/RUNBOOKS/b2-transaction-cap.md)"
        )

    def progress(done: int, total: int) -> None:
        if done % 200 == 0 or done == total:
            print(f"  {done:,}/{total:,}")

    try:
        index = build_close_index(entries, needed=needed, progress=progress, cache_path=cache)
    except TransactionCapExceeded as exc:
        # Expected and self-healing, so it reports rather than raising: a
        # traceback would imply a defect and bury the fact that the partial
        # download was saved.
        print(f"\n{exc}")
        return 2
    lookup = close_price_lookup(index)

    price_store = build_price_factor_store(actions, lookup)
    tr_store = build_total_return_factor_store(actions, lookup)

    n_price = write_factors(price_store, price_path)
    n_tr = write_factors(tr_store, tr_path)

    report = BuildReport(
        actions=len(actions),
        skipped_rows=skipped,
        price_keys_needed=len(needed),
        files_fetched=len(entries),
        prices_found=len(index),
        price_factor_rows=n_price,
        total_return_rows=n_tr,
    )
    print()
    print(report.summary())
    print(f"\nwritten: {price_path}")
    print(f"written: {tr_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
