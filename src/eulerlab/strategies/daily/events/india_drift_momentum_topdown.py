"""Earnings drift plus Clenow momentum, top 5 sectors only (India).

Source: Chan, Jegadeesh & Lakonishok (1996); Moskowitz & Grinblatt (1999); research 182.

One daily earnings-event strategy. Its rule and its library entry (STRATEGIES, at the
bottom) are both in this file.
"""

from __future__ import annotations

from eulerlab.strategies.daily.events.common import DriftMomentum
from eulerlab.strategies.daily.india_papers import PaperStrategy

STRATEGIES = (
    PaperStrategy(
        "india_drift_momentum_topdown",
        "Earnings drift plus Clenow momentum, top 5 sectors only (India)",
        "chan-jegadeesh-lakonishok-1996-announcement-drift",
        "Chan, Jegadeesh & Lakonishok (1996); Moskowitz & Grinblatt (1999); research 182",
        "As the drift-momentum combo, but only among stocks in the five sectors with the best six months.",
        (
            "Sectors: equal-weighted 126-session return of their liquid members (3 or more); "
            "top 5 kept (backtest.topdown). Sector tags are today's (A-128).",
            "Then as india_drift_momentum_combo: 15 names at fixed fifteenths. Run 2021-08 to 2024-11.",
        ),
        140,
        lambda: DriftMomentum("india_drift_momentum_topdown", topdown=True),
    ),
)
