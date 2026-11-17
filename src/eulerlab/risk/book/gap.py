"""Risk of a gap rule on the nights it holds."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from eulerlab.risk.book.common import MIN_GAP_NIGHTS
from eulerlab.risk.book.holdings import GapRule
from eulerlab.risk.book.var import quantile_loss


def gap_summary(rule: GapRule, days: Sequence[date]) -> dict[str, Any]:
    """What a night in position can cost, read from the nights it was held.

    `when_held` uses only signal nights in the window: the position is never
    open on any other night, so those are the gaps it can actually meet.
    """
    window = [day for day in days[1:] if day in rule.gaps]
    nights = [rule.notional * rule.gaps[day] for day in window if day in rule.held]
    var95, es95 = quantile_loss(nights, 0.95) if len(nights) >= MIN_GAP_NIGHTS else (0.0, 0.0)
    worst_held = min(
        ((day, rule.notional * rule.gaps[day]) for day in window if day in rule.held),
        key=lambda item: item[1],
        default=None,
    )
    return {
        "contract": rule.contract,
        "lots": rule.lots,
        "lot_size": rule.lot_size,
        "notional": round(rule.notional, 2),
        "nights": len(window),
        "nights_held": len(nights),
        "held_share": round(len(nights) / len(window), 4) if window else 0.0,
        "enough": len(nights) >= MIN_GAP_NIGHTS,
        "var95_when_held": round(var95, 2),
        "es95_when_held": round(es95, 2),
        "worst_night": (
            {"day": worst_held[0].isoformat(), "pnl": round(worst_held[1], 2)}
            if worst_held and worst_held[1] < 0
            else None
        ),
        "holds_tonight": rule.held_now > 0,
        "held_now": round(rule.held_now, 2),
        "worst_ever": (
            {
                "day": rule.worst[0].isoformat(),
                "gap": round(rule.worst[1], 6),
                "pnl": round(rule.notional * rule.worst[1], 2),
            }
            if rule.worst
            else None
        ),
    }
