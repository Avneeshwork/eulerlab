"""Two earnings-event strategies on NSE's dated results announcements.

Research 113, batch 5. Both read `nse_earnings_announcements` (make
nse-earnings-announcements): the first NSE disclosure of each company's
results, with its `knowledge_time`. A decision on day d sees only
announcements known by d's close, so neither strategy can read a date early.

- Earnings announcement premium: Barber, De George, Lehavy & Trueman (2013),
  JFE 108(1), across many countries; Frazzini & Lamont (2007). Stocks earn
  more around scheduled announcements. The next date is predicted as the same
  quarter's date a year earlier, the paper's method.
- Post-earnings drift by announcement return: Chan, Jegadeesh & Lakonishok
  (1996), JF 51(5); Brandt, Kishore, Santa-Clara & Venkatachalam (2008). In
  India, drift in the direction of the surprise over 2002-2017 (research 113).
  EPS surprises are not held here, so the surprise is the stock's two-day
  return around the announcement, net of NIFTYBEES.

The data covers 2021-07 to 2024 and labels July-December 2022 differently
(research 112), so fewer events are seen then. Run on 2021-08..2024-11 only
(`make events-daily`); elsewhere the strategies would hold cash.
"""

from __future__ import annotations

from collections.abc import Callable

from eulerlab.backtest.strategy import Strategy
from eulerlab.strategies.daily.events.common import (
    EVENTS_WINDOW,
    HOLD,
    WEEK,
    DriftMomentum,
    _index_at,
    announcements,
    known_by,
    recent_reaction,
)
from eulerlab.strategies.daily.events.india_announcement_drift import (
    STRATEGIES as _india_announcement_drift,
)
from eulerlab.strategies.daily.events.india_announcement_drift import AnnouncementDrift
from eulerlab.strategies.daily.events.india_drift_momentum_combo import (
    STRATEGIES as _india_drift_momentum_combo,
)
from eulerlab.strategies.daily.events.india_drift_momentum_topdown import (
    STRATEGIES as _india_drift_momentum_topdown,
)
from eulerlab.strategies.daily.events.india_earnings_announcement_premium import (
    STRATEGIES as _india_earnings_announcement_premium,
)
from eulerlab.strategies.daily.events.india_earnings_announcement_premium import AnnouncementPremium
from eulerlab.strategies.daily.india_papers import PaperStrategy

STRATEGIES: tuple[PaperStrategy, ...] = (
    *_india_earnings_announcement_premium,
    *_india_announcement_drift,
    *_india_drift_momentum_combo,
    *_india_drift_momentum_topdown,
)

BUILDERS: dict[str, Callable[[], Strategy]] = {s.id: s.build for s in STRATEGIES}
BY_ID: dict[str, PaperStrategy] = {s.id: s for s in STRATEGIES}


__all__ = [
    "BUILDERS",
    "BY_ID",
    "EVENTS_WINDOW",
    "HOLD",
    "STRATEGIES",
    "WEEK",
    "AnnouncementDrift",
    "AnnouncementPremium",
    "DriftMomentum",
    "_index_at",
    "announcements",
    "known_by",
    "recent_reaction",
]
