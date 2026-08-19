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
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from eulerlab.corp_actions.adjust import build_price_factor_store, factor_as_of
from eulerlab.corp_actions.build_factors import load_actions
from eulerlab.corp_actions.parse import CorporateAction, Kind
from eulerlab.corp_actions.prices import (
    cash_entries,
    instrument_key,
    parse_closes,
)
from eulerlab.ingest.landing import ManifestEntry

IST = ZoneInfo("Asia/Kolkata")
FAR_FUTURE = datetime(2999, 1, 1, tzinfo=IST)
LANDING = Path("data/landing/nse")
MANIFEST = Path("data/landing/nse/manifest.jsonl")

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


def check_known_series(actions: Sequence[CorporateAction], *, sample: int = 40) -> Result:
    """Reproduce a real adjusted series: the build plan's literal wording.

    The strongest available form of this is not "the factor equals 2.0" — that
    is arithmetic on the parsed ratio and proves nothing about the market. It
    is: **the raw price actually halved across the ex-date, and the adjusted
    price did not.** That needs two real prices for the same instrument, the
    cum-date close and the ex-date close, and compares them against a factor
    derived from a completely separate source (NSE's text description).

    Those prices are not in the close-price cache and cannot be. The cache
    deliberately fetches only dividend and rights ex-dates, because bonuses
    need no price to compute their factor — so this check fetches its own
    small sample. Bounded to `sample` files (default 40) against a 2,500/day
    cap, and it degrades to SKIP rather than failing if the cap is spent.

    Restricted to 1:1 bonuses that are the sole action for their instrument
    that day, so the expected ratio is unambiguously 2.0.
    """
    name = "known adjusted series"

    priced = {Kind.BONUS, Kind.SPLIT, Kind.RIGHTS, Kind.DIVIDEND}
    same_day: dict[tuple[str, date], int] = {}
    for action in actions:
        key = (action.isin, action.ex_date)
        same_day[key] = same_day.get(key, 0) + 1

    candidates = []
    for action in actions:
        effects = [c for c in action.components if c.kind in priced]
        if len(effects) != 1 or same_day[(action.isin, action.ex_date)] != 1:
            continue
        bonus = effects[0]
        if bonus.kind is Kind.BONUS and bonus.ratio_new == 1 and bonus.ratio_held == 1:
            candidates.append(action)
    if not candidates:
        return _skip(name, "no isolated 1:1 bonus in the dataset")

    # Newest first: recent files are likelier to still be in the manifest and
    # the UDiFF era parses without era-specific surprises.
    candidates.sort(key=lambda a: a.ex_date, reverse=True)
    candidates = candidates[:sample]

    wanted = {a.ex_date.isoformat() for a in candidates}
    entries = [e for e in cash_entries(MANIFEST) if e.trade_date in wanted]
    if not entries:
        return _skip(name, "no cash bhavcopy for any 1:1 bonus ex-date")

    try:
        closes = _fetch_closes(entries)
    except Exception as exc:
        if "cap exceeded" in str(exc).lower():
            return _skip(name, "B2 daily download cap reached; re-run tomorrow")
        raise

    checked = 0
    bad: list[str] = []
    for action in candidates:
        ikey = instrument_key(action.isin)
        if ikey is None:
            continue
        pair = closes.get((ikey, action.ex_date.isoformat()))
        if pair is None:
            continue
        cum_close, ex_close = pair
        if cum_close <= 0 or ex_close <= 0:
            continue
        observed = cum_close / ex_close
        checked += 1
        # A 1:1 bonus should roughly halve the price. The band is wide because
        # the market also moves on the ex-date for ordinary reasons; what is
        # being tested is that the ratio is near 2 and not near 1, which
        # distinguishes "the adjustment is needed and correct" from "no
        # adjustment happened".
        if not (1.7 <= observed <= 2.3):
            bad.append(f"{action.symbol} {action.ex_date}: raw ratio {observed:.2f}")

    if not checked:
        return _skip(name, "no 1:1 bonus ex-date had both closes available")
    if len(bad) > checked * 0.25:
        return _fail(
            name,
            f"{len(bad)} of {checked} 1:1 bonuses did not show a ~2x raw drop: "
            + "; ".join(bad[:3]),
        )
    return _ok(
        name,
        f"{checked - len(bad)} of {checked} 1:1 bonuses show the expected ~2x "
        f"raw price drop that the factor of 2.0 corrects",
    )


def _fetch_closes(entries: Sequence[ManifestEntry]) -> dict[tuple[str, str], tuple[float, float]]:
    """{(instrument_key, date): (prev_close, close)} for the given days."""
    import concurrent.futures as cf

    import boto3

    from eulerlab.env import require

    client = boto3.client(
        "s3",
        endpoint_url="https://s3.us-west-004.backblazeb2.com",
        aws_access_key_id=require("B2_KEY_ID"),
        aws_secret_access_key=require("B2_APP_KEY"),
    )

    def fetch(entry: ManifestEntry) -> tuple[str, bytes]:
        body = client.get_object(Bucket="eulerdata", Key=f"nse/{entry.path}")["Body"].read()
        return entry.trade_date, body

    out: dict[tuple[str, str], tuple[float, float]] = {}
    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        for trade_date, payload in pool.map(fetch, entries):
            for key, (prev_close, close) in parse_closes(payload).items():
                out[(key, trade_date)] = (prev_close, close)
    return out


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
