"""Stated shocks, through each holding's beta where the shock is a market move, and the limit rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from eulerlab.risk.book.exposure import by_sector

# --- stress -------------------------------------------------------------------------


def stress(
    names: Sequence[Mapping[str, Any]],
    betas: Mapping[str, float | None],
    sectors: Mapping[str, str],
    equity: float,
    worst_day: tuple[str, float] | None,
    gap_notional: float = 0.0,
    worst_gap: tuple[str, float] | None = None,
) -> list[dict[str, Any]]:
    """What today's holdings lose in each named bad day, as negative rupees.

    A market fall reaches each name through its own beta to the Nifty; a name
    with no measured beta is taken to move with the market (beta 1).
    """

    def market(shock: float) -> float:
        return float(sum(row["value"] * (betas.get(row["symbol"]) or 1.0) * shock for row in names))

    out: list[dict[str, Any]] = [
        {
            "key": "nifty_13",
            "label": "Nifty falls 13% in a day",
            "note": "as on 23 March 2020, by each holding's beta",
            "loss": market(-0.13),
        },
        {
            "key": "nifty_10",
            "label": "Nifty falls 10% in a day",
            "note": "by each holding's beta",
            "loss": market(-0.10),
        },
        {
            "key": "nifty_5",
            "label": "Nifty falls 5% in a day",
            "note": "by each holding's beta",
            "loss": market(-0.05),
        },
    ]
    if worst_day is not None:
        out.append(
            {
                "key": "worst_day",
                "label": "The worst day of the last year, again",
                "note": worst_day[0],
                "loss": worst_day[1],
            }
        )
    grouped = by_sector(names, sectors)
    if grouped:
        top = grouped[0]
        out.append(
            {
                "key": "sector",
                "label": f"{top['sector']} falls 8%, the rest flat",
                "note": "the largest sector",
                "loss": -0.08 * top["value"],
            }
        )
    if names:
        out.append(
            {
                "key": "name",
                "label": "The largest name falls 20%",
                "note": names[0]["symbol"],
                "loss": -0.20 * abs(names[0]["value"]),
            }
        )
    if gap_notional > 0:
        # A fall in the market overnight reaches the future one for one, on
        # top of what it does to the shares. Shown apart, because it applies
        # only on a night the future is held.
        out.append(
            {
                "key": "gap_3",
                "label": "The future is held and opens 3% lower",
                "note": "the futures position alone",
                "loss": -0.03 * gap_notional,
            }
        )
        if worst_gap is not None:
            out.append(
                {
                    "key": "gap_worst",
                    "label": "The future is held through its worst gap on record",
                    "note": f"{worst_gap[0]}, {worst_gap[1] * 100:.1f}%; the futures position alone",
                    "loss": worst_gap[1] * gap_notional,
                }
            )
    for row in out:
        row["loss"] = round(min(0.0, row["loss"]), 2)
        row["share"] = round(row["loss"] / equity, 6) if equity > 0 else 0.0
    return out


# --- limits -------------------------------------------------------------------------


def limit_row(
    name: str, now: float, limit: float, unit: str, kind: str, when: str, *, near: float = 0.75
) -> dict[str, Any]:
    """One limit with how much of it is used. `kind` is `enforced` or `watch`."""
    used = max(0.0, now / limit) if limit > 0 else 0.0
    state = "over" if used >= 1 else "near" if used >= near else "ok"
    return {
        "name": name,
        "now": round(now, 4),
        "limit": limit,
        "unit": unit,
        "used": round(used, 4),
        "state": state,
        "kind": kind,
        "when": when,
    }
