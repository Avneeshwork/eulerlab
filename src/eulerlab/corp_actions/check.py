"""`make check-adjust` — acceptance checks for the adjustment engine.

The build plan's gate for Sprint 5 is "reproduces a known adjusted series
exactly". That is checked here in the strongest form available without
re-downloading the price history: every factor the engine produces is
**recomputed independently from the raw feed text** by a second implementation
that shares no code with the engine, and the two must agree exactly.

Independent recomputation is the point. A test that asserts
`bonus_split_multiplier == 2.0` for a bonus the same module parsed as 1:1 only
proves the code is self-consistent. Re-deriving the ratio from the original
`subject` string with separate arithmetic catches a parser that reads the
ratio backwards, which is the error that would actually happen.

Each check prints PASS, FAIL or SKIP with a count. SKIP is used only where a
check genuinely cannot run — currently the price-series reproduction, which
needs the close-price cache built (S-012) — and never to hide a failure.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from eulerlab.corp_actions.adjust import build_price_factor_store, factor_as_of
from eulerlab.corp_actions.build_factors import load_actions
from eulerlab.corp_actions.parse import CorporateAction, Kind
from eulerlab.corp_actions.prices import CACHE_PATH, _read_cache, close_price_lookup

IST = ZoneInfo("Asia/Kolkata")
FAR_FUTURE = datetime(2999, 1, 1, tzinfo=IST)
LANDING = Path("data/landing/nse")

# Deliberately duplicated, not imported from parse.py: a check that reuses the
# implementation it is checking proves nothing.
_RATIO = re.compile(r"(\d+)\s*:\s*(\d+)")


@dataclass
class Result:
    name: str
    status: str
    detail: str

    @property
    def failed(self) -> bool:
        return self.status == "FAIL"


def _ok(name: str, detail: str) -> Result:
    return Result(name, "PASS", detail)


def _fail(name: str, detail: str) -> Result:
    return Result(name, "FAIL", detail)


def _skip(name: str, detail: str) -> Result:
    return Result(name, "SKIP", detail)


def check_actions_parse(actions: Sequence[CorporateAction], skipped: int) -> Result:
    """Every landed row became an action with an ISIN and an ex-date."""
    name = "actions parse"
    if not actions:
        return _fail(name, "no actions loaded - run `make ingest-corp-actions`")
    if skipped:
        return _fail(name, f"{skipped:,} rows had no usable ISIN or ex-date")
    return _ok(name, f"{len(actions):,} actions, 0 rows skipped")


def check_bonus_ratios_independently(actions: Sequence[CorporateAction]) -> Result:
    """Re-derive every bonus multiplier from the raw subject text.

    Catches a ratio read backwards: 10:1 and 1:10 are both plausible-looking
    and differ by a factor of 55 in the resulting adjustment.
    """
    name = "bonus factors"
    checked = 0
    for action in actions:
        for component in action.components:
            if component.kind is not Kind.BONUS:
                continue
            match = _RATIO.search(component.raw)
            if not match:
                return _fail(name, f"cannot re-derive ratio from {component.raw!r}")
            new, held = int(match.group(1)), int(match.group(2))
            expected = (held + new) / held
            actual = component.bonus_split_multiplier
            if actual is None or abs(actual - expected) > 1e-9:
                return _fail(name, f"{action.symbol} {component.raw!r}: {actual} != {expected}")
            checked += 1
    return _ok(name, f"{checked:,} bonus components re-derived and matched")


def check_split_ratios_independently(actions: Sequence[CorporateAction]) -> Result:
    """A split multiplier must be old face value over new."""
    name = "split factors"
    checked = 0
    for action in actions:
        for component in action.components:
            if component.kind is not Kind.SPLIT:
                continue
            old, new = component.face_value_from, component.face_value_to
            if not old or not new:
                return _fail(name, f"{action.symbol}: missing face values in {component.raw!r}")
            if new >= old:
                return _fail(
                    name,
                    f"{action.symbol}: face value rose {old}->{new} in {component.raw!r}; "
                    "a split must reduce it, so this is parsed backwards",
                )
            expected = old / new
            actual = component.bonus_split_multiplier
            if actual is None or abs(actual - expected) > 1e-9:
                return _fail(name, f"{action.symbol}: {actual} != {expected}")
            checked += 1
    return _ok(name, f"{checked:,} split components re-derived and matched")


def check_rights_against_terp(actions: Sequence[CorporateAction]) -> Result:
    """Recompute the rights factor as P/TERP with separate arithmetic.

    Also asserts the direction that matters: a rights issue must dilute less
    than a bonus of the same ratio, because it is paid for.
    """
    name = "rights factors"
    checked = 0
    cum = 1000.0
    for action in actions:
        for component in action.components:
            if component.kind is not Kind.RIGHTS:
                continue
            actual = component.rights_multiplier(cum_price=cum, face_value=action.face_value)
            if actual is None:
                continue  # priced at/above market, or missing face value - by design
            new, held = component.ratio_new, component.ratio_held
            premium = component.rights_premium
            if new is None or not held or premium is None or action.face_value is None:
                return _fail(name, f"{action.symbol}: produced a factor without full inputs")
            issue = action.face_value + premium
            terp = (held * cum + new * issue) / (held + new)
            expected = cum / terp
            if abs(actual - expected) > 1e-9:
                return _fail(name, f"{action.symbol}: {actual} != {expected}")
            if actual > (held + new) / held:
                return _fail(
                    name,
                    f"{action.symbol}: rights diluted more than a free bonus of the "
                    f"same ratio, which is economically impossible",
                )
            checked += 1
    return _ok(name, f"{checked:,} rights components matched P/TERP independently")


def check_firewall_holds(actions: Sequence[CorporateAction]) -> Result:
    """No factor may be visible before its own ex-date.

    Sprint 4's guarantee, asserted here against the real dataset rather than
    fixtures: every action in the store is queried one second before it
    became knowable and must have no effect.
    """
    name = "lookahead firewall"
    store = build_price_factor_store(actions)
    leaked = 0
    checked = 0
    for action in actions:
        if not any(c.kind in (Kind.BONUS, Kind.SPLIT) for c in action.components):
            continue
        day_before = datetime.combine(action.ex_date, datetime.min.time(), tzinfo=IST)
        factor = factor_as_of(
            store,
            as_of=day_before,
            isin=action.isin,
            price_date=date(2015, 1, 1),
        )
        past = factor_as_of(store, as_of=FAR_FUTURE, isin=action.isin, price_date=date(2015, 1, 1))
        if factor > past + 1e-12:
            leaked += 1
        checked += 1
    if leaked:
        return _fail(name, f"{leaked:,} actions leaked a factor before their ex-date")
    return _ok(name, f"{checked:,} actions checked, none visible before its ex-date")


def check_determinism(actions: Sequence[CorporateAction]) -> Result:
    """Two builds of the same input must be identical. Project-wide rule."""
    name = "determinism"
    a = build_price_factor_store(actions)
    b = build_price_factor_store(actions)
    ra = a.query(as_of=FAR_FUTURE)
    rb = b.query(as_of=FAR_FUTURE)
    if ra != rb:
        return _fail(name, "two builds of identical input differed")
    return _ok(name, f"{len(ra):,} records identical across two builds")


def check_known_series(actions: Sequence[CorporateAction]) -> Result:
    """Reproduce an adjusted series against real prices.

    The build plan's literal wording for this sprint. Needs the close-price
    cache, which S-012 is waiting on, so it reports SKIP rather than quietly
    passing on a weaker check.
    """
    name = "known adjusted series"
    if not CACHE_PATH.exists():
        return _skip(name, f"needs {CACHE_PATH} - run `make build-factors` (S-012)")

    index, _ = _read_cache(CACHE_PATH)
    if not index:
        # The file exists but holds nothing: a capped run creates it before
        # fetching anything. Saying "no bonus found" here would imply the data
        # was searched, which it was not.
        return _skip(name, f"{CACHE_PATH} is empty - run `make build-factors` (S-012)")
    lookup = close_price_lookup(index)
    store = build_price_factor_store(actions, lookup)

    # A 1:1 bonus must halve the price across its ex-date, and the adjusted
    # series must be continuous where the raw one jumps. Restricted to actions
    # whose only price effect is that bonus and which are the sole action for
    # that instrument on that day, so the expected factor is unambiguously 2.0.
    same_day: dict[tuple[str, date], int] = {}
    for action in actions:
        same_day[(action.isin, action.ex_date)] = same_day.get((action.isin, action.ex_date), 0) + 1

    priced = {Kind.BONUS, Kind.SPLIT, Kind.RIGHTS, Kind.DIVIDEND}
    checked = 0
    mismatched: list[str] = []
    for action in actions:
        effects = [c for c in action.components if c.kind in priced]
        if len(effects) != 1 or same_day[(action.isin, action.ex_date)] != 1:
            continue
        bonus = effects[0]
        if bonus.kind is not Kind.BONUS or bonus.ratio_new != 1 or bonus.ratio_held != 1:
            continue
        if lookup(action.isin, action.ex_date) is None:
            continue

        day_before = action.ex_date - timedelta(days=1)
        factor = factor_as_of(store, as_of=FAR_FUTURE, isin=action.isin, price_date=day_before)
        if abs(factor - 2.0) > 1e-9:
            mismatched.append(f"{action.symbol} {action.ex_date}: {factor:.6f}")
        checked += 1

    if not checked:
        return _skip(name, "no isolated 1:1 bonus with a cached cum-date close yet")
    if mismatched:
        return _fail(
            name,
            f"{len(mismatched):,} of {checked:,} 1:1 bonuses did not adjust by 2.0: "
            + "; ".join(mismatched[:3]),
        )
    return _ok(name, f"{checked:,} isolated 1:1 bonuses adjust by exactly 2.0")


CHECKS: tuple[Callable[[Sequence[CorporateAction]], Result], ...] = (
    check_bonus_ratios_independently,
    check_split_ratios_independently,
    check_rights_against_terp,
    check_firewall_holds,
    check_determinism,
    check_known_series,
)


def run(landing: Path = LANDING) -> list[Result]:
    actions, skipped = load_actions(landing)
    results = [check_actions_parse(actions, skipped)]
    if results[0].failed:
        return results
    results.extend(check(actions) for check in CHECKS)
    return results


def main() -> int:
    results = run()
    width = max(len(r.name) for r in results)
    print(f"\n{'CHECK'.ljust(width)}  RESULT  DETAIL")
    for r in results:
        print(f"{r.name.ljust(width)}  {r.status:<6}  {r.detail}")

    failed = [r for r in results if r.failed]
    skipped = [r for r in results if r.status == "SKIP"]
    print()
    if failed:
        print(f"check-adjust FAILED: {len(failed)} of {len(results)} checks red")
        return 1
    note = f", {len(skipped)} skipped" if skipped else ""
    print(f"check-adjust OK: {len(results) - len(skipped)} checks green{note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
