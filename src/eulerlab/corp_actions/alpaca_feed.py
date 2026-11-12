"""Alpaca's US corporate actions, in the shape this engine already speaks.

### What this is not

It is **not** a second adjustment engine. `adjust.py` already turns actions
into a bitemporal factor store, and `panel.py` already refuses to store
adjusted prices because the correct adjustment depends on the date you are
standing on — a strategy deciding in January must not see prices adjusted for
a split that goes ex in May. That machinery is right and this feeds it.

All that was missing for US listings was a translation: Alpaca publishes
`forward_splits`, `reverse_splits` and `cash_dividends` with their own field
names, and the engine expects `CorporateAction` with `ParsedComponent`s.

### The ratio conventions differ, and getting them backwards is silent

Alpaca gives `old_rate` and `new_rate`. A 4-for-1 forward split is
`old_rate=1, new_rate=4`: one old share becomes four. The engine's
`bonus_split_multiplier` wants exactly that — units after per unit before — so
`ratio_new=new_rate, ratio_held=old_rate`.

A reverse split inverts it: `old_rate=10, new_rate=1` means ten shares become
one. Fed in the same order this is a multiplier below 1, which is correct, and
fed backwards it would silently multiply prices by ten instead of dividing.
Nothing downstream would flag it — a wrong factor produces a plausible price
series, which is why this note exists rather than a comment saying "map the
fields".
"""

from __future__ import annotations

from eulerlab.corp_actions.parse import CorporateAction, Kind, ParsedComponent
from eulerlab.paths import data_path

LANDING = data_path("landing/us/actions")


def _components(row: dict[str, object]) -> tuple[ParsedComponent, ...]:
    """One Alpaca row into the engine's components, or empty if unusable."""
    kind_name = str(row.get("action_type", ""))

    if kind_name in ("forward_splits", "reverse_splits"):
        try:
            old = float(row["old_rate"])  # type: ignore[arg-type]
            new = float(row["new_rate"])  # type: ignore[arg-type]
        except (KeyError, TypeError, ValueError):
            return ()
        if old <= 0 or new <= 0:
            return ()
        # Carried as face values, not as ratios, and that is not a typo.
        #
        # `Kind.SPLIT` in this engine means an NSE **face-value change**, and
        # its multiplier is `face_value_from / face_value_to`. It ignores
        # `ratio_new` and `ratio_held` entirely — those belong to `Kind.BONUS`,
        # whose multiplier is `(held + new) / held`, which for a 1:2 forward
        # split would give 1.5 where the truth is 2.0.
        #
        # The first version of this file filled in the ratio fields and every
        # split produced `multiplier=None`. That was the lucky outcome:
        # silently returning nothing is visible, whereas using BONUS would have
        # produced 1.5 for a doubling and nothing downstream would have
        # objected.
        #
        # Alpaca's `old_rate:new_rate` is units-before to units-after, so
        # 1:2 doubles the share count. Mapping new_rate to `face_value_from`
        # and old_rate to `face_value_to` makes the division come out as
        # units-after per unit-before: 2/1 = 2.0 forward, 1/10 = 0.1 reverse.
        return (
            ParsedComponent(
                kind=Kind.SPLIT,
                raw=f"{kind_name} {old:g}:{new:g}",
                face_value_from=new,
                face_value_to=old,
            ),
        )

    if kind_name == "cash_dividends":
        try:
            rate = float(row["rate"])  # type: ignore[arg-type]
        except (KeyError, TypeError, ValueError):
            return ()
        if rate <= 0:
            return ()
        return (
            ParsedComponent(
                kind=Kind.DIVIDEND,
                raw=f"cash dividend {rate}",
                dividend_amount=rate,
            ),
        )

    return ()


def summary(actions: list[CorporateAction]) -> dict[str, int]:
    """What was translated, by kind — so a silent drop is visible as a count."""
    counts: dict[str, int] = {}
    for action in actions:
        for component in action.components:
            counts[component.kind.value] = counts.get(component.kind.value, 0) + 1
    counts["actions"] = len(actions)
    counts["symbols"] = len({a.symbol for a in actions})
    return counts
