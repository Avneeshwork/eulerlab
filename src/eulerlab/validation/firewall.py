"""What a screen's result is worth after the search that found it (ADR-172).

The simple gate (ADR-140) does not correct for how many rules were tried, and
the autopilot tries ten a night. This module puts three numbers beside every
screen, from the experiment store. They are shown, and flag nothing yet: the
thresholds that would turn them into a refusal are the operator's to set
(T-4574), and `gates.py` is not touched.

1. **Distinct ideas tried.** Every rule in the store with daily returns is
   clustered into families (`search_bar.family_bar`, average linkage at 0.7,
   S-057). A hundred variants of one gap fade are one idea, not a hundred.
2. **Deflated Sharpe.** The chance the rule's true Sharpe is above zero, given
   that many families and the spread of their Sharpes. Under 0.95 a result is
   what searching this hard produces from noise.
3. **Does it hold on the selection period.** The rule is found on data up to
   the constitution's `discovery_end`. Its Sharpe on the selection period
   (after that, up to `backtest_end`) is not shown. Only one bit comes back:
   whether it kept at least `KEEP` of its discovery Sharpe, after a small
   random nudge fixed by the rule's fingerprint. That is the reusable holdout
   (Dwork et al. 2015, research 189): an answer too coarse to tune against,
   so the selection period survives many looks. Every look is counted.

An honest limit: both periods were read by earlier research (ADR-143). This
slows further damage. Only the forward test from 2026 is clean.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from eulerlab import constitution
from eulerlab.research import strategy_map
from eulerlab.validation import search_bar
from eulerlab.validation.statistics import deflated_sharpe, sharpe_stats

JOIN_AT = 0.7
"""Correlation at which two rules are one family. The gate's own number (S-057)."""
KEEP = 0.5
# ASSUMPTION: A-136 — KEEP, NOISE and MIN_DAYS are chosen by hand, not fitted.
"""Share of the discovery Sharpe a rule must keep on the selection period."""
NOISE = 0.25
"""Width of the random nudge added to the selection Sharpe before the comparison."""
MIN_DAYS = 60
"""Fewer sessions than this in a period and its Sharpe is not read."""


@dataclass(frozen=True)
class Firewall:
    rules_tried: int
    families: int | None
    noise_bar: float | None
    """The Sharpe the best of that many families of noise would show."""
    deflated_sharpe: float | None
    discovery_sharpe: float | None
    selection_days: int
    holds_on_selection: bool | None
    """None when either period is too short to say."""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _split(daily: Mapping[date, float]) -> tuple[list[float], list[float]]:
    periods = constitution.load().periods
    found: dict[str, list[float]] = {"discovery": [], "selection": [], "forward": []}
    for day in sorted(daily):
        found[periods.part(day)].append(daily[day])
    return found["discovery"], found["selection"]


def _nudge(fingerprint: str) -> float:
    """A fixed draw in [-NOISE, NOISE] per rule: the same rule gets the same answer."""
    seed = int(hashlib.sha256(fingerprint.encode()).hexdigest()[:12], 16)
    return random.Random(seed).uniform(-NOISE, NOISE)  # seeded: deterministic by design


def holds(daily: Mapping[date, float], fingerprint: str) -> tuple[float | None, int, bool | None]:
    """(discovery Sharpe, selection sessions, kept enough of it on selection or None)."""
    found, kept = _split(daily)
    base = strategy_map.sharpe(found) if len(found) >= MIN_DAYS else None
    if base is None or len(kept) < MIN_DAYS:
        return base, len(kept), None
    later = strategy_map.sharpe(kept)
    if later is None:
        return base, len(kept), None
    return base, len(kept), base > 0 and later + _nudge(fingerprint) >= KEEP * base


def assess(
    daily: Mapping[date, float], fingerprint: str, others: Sequence[Mapping[date, float]]
) -> Firewall:
    """The three numbers for one rule, against every other rule tried (`others`)."""
    base, days, kept = holds(daily, fingerprint)
    bar = search_bar.family_bar([dict(daily), *others], join_at=JOIN_AT)
    deflated = None
    if bar is not None and len(daily) >= 3:
        deflated = round(
            deflated_sharpe(
                sharpe_stats(list(daily.values())),
                n_trials=max(bar.families, 1),
                variance_of_sharpes=bar.sigma * bar.sigma,
            ),
            4,
        )
    return Firewall(
        rules_tried=len(others) + 1,
        families=bar.families if bar else None,
        noise_bar=bar.bar if bar else None,
        deflated_sharpe=deflated,
        discovery_sharpe=round(base, 3) if base is not None else None,
        selection_days=days,
        holds_on_selection=kept,
    )
