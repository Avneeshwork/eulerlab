"""``inverse_vol``: weight proportional to 1 / sigma over the last 126 days
(Maillard, Roncalli & Teiletche 2010; Kirby & Ostdiek 2012)."""

from __future__ import annotations

from eulerlab.risk.sizing.common import Matrix


def inverse_vol(returns: Matrix) -> Matrix:
    inv = 1.0 / returns.std(axis=0, ddof=1)
    out: Matrix = inv / inv.sum()
    return out
