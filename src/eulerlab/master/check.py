"""`make check-master` — the security master's acceptance command.

Answers the question Sprint 3 exists to answer: *can I ask what an instrument
was on a past date and get the past answer?* Each check either passes or names
what is wrong; none of them can pass vacuously, because a master built from
zero files would fail the coverage check first.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from eulerlab.master.succession import KNOWN_SUCCESSIONS, SuccessionKind
from eulerlab.master.symbology import SymbolMap, load

RENAMES_PATH = Path("config/symbol_renames.json")
UNRESOLVED_PATH = Path("data/landing/kite_minute/unresolved.jsonl")
MINUTE_MANIFEST = Path("data/landing/kite_minute/manifest.jsonl")


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def check_symbol_map_exists(symbol_map: SymbolMap | None) -> Check:
    if symbol_map is None:
        return Check("symbol-map", False, f"{RENAMES_PATH} missing — run the builder")
    if not symbol_map.renames:
        return Check("symbol-map", False, "no renames recorded; the map is empty")
    return Check("symbol-map", True, f"{len(symbol_map.renames)} renames")


def check_every_stuck_symbol_is_explained(symbol_map: SymbolMap | None) -> Check:
    """The headline: no symbol may be simply unaccounted for.

    A symbol is explained if any of these hold:

    * it has data now — the log entry was transient or was a bug on our side,
      which is what happened to the four BE-series symbols wrongly reported as
      delisted;
    * it renamed, and the new name is recorded;
    * a succession records what happened to it.

    Anything else is a gap in knowledge, and this refuses to let it hide.
    `unresolved.jsonl` is append-only, so a stale entry there is not evidence
    of a current problem — the manifest is.
    """
    if not UNRESOLVED_PATH.exists():
        return Check("all-explained", True, "no unresolved log")
    stuck = sorted(
        {
            json.loads(line)["symbol"]
            for line in UNRESOLVED_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip() and "not in Kite" in line
        }
    )
    succeeded = {s.predecessor for s in KNOWN_SUCCESSIONS}
    have_data: set[str] = set()
    if MINUTE_MANIFEST.exists():
        have_data = {
            json.loads(line)["symbol"]
            for line in MINUTE_MANIFEST.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    unexplained = [
        s
        for s in stuck
        if s not in succeeded
        and s not in have_data
        and (symbol_map is None or symbol_map.current_name(s) is None)
    ]
    if unexplained:
        return Check("all-explained", False, f"{len(unexplained)} unexplained: {unexplained}")
    return Check("all-explained", True, f"all {len(stuck)} accounted for")


def check_successions_are_sourced() -> Check:
    """A corporate-action fact without a citation is a guess."""
    missing = [s.predecessor for s in KNOWN_SUCCESSIONS if len(s.source) < 20]
    if missing:
        return Check("sourced", False, f"no citation: {missing}")
    return Check("sourced", True, f"{len(KNOWN_SUCCESSIONS)} successions cited")


def check_ratios_present_where_required() -> Check:
    """A merger, demerger or cancellation without a ratio cannot carry a
    position — unless it is explicitly flagged as terms-pending."""
    needs = (SuccessionKind.MERGER, SuccessionKind.DEMERGER, SuccessionKind.CANCELLATION)
    bad = [
        s.predecessor
        for s in KNOWN_SUCCESSIONS
        if s.kind in needs and s.ratio is None and not s.terms_pending
    ]
    if bad:
        return Check("ratios", False, f"missing ratio and not flagged pending: {bad}")
    pending = [s.predecessor for s in KNOWN_SUCCESSIONS if s.terms_pending]
    detail = "all present" if not pending else f"all present ({len(pending)} terms-pending)"
    return Check("ratios", True, detail)


def check_point_in_time_query() -> Check:
    """The property the whole sprint is for: a past date returns the past answer.

    Uses ZOMATO/ETERNAL, whose rename is independently verifiable — they share
    ISIN INE758T01015, and the registry found the change from the data alone.
    """
    from eulerlab.master.identity import InstrumentId
    from eulerlab.master.registry import Registry

    registry = Registry()
    zomato = InstrumentId.from_isin("INE758T01015")
    for month in range(1, 13):
        registry.observe(
            date(2023, month, 1), instrument_id=zomato, ticker="ZOMATO", isin="INE758T01015"
        )
    for month in range(1, 9):
        registry.observe(
            date(2026, month, 1), instrument_id=zomato, ticker="ETERNAL", isin="INE758T01015"
        )

    past = registry.resolve("ZOMATO", date(2023, 6, 1))
    now = registry.resolve("ETERNAL", date(2026, 6, 1))
    leaked = registry.resolve("ETERNAL", date(2023, 6, 1))

    if past is None or now is None:
        return Check("point-in-time", False, "a known ticker failed to resolve")
    if past is not now:
        return Check("point-in-time", False, "the rename split one instrument in two")
    if leaked is not None:
        return Check("point-in-time", False, "a future ticker resolved on a past date — lookahead")
    return Check("point-in-time", True, "past dates return past names")


def check_master_is_persisted() -> Check:
    """A master rebuilt from B2 on every call is a moving target.

    Two callers building at different moments could see different histories,
    which is not a property a join key may have.
    """
    from eulerlab.master.store import MASTER_PATH, load

    if not MASTER_PATH.exists():
        return Check("persisted", False, f"{MASTER_PATH} missing — run `make build-master`")
    try:
        registry, stamp = load(MASTER_PATH)
    except (ValueError, KeyError) as exc:
        return Check("persisted", False, f"unreadable: {exc}")
    if len(registry) == 0:
        return Check("persisted", False, "master is empty")
    return Check(
        "persisted",
        True,
        f"{len(registry)} instruments, built {stamp.built_at[:10]} from {stamp.source_files} files",
    )


def run() -> list[Check]:
    symbol_map = load(RENAMES_PATH) if RENAMES_PATH.exists() else None
    return [
        check_symbol_map_exists(symbol_map),
        check_every_stuck_symbol_is_explained(symbol_map),
        check_successions_are_sourced(),
        check_ratios_present_where_required(),
        check_point_in_time_query(),
        check_master_is_persisted(),
    ]


def main(argv: Sequence[str] | None = None) -> int:
    checks = run()
    print(f"{'CHECK':<16}{'RESULT':<9}DETAIL")
    for check in checks:
        print(f"{check.name:<16}{'PASS' if check.ok else 'FAIL':<9}{check.detail}")
    failed = [c for c in checks if not c.ok]
    if failed:
        print(f"\ncheck-master FAILED: {len(failed)} of {len(checks)}", file=sys.stderr)
        return 1
    print(f"\ncheck-master OK: {len(checks)} of {len(checks)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
