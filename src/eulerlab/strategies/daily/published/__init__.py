"""Strategies from the published literature.

Each one cites the paper it comes from — `docs/RESEARCH/017` holds the URLs and
fetch dates. `CLAUDE.md` forbids inventing a source, and "a well-known strategy"
is not a source.

**These are published findings, not predictions about Indian equities.** Every
paper behind them is predominantly US evidence over windows ending years ago.
Momentum is the most replicated result in the literature and its premium still
decayed after publication. Nothing here has been backtested by this project,
and when it is, the noise bar applies.

Most of these are a `RankAndHold` over an existing feature — which is the
honest implementation, not a shortcut. The feature library was built from the
same literature, so "implement the low-volatility anomaly" genuinely is
"rank on `low_volatility` and hold the top N". Writing a bespoke class per
paper would produce ten copies of one loop and hide that fact.

`Composite` is the exception: it is not a rank over one feature, so it gets a
class.
"""

from __future__ import annotations

from collections.abc import Callable

from eulerlab.backtest.strategy import Strategy
from eulerlab.strategies.daily.published import (
    fifty_two_week_high,
    illiquidity_premium,
    low_volatility,
    momentum_6_1,
    momentum_12_1,
    momentum_quality,
    quality_composite,
    short_term_reversal,
    small_size,
    value_reversal,
)
from eulerlab.strategies.daily.published.common import Composite

MODULES = (
    momentum_12_1,
    momentum_6_1,
    short_term_reversal,
    low_volatility,
    fifty_two_week_high,
    illiquidity_premium,
    small_size,
    quality_composite,
    momentum_quality,
    value_reversal,
)
"""The ten published strategies, in library order. Each module carries its own
builder, SPEC and RESEARCH."""

BUILDERS: dict[str, Callable[..., Strategy]] = {
    "momentum_12_1": momentum_12_1.momentum_12_1,
    "momentum_6_1": momentum_6_1.momentum_6_1,
    "short_term_reversal": short_term_reversal.short_term_reversal,
    "low_volatility": low_volatility.low_volatility,
    "fifty_two_week_high": fifty_two_week_high.fifty_two_week_high,
    "illiquidity_premium": illiquidity_premium.illiquidity_premium,
    "small_size": small_size.small_size,
    "quality_composite": quality_composite.quality_composite,
    "momentum_quality": momentum_quality.momentum_quality,
    "value_reversal": value_reversal.value_reversal,
}
"""Name to builder. The registry and the batch runner both read this, so a
strategy cannot appear in the console without something able to build it."""

# Strategies from papers on Indian equities (`research/papers/`). Kept in their
# own module because each follows its own paper's rules rather than the shared
# `RankAndHold` shape.
from eulerlab.strategies.daily.india_papers import BUILDERS as _INDIA  # noqa: E402

BUILDERS.update(_INDIA)

# Daily rules from public GitHub repositories (research 113).
from eulerlab.strategies.daily.github import BUILDERS as _GITHUB_DAILY  # noqa: E402

BUILDERS.update(_GITHUB_DAILY)

# Momentum and reversal refinements with published evidence (research 113, batch 3).
from eulerlab.strategies.daily.evidence import BUILDERS as _EVIDENCE_DAILY  # noqa: E402

BUILDERS.update(_EVIDENCE_DAILY)

# Earnings-event strategies on NSE's dated announcements (research 113, batch 5).
from eulerlab.strategies.daily.events import BUILDERS as _EVENTS_DAILY  # noqa: E402

BUILDERS.update(_EVENTS_DAILY)

# The stock screener's long-term and swing models (ADR-136, research 150).
from eulerlab.strategies.daily.screener import BUILDERS as _SCREENER  # noqa: E402

BUILDERS.update(_SCREENER)


__all__ = ["BUILDERS", "MODULES", "Composite"]
