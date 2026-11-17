"""Earnings drift plus Clenow momentum (India).

Source: Chan, Jegadeesh & Lakonishok (1996); Clenow (2015) via skyte/momentum.

One daily earnings-event strategy. Its rule and its library entry (STRATEGIES, at the
bottom) are both in this file.
"""

from __future__ import annotations

from eulerlab.strategies.daily.events.common import DriftMomentum
from eulerlab.strategies.daily.india_papers import PaperStrategy

STRATEGIES = (
    PaperStrategy(
        "india_drift_momentum_combo",
        "Earnings drift plus Clenow momentum (India)",
        "chan-jegadeesh-lakonishok-1996-announcement-drift",
        "Chan, Jegadeesh & Lakonishok (1996); Clenow (2015) via skyte/momentum",
        "Weekly, hold the 15 recent reporters with a positive reaction and the steepest, smoothest trend.",
        (
            "Announced 2-60 sessions ago with a positive two-day reaction net of NIFTYBEES, "
            "and in Clenow's filter (above the 100-day average, no 15% day).",
            "Ranked by Clenow's slope x R^2, 15 names at fixed fifteenths. Run 2021-08 to 2024-11.",
        ),
        140,
        lambda: DriftMomentum("india_drift_momentum_combo"),
    ),
)
