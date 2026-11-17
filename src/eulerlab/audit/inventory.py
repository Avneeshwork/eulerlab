"""Where every strategy actually lives, and whether its names agree.

Twenty-four intraday signals sit in two files, and their ids do not match the
functions implementing them — `orb_breakout` is `opening_range_breakout`,
`ou_reversion` is `ou_mean_reversion`. That is not wrong, but it is invisible:
someone grepping for a strategy id finds the registry entry and not the code.

Five of them are deliberate aliases. The India adaptations reuse their US
counterpart's detect function by design, so `ou_reversion_in` and
`ou_reversion` are the same procedure pointed at a different instrument. An
inventory that reported those as duplicates would be wrong about the thing it
exists to explain, so they are named as aliases instead.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass

from eulerlab.audit import Finding, Severity


@dataclass(frozen=True)
class Entry:
    """One strategy, and the code behind it."""

    strategy_id: str
    module: str
    function: str
    kind: str
    #: The strategy this one shares an implementation with, if any.
    alias_of: str = ""

    @property
    def name_matches(self) -> bool:
        return self.strategy_id == self.function


def _intraday() -> list[Entry]:
    from eulerlab.intraday.paper_scan import ALL_SIGNALS

    seen: dict[tuple[str, str], str] = {}
    out: list[Entry] = []
    for strategy_id in sorted(ALL_SIGNALS):
        detect = getattr(ALL_SIGNALS[strategy_id], "detect", None)
        module = inspect.getmodule(detect)
        where = module.__name__.rsplit(".", 1)[-1] if module else "?"
        function = getattr(detect, "__name__", "?")
        key = (where, function)
        out.append(
            Entry(
                strategy_id=strategy_id,
                module=f"{where}.py",
                function=function,
                kind="intraday",
                alias_of=seen.get(key, ""),
            )
        )
        seen.setdefault(key, strategy_id)
    return out


def _daily() -> list[Entry]:
    from eulerlab.strategies.daily.published import BUILDERS

    return [
        Entry(
            strategy_id=name,
            module="published.py",
            function=getattr(builder, "__name__", "?"),
            kind="daily",
        )
        for name, builder in sorted(BUILDERS.items())
    ]


def inventory() -> list[Entry]:
    """Every runnable strategy, daily and intraday, with its source."""
    return sorted(_daily() + _intraday(), key=lambda e: (e.kind, e.strategy_id))


def render(entries: list[Entry] | None = None) -> str:
    """The inventory as a table, which is the deliverable the operator asked for."""
    rows = entries if entries is not None else inventory()
    width = max((len(r.strategy_id) for r in rows), default=12)
    lines = [f"{'strategy':{width}s}  {'file':20s} {'function':28s} note", "-" * (width + 62)]
    for row in rows:
        if row.alias_of:
            note = f"shares its implementation with {row.alias_of}"
        elif not row.name_matches:
            note = "id differs from function name"
        else:
            note = ""
        lines.append(f"{row.strategy_id:{width}s}  {row.module:20s} {row.function:28s} {note}")
    lines.append("")
    lines.append(f"{len(rows)} strategies across {len({r.module for r in rows})} files")
    return "\n".join(lines)


def check_names(entries: list[Entry] | None = None) -> list[Finding]:
    """Report where a strategy cannot be found by its own name.

    A NOTE rather than a WARN. Renaming twenty-four functions to match their
    ids would touch the tuned registry, the sweep grids and the ledger
    subjects, and none of that is worth doing to satisfy a linter. The point of
    the finding is that the mapping is written down somewhere a person reads.
    """
    rows = entries if entries is not None else inventory()
    out: list[Finding] = []
    for row in rows:
        if row.alias_of or row.name_matches:
            continue
        out.append(
            Finding(
                rule="strategy-name-differs",
                severity=Severity.NOTE,
                message=f"{row.strategy_id} is implemented by {row.function}()",
                path=row.module,
                because="grep for the id finds the registry entry, not the code",
            )
        )
    return out
