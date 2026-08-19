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
    build_close_index,
    cash_entries,
    close_price_lookup,
    instrument_key,
)

MANIFEST = Path("data/landing/nse/manifest.jsonl")
ACTIONS_GLOB = "corp_actions/*/*/*_json.json"
PRICE_FACTORS = Path("data/derived/price_factors.jsonl")
TOTAL_RETURN_FACTORS = Path("data/derived/total_return_factors.jsonl")


def _cached_dates(path: Path) -> set[str]:
    """Trade dates already in the close-price cache, so the builder can say
    how much of the run will actually hit the network."""
    if not path.exists():
        return set()
    return {
        json.loads(line)["d"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def load_actions(landing_root: Path) -> tuple[list[CorporateAction], int]:
    """Every landed corporate action, oldest ex-date first."""
    rows: list[dict[str, object]] = []
    for path in sorted(landing_root.glob(ACTIONS_GLOB)):
        rows.extend(json.loads(path.read_text(encoding="utf-8")))
    actions, skipped = parse_rows(rows)
    return sorted(actions, key=lambda a: (a.ex_date, a.isin)), skipped


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
    parser.add_argument("--landing", type=Path, default=Path("data/landing/nse"))
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument(
        "--limit-files",
        type=int,
        default=None,
        help="fetch at most N bhavcopy files - for a quick smoke run",
    )
    args = parser.parse_args(argv)

    actions, skipped = load_actions(args.landing)
    print(f"loaded {len(actions):,} corporate actions ({skipped:,} rows skipped)")

    needed = needed_price_keys(actions)
    ex_dates = {d for _, d in needed}
    print(f"{len(needed):,} price lookups needed, across {len(ex_dates):,} ex-dates")

    entries = [e for e in cash_entries(args.manifest) if e.trade_date in ex_dates]
    if args.limit_files:
        entries = entries[: args.limit_files]

    cached_dates = _cached_dates(CLOSE_CACHE)
    to_fetch = sum(1 for e in entries if e.trade_date not in cached_dates)
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

    index = build_close_index(entries, needed=needed, progress=progress)
    lookup = close_price_lookup(index)

    price_store = build_price_factor_store(actions, lookup)
    tr_store = build_total_return_factor_store(actions, lookup)

    n_price = write_factors(price_store, PRICE_FACTORS)
    n_tr = write_factors(tr_store, TOTAL_RETURN_FACTORS)

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
    print(f"\nwritten: {PRICE_FACTORS}")
    print(f"written: {TOTAL_RETURN_FACTORS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
